from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import paho.mqtt.client as mqtt
import psycopg
import pytest
from psycopg import Connection

import myproj.collector as collector
from myproj.models import TelemetryMessage, TelemetryValidationError


@pytest.fixture
def sample_message() -> TelemetryMessage:
    project_root = Path(__file__).resolve().parents[2]
    text = (project_root / "examples/telemetry/valid.json").read_text(encoding="utf-8")
    return TelemetryMessage.from_json(text)


def test_flush_pending_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    save = Mock()
    monkeypatch.setattr(collector, "insert_telemetry_batch", save)
    state = collector.CollectionState(conn=Mock(spec=Connection))

    collector.flush_pending(state)

    save.assert_not_called()
    assert state.pending == []


def test_flush_pending_reports_duplicates(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sample_message: TelemetryMessage,
) -> None:
    expected = [sample_message, sample_message, sample_message]
    state = collector.CollectionState(
        conn=Mock(spec=Connection), pending=expected.copy()
    )
    saved_messages: list[TelemetryMessage] = []

    def fake_insert(conn, messages):
        assert conn is state.conn
        # flush後に元のリストが空になるため、呼び出し時点の内容を記録する。
        saved_messages.extend(messages)
        return 1

    save = Mock(side_effect=fake_insert)
    monkeypatch.setattr(collector, "insert_telemetry_batch", save)

    collector.flush_pending(state)

    save.assert_called_once()
    assert saved_messages == expected
    assert state.pending == []
    output = capsys.readouterr().out
    assert "1 件のメッセージを保存しました" in output
    assert "重複=2" in output


def test_flush_pending_failed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sample_message: TelemetryMessage,
) -> None:
    save = Mock(side_effect=psycopg.DatabaseError("save failed"))
    monkeypatch.setattr(collector, "insert_telemetry_batch", save)
    state = collector.CollectionState(
        conn=Mock(spec=Connection), pending=[sample_message]
    )

    # 保存失敗の例外が、呼び出し元まで伝わることを確認する。
    with pytest.raises(psycopg.DatabaseError, match="^save failed$"):
        collector.flush_pending(state)

    save.assert_called_once_with(state.conn, [sample_message])
    assert state.pending == [sample_message]
    assert capsys.readouterr().out == ""


def test_collect_telemetry_waits_until_three_messages(
    monkeypatch: pytest.MonkeyPatch,
    sample_message: TelemetryMessage,
) -> None:
    save = Mock()
    monkeypatch.setattr(collector, "insert_telemetry_batch", save)
    state = collector.CollectionState(conn=Mock(spec=Connection))
    messages = [
        sample_message,
        replace(sample_message, sequence_no=sample_message.sequence_no + 1),
    ]
    expected_pending: list[TelemetryMessage] = []

    for message in messages:
        collector.collect_telemetry(
            state,
            f"tmrp/devices/{message.device_id}/telemetry",
            message.to_json().encode("utf-8"),
        )
        expected_pending.append(message)
        assert state.pending == expected_pending
        save.assert_not_called()


def test_collect_telemetry_flushes_on_third_message(
    monkeypatch: pytest.MonkeyPatch,
    sample_message: TelemetryMessage,
) -> None:
    state = collector.CollectionState(conn=Mock(spec=Connection))
    messages = [
        replace(sample_message, sequence_no=sample_message.sequence_no + offset)
        for offset in range(3)
    ]
    saved_messages: list[TelemetryMessage] = []

    def fake_insert(conn, pending):
        assert conn is state.conn
        # 内容と順序を、pendingがclearされる前にコピーする。
        saved_messages.extend(pending)
        return len(pending)

    save = Mock(side_effect=fake_insert)
    monkeypatch.setattr(collector, "insert_telemetry_batch", save)

    for message in messages:
        collector.collect_telemetry(
            state,
            f"tmrp/devices/{message.device_id}/telemetry",
            message.to_json().encode("utf-8"),
        )

    save.assert_called_once()
    assert saved_messages == messages
    assert state.pending == []


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        pytest.param(b"{", TelemetryValidationError, id="invalid-json"),
        pytest.param(b"{}", TelemetryValidationError, id="missing-fields"),
        pytest.param(bytes([255]), UnicodeDecodeError, id="invalid-utf8"),
    ],
)
def test_collect_telemetry_rejects_invalid_input(
    monkeypatch: pytest.MonkeyPatch,
    sample_message: TelemetryMessage,
    payload: bytes,
    expected_error: type[Exception],
) -> None:
    save = Mock()
    monkeypatch.setattr(collector, "insert_telemetry_batch", save)
    expected = [
        sample_message,
        replace(sample_message, sequence_no=sample_message.sequence_no + 1),
    ]
    state = collector.CollectionState(
        conn=Mock(spec=Connection), pending=expected.copy()
    )

    # 不正な入力を3件目として数えず、既存の2件を保持する。
    with pytest.raises(expected_error):
        collector.collect_telemetry(
            state,
            f"tmrp/devices/{sample_message.device_id}/telemetry",
            payload,
        )

    assert state.pending == expected
    save.assert_not_called()


def test_run_collector_receiving_save_failed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sample_message: TelemetryMessage,
) -> None:
    state = collector.CollectionState(conn=Mock(spec=Connection))
    messages = [
        replace(sample_message, sequence_no=sample_message.sequence_no + offset)
        for offset in range(3)
    ]
    error = psycopg.DatabaseError("save failed")
    save = Mock(side_effect=error)
    monkeypatch.setattr(collector, "insert_telemetry_batch", save)

    for message in messages[:2]:
        collector.collect_telemetry(
            state,
            f"tmrp/devices/{message.device_id}/telemetry",
            message.to_json().encode("utf-8"),
        )
    assert state.pending == messages[:2]
    save.assert_not_called()

    # 受信ループ内で3件目が届き、一括保存に失敗する状況を再現する。
    def receive_third_message():
        message = messages[2]
        collector.collect_telemetry(
            state,
            f"tmrp/devices/{message.device_id}/telemetry",
            message.to_json().encode("utf-8"),
        )

    client = Mock(spec=mqtt.Client)
    client.loop_forever.side_effect = receive_third_message

    with pytest.raises(psycopg.DatabaseError, match="^save failed$") as exc_info:
        collector.run_collector(client, state)

    assert exc_info.value is error
    save.assert_called_once_with(state.conn, messages)
    assert state.pending == messages
    client.loop_forever.assert_called_once_with()
    client.disconnect.assert_called_once_with()
    assert capsys.readouterr().out == ""


def test_run_collector_flushes_pending_on_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sample_message: TelemetryMessage,
) -> None:
    state = collector.CollectionState(
        conn=Mock(spec=Connection), pending=[sample_message]
    )
    client = Mock(spec=mqtt.Client)
    # Ctrl+Cを再現する。run_collector自身がこの例外を捕捉する。
    client.loop_forever.side_effect = KeyboardInterrupt()
    saved_messages: list[TelemetryMessage] = []

    def fake_insert(conn, pending):
        assert conn is state.conn
        # 切断する前に残件を保存していることも確認する。
        client.disconnect.assert_not_called()
        saved_messages.extend(pending)
        return 1

    save = Mock(side_effect=fake_insert)
    monkeypatch.setattr(collector, "insert_telemetry_batch", save)

    collector.run_collector(client, state)

    save.assert_called_once()
    assert saved_messages == [sample_message]
    assert state.pending == []
    client.loop_forever.assert_called_once_with()
    client.disconnect.assert_called_once_with()
    output = capsys.readouterr().out
    assert "終了します" in output
    assert "1 件のメッセージを保存しました" in output
    assert "重複=0" in output


def test_run_collector_disconnects_when_shutdown_save_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sample_message: TelemetryMessage,
) -> None:
    state = collector.CollectionState(
        conn=Mock(spec=Connection), pending=[sample_message]
    )
    client = Mock(spec=mqtt.Client)
    client.loop_forever.side_effect = KeyboardInterrupt()
    error = psycopg.DatabaseError("save failed")
    save = Mock(side_effect=error)
    monkeypatch.setattr(collector, "insert_telemetry_batch", save)

    # Ctrl+Cは捕捉されるが、その後の保存で発生したDBエラーは伝わる。
    with pytest.raises(psycopg.DatabaseError, match="^save failed$") as exc_info:
        collector.run_collector(client, state)

    assert exc_info.value is error
    save.assert_called_once_with(state.conn, [sample_message])
    assert state.pending == [sample_message]
    client.loop_forever.assert_called_once_with()
    # 保存で例外が発生してもfinallyで必ず切断する。
    client.disconnect.assert_called_once_with()
    output = capsys.readouterr().out
    assert "終了します" in output
    assert "フラッシュ完了" not in output
