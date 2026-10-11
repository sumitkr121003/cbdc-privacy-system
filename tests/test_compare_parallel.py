"""Correctness checks for the preliminary sequential/parallel benchmark."""

from datetime import datetime, timezone
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

from benchmarks.compare_parallel import (
    SUPPORTED_CONTENTION_PROFILES,
    SUPPORTED_TRANSACTION_COUNTS,
    SUPPORTED_WORKER_COUNTS,
    aggregate_runs,
    build_report,
    render_markdown_report,
    run_matrix,
    run_comparison,
    summarize_latencies_ms,
    _measure_execution,
    _prepare_workload,
    safe_speedup_ratio,
    _process_cpu_capacity_percent,
    _calculate_whole_system_cpu_utilization,
    _read_windows_system_times,
    write_report,
)


def test_latency_summary_uses_nearest_rank_percentiles():
    summary = summarize_latencies_ms([1_000_000, 2_000_000, 3_000_000, 4_000_000])

    assert summary == {
        "mean_ms": 2.5,
        "p50_ms": 2.0,
        "p95_ms": 4.0,
        "p99_ms": 4.0,
    }


@pytest.mark.parametrize(
    "sequential,parallel,expected",
    [(10.0, 15.0, 1.5), (0.0, 1.0, None), (1.0, 0.0, None),
     (float("inf"), 1.0, None), (1.0, float("nan"), None)],
)
def test_speedup_ratio_handles_valid_and_invalid_throughput(sequential, parallel, expected):
    assert safe_speedup_ratio(sequential, parallel) == expected


def test_process_cpu_capacity_percent_is_labeled_and_handles_invalid_intervals():
    assert _process_cpu_capacity_percent(500, 1_000, 2) == 25.0
    assert _process_cpu_capacity_percent(1, 0, 2) is None
    assert _process_cpu_capacity_percent(1, 1, 0) is None


def test_whole_system_cpu_counter_delta_calculation_and_invalid_counters():
    assert _calculate_whole_system_cpu_utilization(
        (100, 200, 50), (160, 240, 70)
    ) == 80.0
    assert _calculate_whole_system_cpu_utilization((10, 20, 5), (10, 20, 5)) is None
    assert _calculate_whole_system_cpu_utilization((10, 20, 5), (10, 20, 6)) is None
    assert _calculate_whole_system_cpu_utilization(None, (1, 1, 0)) is None


def test_windows_system_counter_reader_handles_failure_and_unsupported_platform(monkeypatch):
    import benchmarks.compare_parallel as benchmark_module

    monkeypatch.setattr(benchmark_module.sys, "platform", "linux")
    assert _read_windows_system_times() is None

    monkeypatch.setattr(benchmark_module.sys, "platform", "win32")
    failed_api = SimpleNamespace(GetSystemTimes=lambda *_args: 0)
    monkeypatch.setattr(benchmark_module.ctypes, "WinDLL", lambda *_args, **_kwargs: SimpleNamespace(
        GetSystemTimes=failed_api.GetSystemTimes
    ), raising=False)
    assert _read_windows_system_times() is None

    def raising_api(*_args):
        raise OSError("mocked GetSystemTimes failure")

    monkeypatch.setattr(
        benchmark_module.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: SimpleNamespace(GetSystemTimes=raising_api),
        raising=False,
    )
    assert _read_windows_system_times() is None


def test_comparison_uses_signed_equivalent_successful_workloads():
    result = run_comparison(transaction_count=100, workers=2)

    assert result["warmup_outcomes_equivalent"] is True
    assert result["initial_supply"] == 300
    assert len(result["measured_runs"]) == 3
    for run in result["measured_runs"]:
        assert run["outcomes_equivalent"] is True
        for path in ("sequential", "parallel"):
            assert run[path]["attempted"] == 100
            assert run[path]["successful"] == 100
            assert run[path]["conflict_participants"] == 0
            assert run[path]["conflicting"] == 0
            assert run[path]["rejected"] == 0
            assert isinstance(run[path]["process_cpu_seconds"], float)
            assert run[path]["process_cpu_seconds"] >= 0
            assert run[path]["process_cpu_capacity_percent"] is None or (
                run[path]["process_cpu_capacity_percent"] >= 0
            )
            assert isinstance(run[path]["peak_traced_memory_bytes"], int)
            assert run[path]["peak_traced_memory_bytes"] >= 0

        assert set(run["sequential"]["per_transaction_latency"]) == {
            "mean_ms", "p50_ms", "p95_ms", "p99_ms"
        }
        assert "per_transaction_latency" not in run["parallel"]
        assert set(run["parallel"]["batch_submission_to_final_outcome_latency"]) == {
            "mean_ms", "p50_ms", "p95_ms", "p99_ms"
        }
        latency = run["parallel"]["batch_submission_to_final_outcome_latency"]
        assert latency["p50_ms"] <= latency["p95_ms"] <= latency["p99_ms"]
        assert run["parallel"]["completion_timestamp_recording_overhead_mean_ns"] >= 0
        assert "whole_system_cpu_utilization_percent" in run["parallel"]
        assert run["parallel"]["batch_latency_seconds"] > 0
        assert run["parallel"]["amortized_ms_per_attempted_transaction"] > 0


def test_aggregate_runs_calculates_means_and_sample_standard_deviations():
    runs = []
    for index, (sequential_elapsed, parallel_elapsed, seq_rate, par_rate) in enumerate((
        (1.0, 2.0, 10.0, 5.0),
        (2.0, 4.0, 5.0, 2.5),
        (3.0, 6.0, 10.0, 5.0),
    ), start=1):
        runs.append({
            "sequential": {
                "elapsed_seconds": sequential_elapsed,
                "process_cpu_seconds": float(index),
                "peak_traced_memory_bytes": index * 100,
                "throughput_attempted_per_second": seq_rate,
                "throughput_successful_per_second": seq_rate,
            },
            "parallel": {
                "batch_latency_seconds": parallel_elapsed,
                "process_cpu_seconds": float(index * 2),
                "peak_traced_memory_bytes": index * 200,
                "throughput_attempted_per_second": par_rate,
                "throughput_successful_per_second": par_rate,
            },
        })

    summary = aggregate_runs(runs)

    assert summary["sequential"]["elapsed_seconds"] == {
        "mean": 2.0,
        "sample_standard_deviation": 1.0,
    }
    assert summary["parallel"]["batch_latency_seconds"] == {
        "mean": 4.0,
        "sample_standard_deviation": 2.0,
    }
    assert summary["sequential"]["throughput_attempted_per_second"] == {
        "mean": 25.0 / 3.0,
        "sample_standard_deviation": pytest.approx(2.8867513459),
    }
    assert summary["sequential"]["process_cpu_seconds"] == {
        "mean": 2.0,
        "sample_standard_deviation": 1.0,
    }
    assert summary["sequential"]["peak_traced_memory_bytes"] == {
        "mean": 200.0,
        "sample_standard_deviation": 100.0,
    }
    assert summary["parallel"]["process_cpu_seconds"] == {
        "mean": 4.0,
        "sample_standard_deviation": 2.0,
    }
    assert summary["parallel"]["peak_traced_memory_bytes"] == {
        "mean": 400.0,
        "sample_standard_deviation": 200.0,
    }


def test_measure_execution_collects_process_wall_and_peak_python_memory():
    def allocate_during_execution():
        allocation = bytearray(32_768)
        return len(allocation)

    result, wall_ns, process_cpu_ns, peak_bytes, system_cpu_percent = _measure_execution(
        allocate_during_execution
    )

    assert result == 32_768
    assert isinstance(wall_ns, int) and wall_ns >= 0
    assert isinstance(process_cpu_ns, int) and process_cpu_ns >= 0
    assert isinstance(peak_bytes, int) and peak_bytes > 0
    assert system_cpu_percent is None


def test_measure_execution_collects_mocked_whole_system_utilization(monkeypatch):
    import benchmarks.compare_parallel as benchmark_module

    snapshots = iter(((100, 200, 50), (160, 240, 70)))
    monkeypatch.setattr(
        benchmark_module, "_read_windows_system_times", lambda: next(snapshots)
    )
    result, _, _, _, utilization = _measure_execution(lambda: "done")

    assert result == "done"
    assert utilization == 80.0


def test_report_contains_environment_configuration_runs_and_summary():
    configuration = run_matrix((100,), (2,), (20,))[0]
    generated_at = datetime(2026, 10, 11, 12, 30, tzinfo=timezone.utc)

    report = build_report(configuration, generated_at=generated_at)
    serialized = json.dumps(report)
    decoded = json.loads(serialized)
    markdown = render_markdown_report(decoded)
    workspace = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="benchmark-report-test-", dir=workspace) as temp_dir:
        output_dir = Path(temp_dir) / "nested" / "reports"
        json_path, markdown_path = write_report(decoded, output_dir)

        assert decoded["metadata"]["generated_at_utc"] == "2026-10-11T12:30:00+00:00"
        assert decoded["metadata"]["python_version"]
        assert decoded["metadata"]["platform"]
        assert decoded["configuration"]["transaction_count"] == 100
        assert decoded["configuration"]["workers"] == 2
        assert decoded["configuration"]["contention_percent"] == 20
        assert decoded["configuration"]["collision_pattern"] == "pairwise"
        assert decoded["configuration"]["warmup_run_count"] == 1
        assert decoded["configuration"]["measured_run_count"] == 3
        assert "time.process_time_ns" in decoded["measurement"]["process_cpu"]
        assert len(decoded["measured_runs"]) == 3
        assert all(run["outcomes_equivalent"] for run in decoded["measured_runs"])
        assert "Peak traced bytes" in markdown
        assert "sample standard deviation" in markdown
        assert "Sequential per-transaction latency" in markdown
        assert "parallel attempted throughput / sequential attempted throughput" in decoded["speedup"]["definition"]
        assert len(decoded["speedup"]["per_measured_run"]) == 3
        assert decoded["speedup"]["ratio_of_mean_attempted_throughput"] > 0
        assert "batch-submission-to-final-outcome latency" in markdown
        assert "Whole-system CPU utilization" in markdown
        assert "completion_timestamp_recording_overhead_mean_ns" in decoded["summary"]["parallel"]
        assert "parallel_batch_submission_to_final_outcome_latency" in decoded["summary"]
        assert "not whole-system CPU utilization" in decoded["measurement"]["process_cpu_capacity_percent"]
        assert json.loads(json_path.read_text(encoding="utf-8")) == decoded
        assert markdown_path.read_text(encoding="utf-8") == markdown

        second_json_path, second_markdown_path = write_report(decoded, output_dir)
        assert second_json_path != json_path
        assert second_markdown_path != markdown_path
        assert json_path.exists() and second_json_path.exists()
        assert markdown_path.exists() and second_markdown_path.exists()


def test_report_formats_unavailable_whole_system_cpu_as_na():
    report = build_report(run_matrix((100,), (2,), (0,))[0])
    unavailable = copy.deepcopy(report)
    for run in unavailable["measured_runs"]:
        for path in ("sequential", "parallel"):
            run[path]["whole_system_cpu_utilization_percent"] = None
    for path in ("sequential", "parallel"):
        unavailable["summary"][path]["whole_system_cpu_utilization_percent"] = {
            "mean": None,
            "sample_standard_deviation": None,
        }

    markdown = render_markdown_report(unavailable)

    assert "whole_system_cpu_utilization_percent: mean n/a" in markdown
    assert "n/a |" in markdown


def test_aggregate_runs_requires_multiple_samples():
    with pytest.raises(ValueError, match="At least two"):
        aggregate_runs([])


def test_supported_sizes_generate_signed_transactions_with_distinct_inputs():
    (
        wallets,
        transactions,
        initial_supply,
        contention,
        conflict_participants,
        conflict_groups,
        collision_pattern,
    ) = _prepare_workload(10_000)

    assert SUPPORTED_TRANSACTION_COUNTS == (100, 1_000, 10_000)
    assert SUPPORTED_CONTENTION_PROFILES == (0, 20, 50)
    assert len(wallets) == 1_000
    assert len(transactions) == 10_000
    assert initial_supply == 30_000
    assert (contention, conflict_participants, conflict_groups) == (0, 0, 0)
    assert collision_pattern == "pairwise"
    input_ids = [transaction.input_ids[0] for transaction in transactions]
    assert len(input_ids) == len(set(input_ids))
    for index in (0, len(transactions) - 1):
        owner, wallet = wallets[index % len(wallets)]
        transaction = transactions[index]
        assert transaction.sender == owner
        assert transaction.signature is not None
        message = wallet.create_payment_message(
            wallet.get_address(),
            transaction.recipient,
            transaction.amount,
            transaction.fee,
            list(transaction.input_ids),
        )
        assert wallet.verify_signature(message, transaction.signature)


def test_matrix_runs_requested_worker_configurations_with_fresh_equivalent_outcomes():
    configurations = run_matrix((100,), (1, 2))

    assert SUPPORTED_WORKER_COUNTS == (1, 2, 4, 8)
    assert [item["workers"] for item in configurations] == [1, 2]
    for item in configurations:
        result = item["comparison"]
        assert item["transaction_count"] == 100
        assert result["warmup_outcomes_equivalent"] is True
        assert len(result["measured_runs"]) == 3
        assert all(run["outcomes_equivalent"] for run in result["measured_runs"])
        assert all(
            run[path]["attempted"] == run[path]["successful"] == 100
            and run[path]["rejected"] == 0
            for run in result["measured_runs"]
            for path in ("sequential", "parallel")
        )


@pytest.mark.parametrize("count", [0, 99, 1001, True])
def test_comparison_rejects_out_of_scope_or_invalid_workload_size(count):
    with pytest.raises(ValueError, match="transaction_count"):
        run_comparison(transaction_count=count)


@pytest.mark.parametrize("workers", [0, 3, True])
def test_comparison_rejects_unsupported_worker_count(workers):
    with pytest.raises(ValueError, match="workers"):
        run_comparison(transaction_count=100, workers=workers)


def test_matrix_rejects_empty_or_duplicate_configurations():
    with pytest.raises(ValueError, match="At least one transaction"):
        run_matrix((), (1,))
    with pytest.raises(ValueError, match="At least one worker"):
        run_matrix((100,), ())
    with pytest.raises(ValueError, match="duplicates"):
        run_matrix((100, 100), (1,))
    with pytest.raises(ValueError, match="duplicates"):
        run_matrix((100,), (1, 1))
    with pytest.raises(ValueError, match="transaction counts"):
        run_matrix((101,), (1,))
    with pytest.raises(ValueError, match="workers"):
        run_matrix((100,), (3,))


@pytest.mark.parametrize(
    "profile, expected_participants, expected_losers, expected_successes",
    [(0, 0, 0, 100), (20, 20, 10, 90), (50, 50, 25, 75)],
)
def test_contention_profiles_have_deterministic_pair_conflict_counts(
    profile, expected_participants, expected_losers, expected_successes
):
    first = run_comparison(100, workers=2, contention_percent=profile)
    second = run_comparison(100, workers=2, contention_percent=profile)

    assert first["contention_percent"] == profile
    assert first["conflict_participants"] == expected_participants
    assert first["conflict_group_count"] == expected_participants // 2
    assert first["summary"]["counts"] == {
        "attempted": 100,
        "conflict_participants": expected_participants,
        "successful": expected_successes,
        "conflicting": expected_losers,
        "rejected": 0,
    }
    assert second["summary"]["counts"] == first["summary"]["counts"]
    assert first["warmup_outcomes_equivalent"] is True
    assert second["warmup_outcomes_equivalent"] is True
    for result in (first, second):
        assert len(result["measured_runs"]) == 3
        for run in result["measured_runs"]:
            assert run["outcomes_equivalent"] is True
            for path in ("sequential", "parallel"):
                assert run[path]["conflict_participants"] == expected_participants
                assert run[path]["conflicting"] == expected_losers
                assert run[path]["successful"] == expected_successes
                assert run[path]["rejected"] == 0


def test_contention_rejects_unsupported_profile():
    with pytest.raises(ValueError, match="contention_percent"):
        run_comparison(100, workers=1, contention_percent=30)


def test_matrix_rejects_invalid_contention_profiles():
    with pytest.raises(ValueError, match="contention profiles"):
        run_matrix((100,), (1,), (10,))
    with pytest.raises(ValueError, match="duplicates"):
        run_matrix((100,), (1,), (0, 0))


def test_hotspot_workload_is_deterministic_and_preserves_ledger_integrity():
    first_workload = _prepare_workload(100, 20, "hotspot")
    second_workload = _prepare_workload(100, 20, "hotspot")
    first_txs = first_workload[1]
    second_txs = second_workload[1]
    first_inputs = [tx.input_ids[0] for tx in first_txs]
    second_inputs = [tx.input_ids[0] for tx in second_txs]
    first_shared = [input_id for input_id in set(first_inputs) if first_inputs.count(input_id) > 1]
    second_shared = [input_id for input_id in set(second_inputs) if second_inputs.count(input_id) > 1]

    assert len(first_shared) == 1
    assert len(second_shared) == 1
    assert first_inputs.count(first_shared[0]) == 20
    assert second_inputs.count(second_shared[0]) == 20
    assert first_workload[3:] == (20, 20, 1, "hotspot")

    result = run_comparison(100, workers=2, contention_percent=20, collision_pattern="hotspot")
    repeated_result = run_comparison(
        100, workers=2, contention_percent=20, collision_pattern="hotspot"
    )
    assert result["collision_pattern"] == "hotspot"
    assert result["summary"]["counts"] == {
        "attempted": 100,
        "conflict_participants": 20,
        "successful": 81,
        "conflicting": 19,
        "rejected": 0,
    }
    assert repeated_result["summary"]["counts"] == result["summary"]["counts"]
    assert result["warmup_outcomes_equivalent"] is True
    for run in result["measured_runs"]:
        assert run["outcomes_equivalent"] is True
        for path in ("sequential", "parallel"):
            assert run[path]["successful"] + run[path]["conflicting"] + run[path]["rejected"] == 100
