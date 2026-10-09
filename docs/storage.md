# PostgreSQL保存の再現手順

Week 6で実装したスキーマ、重複スキップ、一括保存、DBテストを再現する。
MQTTからの送受信と終了時保存は[MQTT手順](mqtt.md)を参照する。
コマンドはTMRPのルートで実行する。

## 1. ローカルDBの準備

確認環境はUbuntu 24.04／WSL、PostgreSQL 16、Python 3.12。
現在の保存用スクリプトは次の接続先を使用する。

| 設定 | 値 |
|---|---|
| Unixソケット | `/var/run/postgresql` |
| ポート | `5432` |
| DB | `tmrp_dev` |
| ロール | `shou` |
| Python接続のタイムゾーン | `UTC` |

ローカルのpeer認証を使うため、ここではOSユーザー名もshouを前提とする。
別のOSユーザーで再現する場合は、その名前でDBロールを用意し、コマンドと
`scripts/store_sample_telemetry.py`、`scripts/subscribe_telemetry.py`の`user=shou`を合わせる。
`TMRP_TEST_DSN`はテスト専用で、これらのスクリプトの接続先は変更しない。

以下のインストール・ロール・DB作成は、未準備の環境でのみ行う。
既存の学習環境では接続確認へ進む。

```bash
# Ubuntuのパッケージ情報を更新し、PostgreSQL 16とクライアントをインストールする。
sudo apt update
sudo apt install postgresql-16 postgresql-client-16

# クラスタのバージョン、名前、ポート、online/downを確認する。
pg_lsclusters

# 16/mainがdownの場合に起動する。onlineなら実行不要。
sudo pg_ctlcluster 16 main start

# LOGIN可能で、管理権限を持たない学習用ロールを作る。既存なら実行不要。
sudo -u postgres createuser -h /var/run/postgresql -p 5432 \
  --login --no-superuser --no-createdb --no-createrole shou

# shouを所有者とする学習用DBを作る。既存なら実行不要。
sudo -u postgres createdb -h /var/run/postgresql -p 5432 --owner=shou tmrp_dev

# 本体、Psycopg、開発ツールを仮想環境へインストールする。
.venv/bin/python -m pip install -e ".[dev]"
```

ロール作成オプションは[PostgreSQL公式資料](https://www.postgresql.org/docs/16/app-createuser.html)を参照。

```bash
# 接続ユーザーとDBを確認する。
# -X: 個人用psql設定を読み込まない。-w: パスワード入力を求めず失敗時は終了する。
# -h/-p/-U/-d: 接続先ソケット、ポート、ロール、DB。-c: 指定SQLを実行する。
psql -X -w -h /var/run/postgresql -p 5432 -U shou -d tmrp_dev \
  -c 'SELECT current_user, current_database();'
```

## 2. スキーマを作る

[sql/001_create_telemetry.sql](../sql/001_create_telemetry.sql)を初回だけ適用する。
すでに`telemetry_messages`がある場合は再適用せず、構造確認へ進む。
このファイルは自動マイグレーションや再実行用のSQLではない。

```bash
# -fでSQLファイルを実行し、ON_ERROR_STOP=1でSQLエラー時に終了する。
psql -X -w -h /var/run/postgresql -p 5432 -U shou -d tmrp_dev \
  -v ON_ERROR_STOP=1 -f sql/001_create_telemetry.sql

# テーブルの列、型、制約を確認する。
psql -X -w -h /var/run/postgresql -p 5432 -U shou -d tmrp_dev \
  -c '\d telemetry_messages'
```

`psql`のオプションは[公式資料](https://www.postgresql.org/docs/16/app-psql.html)を参照。

| 列 | 内容 |
|---|---|
| `id` | DBが生成する主キー |
| `device_id` | 空文字不可、NULL不可 |
| `sequence_no` | 0以上、NULL不可 |
| `event_time` | タイムゾーン付き日時、NULL不可 |
| `battery_percent` | 0〜100、欠損時はNULL |
| `payload` | モデルの`to_dict()`をJSONBとして保存、NULL不可 |
| `received_at` | 挿入トランザクションの開始時刻を既定値とするDB記録時刻 |

重複判定は`(device_id, event_time, sequence_no)`の組み合わせで行う。
同じキーは追加せず、既存行も更新しない。本文の別の値が違っていても先に保存した値を維持する。
この設計は再送時に元のevent_timeとsequence_noを維持することを前提とする。
シミュレーターの再実行ではevent_timeが変わるため、新しいイベントとして保存される。

## 3. 固定サンプルを保存する

```bash
# 正常サンプルを保存する。初回は新規保存、保存済みなら重複スキップになる。
.venv/bin/python scripts/store_sample_telemetry.py

# 同じファイルをもう一度保存し、重複スキップになることを確認する。
.venv/bin/python scripts/store_sample_telemetry.py

# UTCで固定サンプルの保存結果を確認する。キーに一致する行は1件。
psql -X -w -h /var/run/postgresql -p 5432 -U shou -d tmrp_dev \
  -c "SET TIME ZONE 'UTC';
      SELECT device_id, sequence_no, event_time, battery_percent
      FROM telemetry_messages
      WHERE device_id = 'robot-001' AND sequence_no = 1001
        AND event_time = '2024-06-01T12:00:00Z'::timestamptz;"
```

初回の成功表示は`Telemetry data inserted successfully`、重複時は
`同じイベントが保存済みのため、追加しませんでした`。保存済みの環境では初回から重複になる。
期待するバッテリー値は82.5。確認のために既存データを削除する必要はない。

## 保存関数とトランザクション

- `insert_telemetry(conn, message) -> bool`：新規挿入ならTrue、重複ならFalse。
  接続作成・コミット・表示は呼び出し側が担当する。
- `insert_telemetry_batch(conn, messages) -> int`：Iterableを順に処理し、新規挿入件数を返す。
  全件を1つのトランザクションにまとめ、空入力は0、途中の例外ではそのバッチを取り消す。
- 一括保存は単件SQLを繰り返す実装であり、COPYや複数行INSERTによる高速化は未実装。
- すでに外側のトランザクションがある場合、内側はセーブポイントになり、最終確定は呼び出し側が担当する。
  subscriberは`autocommit=True`で接続し、通常はバッチ関数の終了時にコミットする。

挙動の詳細は[Psycopgのトランザクション資料](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)を参照。

## DBテストと品質チェック

```bash
# テスト用接続先をこのコマンドに限って指定し、DBテスト7件を詳細表示で実行する。
TMRP_TEST_DSN='host=/var/run/postgresql port=5432 dbname=tmrp_dev user=shou' \
  .venv/bin/python -m pytest tests/integration/test_storage.py -v

# DBテストを含む全テストを実行する。Week 6仕上げ時点では251 passed。
TMRP_TEST_DSN='host=/var/run/postgresql port=5432 dbname=tmrp_dev user=shou' \
  .venv/bin/python -m pytest -q

# ファイルを変更せず、スクリプトも含めたコード規約と書式を検査する。
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m ruff format --check src tests scripts

# src内の型をstrict設定で検査する。
.venv/bin/python -m mypy
```

`TMRP_TEST_DSN`を設定しない場合、DBテスト7件はskipする。DB検証の成功と混同しない。
設定した接続先へ接続できない場合は失敗する。
fixtureはテストごとに一時テーブルを作り、`search_path=pg_temp`で検索先を限定する。
接続を閉じると一時テーブルは消える。既存のpublicテーブルには書き込まない。
テスト用DBロールにはDBへの接続と一時テーブル作成権限が必要。

7件は単件保存・重複・呼び出し側ロールバック、一括保存・重複・空入力・途中例外を検証する。
subscriberのバッファや終了処理の自動テストは、現時点ではpytestに未追加。
MQTTを含む確認は[通し確認](mqtt.md)で行う。

`scripts/check_test.sh`はsrc/testsを自動整形して検査する。DBテストも実行する場合は
同様に`TMRP_TEST_DSN`を渡す。スクリプト自身は環境変数を設定せず、scriptsのRuff検査も行わない。
