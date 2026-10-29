"""Guard against falsely passing missing data or a throttled load generator."""

import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[3] / "scripts/benchmark/power_receiver.py"
SPEC = importlib.util.spec_from_file_location("power_benchmark", PATH)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


@pytest.fixture
def good_result():
    return {
        "scenario": "baseline",
        "offered": 120,
        "broker_confirmed": 120,
        "database_matches": True,
        "outcomes_match": True,
        "processing_errors": 0,
        "ready_at_end": True,
        "send_lag_p99_ms": 1,
        "receiver_peak_rss_mib": 40,
        "drain_seconds": 0.1,
        "scheduled_to_processed_p95_ms": 50,
        "scheduled_to_processed_p99_ms": 80,
        "unready_samples": 0,
        "receiver_cpu_percent_one_core": 20,
        "receiver_rss_growth_mib": 1,
        "send_seconds": 1,
        "clock_drift_ms": 0,
    }


def test_nearest_rank_and_missing_measurements():
    assert benchmark.percentile([], 99) is None
    assert benchmark.percentile(list(range(1, 101)), 95) == 95
    assert benchmark.percentile([3], 99) == 3


def test_good_run_passes(good_result):
    assert all(benchmark.assess(good_result).values())


@pytest.mark.parametrize(
    "field,value",
    [
        ("broker_confirmed", 119),
        ("database_matches", False),
        ("outcomes_match", False),
        ("processing_errors", 1),
        ("ready_at_end", False),
        ("send_lag_p99_ms", 150),
        ("receiver_peak_rss_mib", 300),
        ("drain_seconds", 31),
        ("scheduled_to_processed_p95_ms", 501),
        ("scheduled_to_processed_p99_ms", 1001),
        ("scheduled_to_processed_p99_ms", None),
        ("unready_samples", 1),
        ("receiver_cpu_percent_one_core", 71),
        ("clock_drift_ms", 51),
    ],
)
def test_failed_or_invalid_measurements_never_pass(good_result, field, value):
    good_result[field] = value
    assert not all(benchmark.assess(good_result).values())


def test_burst_uses_drain_budget_and_requires_actual_burst(good_result):
    good_result.update(
        scenario="burst", send_lag_p99_ms=1500, scheduled_to_processed_p99_ms=20000
    )
    assert all(benchmark.assess(good_result).values())
    good_result["send_seconds"] = 3
    assert not all(benchmark.assess(good_result).values())


def test_recovery_allows_planned_offline_period_but_not_loss(good_result):
    good_result.update(
        scenario="recovery", unready_samples=20, scheduled_to_processed_p99_ms=11000
    )
    assert all(benchmark.assess(good_result).values())
    good_result["database_matches"] = False
    assert not all(benchmark.assess(good_result).values())


def test_soak_fails_memory_growth(good_result):
    good_result.update(scenario="soak", receiver_rss_growth_mib=11)
    assert not all(benchmark.assess(good_result).values())
