"""Compare signed sequential transfers with the existing parallel batch path.

Setup (wallet generation, funding, transaction construction, and signing) is
outside the timed intervals. Sequential timing covers each ``transfer_signed``
call; parallel timing covers the complete ``process_batch`` call, including
worker-pool setup, validation, ordered commits, and pool shutdown.
"""

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import math
import os
import platform
import statistics
import sys
import time
import tracemalloc
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.batch_processor import BatchTransactionProcessor
from src.utxo_engine import Transaction, UTXOEngine
from src.wallet import Wallet

SUPPORTED_TRANSACTION_COUNTS = (100, 1_000, 10_000)
SUPPORTED_WORKER_COUNTS = (1, 2, 4, 8)
SUPPORTED_CONTENTION_PROFILES = (0, 20, 50)
SUPPORTED_COLLISION_PATTERNS = ("pairwise", "hotspot")
# UTXOEngine wallet registration scans already registered wallets. Cap wallet
# count so 10,000-transaction setup stays practical; each attempted transaction
# still receives one input, shared only within its deliberate conflict pair.
MAX_DISTINCT_WALLETS = 1_000


def summarize_latencies_ms(samples_ns):
    """Return sequential per-call latency statistics in milliseconds."""
    if not samples_ns:
        raise ValueError("At least one latency sample is required")

    ordered = sorted(samples_ns)

    def percentile(fraction):
        rank = max(0, math.ceil(fraction * len(ordered)) - 1)
        return ordered[rank] / 1_000_000

    return {
        "mean_ms": statistics.fmean(samples_ns) / 1_000_000,
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
    }


def safe_speedup_ratio(sequential_throughput, parallel_throughput):
    """Return parallel/sequential throughput, or None for invalid rates."""
    values = (sequential_throughput, parallel_throughput)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        for value in values
    ):
        return None
    return parallel_throughput / sequential_throughput


def _process_cpu_capacity_percent(process_cpu_ns, wall_ns, logical_cpu_count=None):
    """Estimate process CPU share of total logical-processor capacity."""
    if logical_cpu_count is None:
        logical_cpu_count = os.cpu_count()
    if (
        isinstance(process_cpu_ns, bool) or not isinstance(process_cpu_ns, int)
        or isinstance(wall_ns, bool) or not isinstance(wall_ns, int)
        or process_cpu_ns < 0 or wall_ns <= 0
        or not isinstance(logical_cpu_count, int) or logical_cpu_count <= 0
    ):
        return None
    return process_cpu_ns / (wall_ns * logical_cpu_count) * 100


def _filetime_value(filetime):
    return (filetime.dwHighDateTime << 32) | filetime.dwLowDateTime


def _read_windows_system_times():
    """Read Windows cumulative (kernel, user, idle) system times in 100ns."""
    if sys.platform != "win32":
        return None
    try:
        idle_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        get_system_times = ctypes.WinDLL(
            "kernel32", use_last_error=True
        ).GetSystemTimes
        get_system_times.argtypes = [
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        get_system_times.restype = wintypes.BOOL
        if not get_system_times(
            ctypes.byref(idle_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        return (
            _filetime_value(kernel_time),
            _filetime_value(user_time),
            _filetime_value(idle_time),
        )
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return None


def _calculate_whole_system_cpu_utilization(before, after):
    """Calculate whole-system busy percentage from (kernel,user,idle) deltas."""
    try:
        if before is None or after is None or len(before) != 3 or len(after) != 3:
            return None
        if any(type(value) is not int for value in (*before, *after)):
            return None
    except TypeError:
        return None
    try:
        kernel_delta, user_delta, idle_delta = (
            after[index] - before[index] for index in range(3)
        )
    except (TypeError, ValueError):
        return None
    total_delta = kernel_delta + user_delta
    busy_delta = total_delta - idle_delta
    if total_delta <= 0 or idle_delta < 0 or busy_delta < 0:
        return None
    return busy_delta / total_delta * 100


def _measure_execution(execute):
    """Measure one execution with tracemalloc active for both compared paths.

    Callers must finish workload and ledger preparation before entering this
    helper. Tracing setup/reset, Windows system-counter snapshots, and post-run
    memory inspection are outside the wall/process CPU intervals; allocations
    made by ``execute`` are traced. When tracing was already active, its state
    is preserved. Windows counter reads immediately bracket the measured call.
    """
    tracing_was_active = tracemalloc.is_tracing()
    if not tracing_was_active:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        baseline_current, _ = tracemalloc.get_traced_memory()
        system_cpu_before = _read_windows_system_times()
        wall_start_ns = time.perf_counter_ns()
        process_cpu_start_ns = time.process_time_ns()
        try:
            result = execute()
        finally:
            wall_elapsed_ns = time.perf_counter_ns() - wall_start_ns
            process_cpu_elapsed_ns = (
                time.process_time_ns() - process_cpu_start_ns
            )
            system_cpu_after = _read_windows_system_times()
        whole_system_cpu_percent = _calculate_whole_system_cpu_utilization(
            system_cpu_before, system_cpu_after
        )
        _, peak_bytes = tracemalloc.get_traced_memory()
        execution_peak_bytes = max(0, peak_bytes - baseline_current)
        return (
            result,
            wall_elapsed_ns,
            process_cpu_elapsed_ns,
            execution_peak_bytes,
            whole_system_cpu_percent,
        )
    finally:
        if not tracing_was_active:
            tracemalloc.stop()


def _prepare_workload(transaction_count, contention_percent=0, collision_pattern="pairwise"):
    """Prepare signed workloads with participant-rate input contention.

    ``contention_percent`` is the percentage of attempted transactions that
    belong to a collision group sharing one UTXO. In ``pairwise`` mode each
    group has two participants; in ``hotspot`` mode all participants share one
    UTXO. A group's first committed transaction wins; other attempts conflict.
    """
    if (
        type(transaction_count) is not int
        or transaction_count not in SUPPORTED_TRANSACTION_COUNTS
    ):
        raise ValueError(
            "transaction_count must be one of 100, 1000, or 10000"
        )
    if (
        type(contention_percent) is not int
        or contention_percent not in SUPPORTED_CONTENTION_PROFILES
    ):
        raise ValueError("contention_percent must be 0, 20, or 50")
    if collision_pattern not in SUPPORTED_COLLISION_PATTERNS:
        raise ValueError("collision_pattern must be 'pairwise' or 'hotspot'")

    participant_count = transaction_count * contention_percent // 100
    conflict_group_count = (
        participant_count // 2 if collision_pattern == "pairwise"
        else int(participant_count > 0)
    )
    independent_count = transaction_count - participant_count
    funded_input_count = conflict_group_count + independent_count
    wallet_count = min(funded_input_count, MAX_DISTINCT_WALLETS)
    wallets = [
        (f"sender-{index}", Wallet()) for index in range(wallet_count)
    ]
    transactions = []

    def append_signed_transaction(owner, wallet, input_id, recipient_index):
        recipient = f"recipient-{recipient_index}"
        signature = wallet.sign_payment(
            sender=wallet.get_address(),
            recipient=recipient,
            amount=1,
            fee=1,
            input_ids=[input_id],
        )
        transactions.append(Transaction(
            sender=owner,
            recipient=recipient,
            amount=1,
            fee=1,
            input_ids=(input_id,),
            signature=signature,
        ))

    recipient_index = 0
    funding_index = 0
    group_sizes = (
        [2] * conflict_group_count if collision_pattern == "pairwise"
        else ([participant_count] if participant_count else [])
    )
    for group_size in group_sizes:
        owner, wallet = wallets[funding_index % wallet_count]
        funding_index += 1
        input_id = f"genesis-{wallet.get_address()}-{funding_index}"
        for _ in range(group_size):
            append_signed_transaction(owner, wallet, input_id, recipient_index)
            recipient_index += 1

    for _ in range(independent_count):
        owner, wallet = wallets[funding_index % wallet_count]
        funding_index += 1
        input_id = f"genesis-{wallet.get_address()}-{funding_index}"
        append_signed_transaction(owner, wallet, input_id, recipient_index)
        recipient_index += 1

    initial_supply = funded_input_count * 3
    _validate_workload(
        transactions, contention_percent, participant_count, conflict_group_count,
        collision_pattern,
    )
    return (
        wallets,
        transactions,
        initial_supply,
        contention_percent,
        participant_count,
        conflict_group_count,
        collision_pattern,
    )


def _validate_workload(
    transactions, contention_percent, expected_participants, expected_groups,
    collision_pattern="pairwise",
):
    """Check collision participants and the selected conflict-group shape."""
    input_counts = Counter(tx.input_ids[0] for tx in transactions)
    shared_counts = [count for count in input_counts.values() if count > 1]
    expected_group_size = 2 if collision_pattern == "pairwise" else expected_participants
    if any(count != expected_group_size for count in shared_counts):
        raise AssertionError("Contested inputs do not match the collision pattern")
    participant_count = sum(shared_counts)
    if participant_count != expected_participants:
        raise AssertionError("Workload conflict-participant count is incorrect")
    if len(shared_counts) != expected_groups:
        raise AssertionError("Workload conflict-group count is incorrect")
    if participant_count * 100 != len(transactions) * contention_percent:
        raise AssertionError("Workload does not match the requested contention rate")


def _fresh_ledger_pair(wallets, transactions):
    """Create two fresh ledgers with matching registrations and test funds."""
    sequential_engine = UTXOEngine()
    parallel_engine = UTXOEngine()
    wallets_by_owner = dict(wallets)
    for owner, wallet in wallets:
        sequential_engine.register_wallet(owner, wallet)
        parallel_engine.register_wallet(owner, wallet)

    funded_inputs = set()
    for transaction in transactions:
        wallet = wallets_by_owner[transaction.sender]
        input_id = transaction.input_ids[0]
        if input_id in funded_inputs:
            continue
        sequential_input = sequential_engine.issue_test_funds(
            wallet.get_address(), 3
        )
        parallel_input = parallel_engine.issue_test_funds(
            wallet.get_address(), 3
        )
        if sequential_input != parallel_input:
            raise AssertionError("Fresh ledgers have different input IDs")
        if sequential_input != input_id:
            raise AssertionError("Funded input does not match signed workload")
        funded_inputs.add(input_id)

    if sequential_engine.utxos != parallel_engine.utxos:
        raise AssertionError("Fresh ledger states are not equivalent")
    return sequential_engine, parallel_engine


def _validate_ledger(engine, initial_supply, attempted, successful,
                     conflicting, rejected):
    """Assert conservation, unique spent inputs, fees, and history consistency."""
    history = engine.get_transaction_history()
    if len(history) != successful:
        raise AssertionError("History length does not match successful count")

    all_inputs = [
        input_id for record in history for input_id in record["input_ids"]
    ]
    if len(all_inputs) != len(set(all_inputs)):
        raise AssertionError("An input was spent by more than one transaction")
    if set(all_inputs) != engine.spent_utxos:
        raise AssertionError("Spent-input set does not match transaction history")
    if sum(record["fee"] for record in history) != engine.total_fees:
        raise AssertionError("Recorded fees do not match accumulated fees")

    for record in history:
        input_value = sum(
            engine.utxos[input_id].amount for input_id in record["input_ids"]
        )
        output_value = sum(output.amount for output in record["outputs"])
        if input_value != output_value + record["fee"]:
            raise AssertionError("Transaction does not conserve input value")
        if output_value != record["amount"] + record["change"]:
            raise AssertionError("Transaction outputs do not match amount and change")

    unspent_value = sum(
        output.amount
        for output_id, output in engine.utxos.items()
        if output_id not in engine.spent_utxos
    )
    if initial_supply != unspent_value + engine.total_fees:
        raise AssertionError("Ledger supply is not conserved")
    if engine.next_transaction_id != successful + 1:
        raise AssertionError("Transaction sequence does not match successful count")
    if successful + conflicting + rejected != attempted:
        raise AssertionError("Transaction outcome counts do not equal attempts")
    return history


def _run_once(
    wallets, transactions, initial_supply, workers, conflict_participants,
):
    """Execute one pair of paths on a fresh equivalent ledger pair."""
    sequential_engine, parallel_engine = _fresh_ledger_pair(
        wallets, transactions
    )

    sequential_latencies_ns = []
    sequential_successes = 0
    sequential_conflicts = 0
    sequential_rejections = 0
    sequential_outcomes = []
    def execute_sequentially():
        nonlocal sequential_successes, sequential_conflicts, sequential_rejections
        for transaction in transactions:
            call_start = time.perf_counter_ns()
            try:
                sequential_engine.transfer_signed(
                    sender=transaction.sender,
                    recipient=transaction.recipient,
                    amount=transaction.amount,
                    fee=transaction.fee,
                    input_ids=list(transaction.input_ids),
                    signature=transaction.signature,
                )
                sequential_outcomes.append("SUCCESS")
                sequential_successes += 1
            except ValueError as error:
                if "already spent" in str(error).lower():
                    sequential_outcomes.append("CONFLICT_DOUBLE_SPEND")
                    sequential_conflicts += 1
                else:
                    sequential_outcomes.append("REJECTED")
                    sequential_rejections += 1
            sequential_latencies_ns.append(time.perf_counter_ns() - call_start)

    def run_sequential():
        execute_sequentially()
        return list(sequential_outcomes)

    (
        _, sequential_elapsed_ns, sequential_cpu_ns, sequential_peak_bytes,
        sequential_system_cpu_percent,
    ) = _measure_execution(run_sequential)

    parallel_completion_timestamps = {}
    completion_recording_overhead_ns = {}
    batch_submission_start_ns = []

    def run_parallel():
        batch_submission_start_ns.append(time.perf_counter_ns())
        return BatchTransactionProcessor(parallel_engine).process_batch(
            transactions,
            workers=workers,
            completion_timestamps_ns=parallel_completion_timestamps,
            completion_recording_overhead_ns=completion_recording_overhead_ns,
        )

    (
        parallel_results,
        parallel_elapsed_ns,
        parallel_cpu_ns,
        parallel_peak_bytes,
        parallel_system_cpu_percent,
    ) = _measure_execution(run_parallel)

    attempted = len(transactions)
    logical_cpu_count = os.cpu_count()
    sequential_counts = {
        "attempted": attempted,
        "successful": sequential_successes,
        "conflict_participants": conflict_participants,
        "conflicting": sequential_conflicts,
        "rejected": sequential_rejections,
    }
    parallel_outcomes = [result.status for result in parallel_results]
    if len(parallel_completion_timestamps) != attempted:
        raise AssertionError("Parallel completion timestamps do not cover every attempt")
    if len(batch_submission_start_ns) != 1:
        raise AssertionError("Parallel batch start timestamp was not captured exactly once")
    parallel_start_ns = batch_submission_start_ns[0]
    parallel_latency_samples_ns = []
    for index, result in enumerate(parallel_results):
        recorded_status, completed_at_ns = parallel_completion_timestamps[index]
        if recorded_status != result.status:
            raise AssertionError("Recorded parallel outcome differs from batch result")
        latency_ns = completed_at_ns - parallel_start_ns
        if latency_ns < 0:
            raise AssertionError("Parallel completion precedes batch submission")
        parallel_latency_samples_ns.append(latency_ns)
    parallel_counts = {
        "attempted": attempted,
        "successful": sum(result.status == "SUCCESS" for result in parallel_results),
        "conflict_participants": conflict_participants,
        "conflicting": sum(
            result.status == "CONFLICT_DOUBLE_SPEND" for result in parallel_results
        ),
        "rejected": sum(result.status == "REJECTED" for result in parallel_results),
    }
    if len(parallel_results) != attempted:
        raise AssertionError("Batch result count does not match attempted count")

    sequential_history = _validate_ledger(
        sequential_engine,
        initial_supply,
        attempted,
        sequential_counts["successful"],
        sequential_counts["conflicting"],
        sequential_counts["rejected"],
    )
    parallel_history = _validate_ledger(
        parallel_engine,
        initial_supply,
        attempted,
        parallel_counts["successful"],
        parallel_counts["conflicting"],
        parallel_counts["rejected"],
    )
    outcomes_equivalent = (
        sequential_outcomes == parallel_outcomes
        and
        sequential_history == parallel_history
        and sequential_engine.utxos == parallel_engine.utxos
        and sequential_engine.spent_utxos == parallel_engine.spent_utxos
        and sequential_engine.total_fees == parallel_engine.total_fees
        and sequential_engine.next_transaction_id == parallel_engine.next_transaction_id
    )
    if not outcomes_equivalent:
        raise AssertionError("Sequential and parallel ledger outcomes differ")

    return {
        "outcomes_equivalent": outcomes_equivalent,
        "sequential": {
            **sequential_counts,
            "elapsed_seconds": sequential_elapsed_ns / 1_000_000_000,
            "process_cpu_seconds": sequential_cpu_ns / 1_000_000_000,
            "whole_system_cpu_utilization_percent": sequential_system_cpu_percent,
            "process_cpu_capacity_percent": _process_cpu_capacity_percent(
                sequential_cpu_ns, sequential_elapsed_ns, logical_cpu_count
            ),
            "peak_traced_memory_bytes": sequential_peak_bytes,
            "throughput_attempted_per_second": (
                attempted * 1_000_000_000 / sequential_elapsed_ns
            ),
            "throughput_successful_per_second": (
                sequential_counts["successful"] * 1_000_000_000
                / sequential_elapsed_ns
            ),
            "per_transaction_latency": summarize_latencies_ms(sequential_latencies_ns),
        },
        "parallel": {
            **parallel_counts,
            "batch_latency_seconds": parallel_elapsed_ns / 1_000_000_000,
            "process_cpu_seconds": parallel_cpu_ns / 1_000_000_000,
            "whole_system_cpu_utilization_percent": parallel_system_cpu_percent,
            "process_cpu_capacity_percent": _process_cpu_capacity_percent(
                parallel_cpu_ns, parallel_elapsed_ns, logical_cpu_count
            ),
            "peak_traced_memory_bytes": parallel_peak_bytes,
            "throughput_attempted_per_second": (
                attempted * 1_000_000_000 / parallel_elapsed_ns
            ),
            "throughput_successful_per_second": (
                parallel_counts["successful"] * 1_000_000_000
                / parallel_elapsed_ns
            ),
            "amortized_ms_per_attempted_transaction": parallel_elapsed_ns / attempted / 1_000_000,
            "batch_submission_to_final_outcome_latency": summarize_latencies_ms(
                parallel_latency_samples_ns
            ),
            "completion_timestamp_recording_overhead_mean_ns": (
                statistics.fmean(completion_recording_overhead_ns.values())
            ),
            "completion_timestamp_recording_overhead_total_ns": sum(
                completion_recording_overhead_ns.values()
            ),
        },
    }


def aggregate_runs(measured_runs):
    """Calculate mean and sample standard deviation for timing/resources/rates."""
    if len(measured_runs) < 2:
        raise ValueError("At least two measured runs are required for deviation")

    summaries = {}
    for path, elapsed_key in (
        ("sequential", "elapsed_seconds"),
        ("parallel", "batch_latency_seconds"),
    ):
        summaries[path] = {}
        metrics = [
            elapsed_key,
            "process_cpu_seconds",
            "process_cpu_capacity_percent",
            "whole_system_cpu_utilization_percent",
            "peak_traced_memory_bytes",
            "throughput_attempted_per_second",
            "throughput_successful_per_second",
        ]
        if path == "parallel":
            metrics.extend((
                "completion_timestamp_recording_overhead_mean_ns",
                "completion_timestamp_recording_overhead_total_ns",
            ))
        for metric in metrics:
            values = [run[path].get(metric) for run in measured_runs]
            if any(value is None for value in values):
                summaries[path][metric] = {
                    "mean": None,
                    "sample_standard_deviation": None,
                }
                continue
            summaries[path][metric] = {
                "mean": statistics.fmean(values),
                "sample_standard_deviation": statistics.stdev(values),
            }
    if all(
        "batch_submission_to_final_outcome_latency" in run["parallel"]
        for run in measured_runs
    ):
        latency_fields = ("mean_ms", "p50_ms", "p95_ms", "p99_ms")
        summaries["parallel_batch_submission_to_final_outcome_latency"] = {
            field: {
                "mean": statistics.fmean(
                    run["parallel"]["batch_submission_to_final_outcome_latency"][field]
                    for run in measured_runs
                ),
                "sample_standard_deviation": statistics.stdev(
                    run["parallel"]["batch_submission_to_final_outcome_latency"][field]
                    for run in measured_runs
                ),
            }
            for field in latency_fields
        }
    return summaries


def run_comparison(
    transaction_count=100, workers=4, contention_percent=0,
    collision_pattern="pairwise",
):
    """Warm up once, then perform three paired measured comparisons."""
    if type(workers) is not int or workers not in SUPPORTED_WORKER_COUNTS:
        raise ValueError("workers must be one of 1, 2, 4, or 8")

    workload = _prepare_workload(
        transaction_count, contention_percent, collision_pattern
    )
    return _run_comparison(*workload, workers)


def _run_comparison(
    wallets, transactions, initial_supply, contention_percent,
    conflict_participants, conflict_group_count, collision_pattern, workers,
):
    """Run warm-up and measured comparisons for an existing signed workload."""
    warmup = _run_once(
        wallets, transactions, initial_supply, workers, conflict_participants,
    )
    if not warmup["outcomes_equivalent"]:
        raise AssertionError("Warm-up ledgers did not produce equivalent outcomes")

    measured_runs = []
    for _ in range(3):
        run = _run_once(
            wallets, transactions, initial_supply, workers, conflict_participants,
        )
        if not run["outcomes_equivalent"]:
            raise AssertionError("Measured ledgers did not produce equivalent outcomes")
        measured_runs.append(run)

    summary = aggregate_runs(measured_runs)
    count_keys = (
        "attempted", "conflict_participants", "successful", "conflicting", "rejected"
    )
    expected_counts = {
        key: measured_runs[0]["sequential"][key] for key in count_keys
    }
    for run in measured_runs:
        if any(run[path][key] != expected_counts[key]
               for path in ("sequential", "parallel") for key in count_keys):
            raise AssertionError("Measured transaction outcome counts are inconsistent")
    summary["counts"] = expected_counts
    return {
        "transaction_count": len(transactions),
        "workers": workers,
        "contention_percent": contention_percent,
        "conflict_group_count": conflict_group_count,
        "collision_pattern": collision_pattern,
        "conflict_participants": conflict_participants,
        "initial_supply": initial_supply,
        "warmup_outcomes_equivalent": warmup["outcomes_equivalent"],
        "measured_runs": measured_runs,
        "summary": summary,
    }


def run_matrix(
    transaction_counts=(100,), worker_counts=(4,), contention_profiles=(0,),
    collision_patterns=("pairwise",),
):
    """Run selected transaction-size, worker-count, and contention settings."""
    if not transaction_counts:
        raise ValueError("At least one transaction count is required")
    if not worker_counts:
        raise ValueError("At least one worker count is required")
    if not contention_profiles:
        raise ValueError("At least one contention profile is required")
    if not collision_patterns:
        raise ValueError("At least one collision pattern is required")
    if len(set(transaction_counts)) != len(transaction_counts):
        raise ValueError("Transaction counts must not contain duplicates")
    if len(set(worker_counts)) != len(worker_counts):
        raise ValueError("Worker counts must not contain duplicates")
    if len(set(contention_profiles)) != len(contention_profiles):
        raise ValueError("Contention profiles must not contain duplicates")
    if len(set(collision_patterns)) != len(collision_patterns):
        raise ValueError("Collision patterns must not contain duplicates")
    if any(
        type(count) is not int or count not in SUPPORTED_TRANSACTION_COUNTS
        for count in transaction_counts
    ):
        raise ValueError("transaction counts must be 100, 1000, or 10000")
    if any(
        type(workers) is not int or workers not in SUPPORTED_WORKER_COUNTS
        for workers in worker_counts
    ):
        raise ValueError("workers must be one of 1, 2, 4, or 8")
    if any(
        type(profile) is not int or profile not in SUPPORTED_CONTENTION_PROFILES
        for profile in contention_profiles
    ):
        raise ValueError("contention profiles must be 0, 20, or 50")
    if any(pattern not in SUPPORTED_COLLISION_PATTERNS for pattern in collision_patterns):
        raise ValueError("collision patterns must be pairwise or hotspot")

    workloads = {
        (count, profile, pattern): _prepare_workload(count, profile, pattern)
        for count in transaction_counts
        for profile in contention_profiles
        for pattern in collision_patterns
    }
    configurations = []
    for count in transaction_counts:
        for profile in contention_profiles:
            for pattern in collision_patterns:
                workload = workloads[(count, profile, pattern)]
                for workers in worker_counts:
                    comparison = _run_comparison(*workload, workers)
                    configurations.append({
                        "transaction_count": count,
                        "workers": workers,
                        "contention_percent": profile,
                        "collision_pattern": pattern,
                        "comparison": comparison,
                    })
    return configurations


def build_report(configuration, generated_at=None):
    """Build a JSON-serializable report for one completed configuration."""
    comparison = configuration["comparison"]
    generated_at = generated_at or datetime.now(timezone.utc)
    return {
        "metadata": {
            "generated_at_utc": generated_at.astimezone(timezone.utc).isoformat(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
            "benchmark": "signed sequential versus parallel batch comparison",
        },
        "configuration": {
            "transaction_count": configuration["transaction_count"],
            "workers": configuration["workers"],
            "contention_percent": configuration["contention_percent"],
            "collision_pattern": configuration.get(
                "collision_pattern", comparison.get("collision_pattern", "pairwise")
            ),
            "contention_definition": _contention_definition(
                configuration.get(
                    "collision_pattern", comparison.get("collision_pattern", "pairwise")
                )
            ),
            "conflict_group_count": comparison["conflict_group_count"],
            "conflict_participants": comparison["conflict_participants"],
            "initial_supply": comparison["initial_supply"],
            "signed_transactions": True,
            "warmup_run_count": 1,
            "measured_run_count": len(comparison["measured_runs"]),
        },
        "measurement": {
            "wall_clock": "time.perf_counter_ns elapsed seconds",
            "process_cpu": (
                "time.process_time_ns elapsed process CPU seconds"
            ),
            "whole_system_cpu_utilization": (
                "Windows GetSystemTimes counter delta: (kernel + user - idle) / "
                "(kernel + user) * 100; None on unsupported platforms or failed/invalid reads"
            ),
            "process_cpu_capacity_percent": (
                "process CPU seconds / (wall seconds * logical CPU count) * 100; "
                "average process share of logical processor capacity, not "
                "whole-system CPU utilization; may be unavailable"
            ),
            "peak_traced_python_memory": (
                "tracemalloc peak bytes above the per-execution starting "
                "allocation baseline"
            ),
            "timing_boundary": (
                "Workload generation, wallet creation, signing, funding, "
                "integrity checks, outcome comparison, and report writing "
                "are excluded. Sequential timing covers transfer_signed calls; "
                "parallel timing covers process_batch including executor setup, "
                "validation, commits, and shutdown."
            ),
            "instrumentation": (
                "tracemalloc runs during both timed execution paths; its "
                "instrumentation overhead is included consistently."
            ),
            "sequential_latency": (
                "Per-transfer latency samples are reported for sequential "
                "execution. Parallel percentiles use batch-submission-to-final-"
                "outcome timestamps recorded at final result creation."
            ),
            "parallel_latency_definition": (
                "Parallel latency is measured from the timestamp immediately "
                "before process_batch submission to each transaction's final "
                "success, conflict, or rejection result. It includes validation "
                "queue waiting time."
            ),
            "completion_timestamp_instrumentation": (
                "Optional completion timestamp and dict-recording cost capture "
                "is enabled for benchmark runs. Its measured estimate includes "
                "the second clock read used for the estimate; the estimate itself "
                "adds a small amount of overhead and is included in timed execution."
            ),
            "whole_system_cpu_limitations": (
                "Other system processes contribute to this system-wide average. "
                "Short execution intervals limit precision; unavailable reads "
                "are reported as null. Counter snapshots bracket each measured run."
            ),
        },
        "speedup": _report_speedup(comparison),
        "warmup_outcomes_equivalent": comparison["warmup_outcomes_equivalent"],
        "measured_runs": comparison["measured_runs"],
        "summary": comparison["summary"],
    }


def _contention_definition(collision_pattern):
    if collision_pattern == "hotspot":
        return (
            "Percentage of attempted transactions in one shared-input group; "
            "exactly one can commit and the remaining participants are conflict losers."
        )
    return (
        "Percentage of attempted transactions in pairwise shared-input groups; "
        "each pair has two participants and one conflict loser."
    )


def _report_speedup(comparison):
    """Report attempted-throughput ratios per run and for mean rates."""
    per_run = [
        safe_speedup_ratio(
            run["sequential"]["throughput_attempted_per_second"],
            run["parallel"]["throughput_attempted_per_second"],
        )
        for run in comparison["measured_runs"]
    ]
    sequential_mean = comparison["summary"]["sequential"][
        "throughput_attempted_per_second"
    ]["mean"]
    parallel_mean = comparison["summary"]["parallel"][
        "throughput_attempted_per_second"
    ]["mean"]
    return {
        "definition": "parallel attempted throughput / sequential attempted throughput",
        "per_measured_run": per_run,
        "ratio_of_mean_attempted_throughput": safe_speedup_ratio(
            sequential_mean, parallel_mean
        ),
    }


def render_markdown_report(report):
    """Render a human-readable report containing every measured run."""
    metadata = report["metadata"]
    config = report["configuration"]
    lines = [
        "# CBDC Privacy System Benchmark Report",
        "",
        f"- Generated (UTC): {metadata['generated_at_utc']}",
        f"- Python: {metadata['python_version']}",
        f"- Platform: {metadata['platform']}",
        f"- Transactions: {config['transaction_count']}",
        f"- Parallel workers: {config['workers']}",
        f"- Collision pattern: {config['collision_pattern']}",
        f"- Contention: {config['contention_percent']}%",
        f"- Contention definition: {config['contention_definition']}",
        f"- Conflict groups: {config['conflict_group_count']}",
        f"- Conflict participants: {config['conflict_participants']}",
        f"- Initial supply: {config['initial_supply']}",
        f"- Signed transactions: {config['signed_transactions']}",
        f"- Warm-up runs: {config['warmup_run_count']}",
        f"- Measured runs: {config['measured_run_count']}",
        f"- Warm-up outcomes equivalent: {report['warmup_outcomes_equivalent']}",
        "",
        "## Measurement boundaries",
        "",
        f"- Wall clock: {report['measurement']['wall_clock']}.",
        f"- Process CPU: {report['measurement']['process_cpu']}.",
        f"- Whole-system CPU utilization: {report['measurement']['whole_system_cpu_utilization']}.",
        f"- Process CPU capacity share: {report['measurement']['process_cpu_capacity_percent']}.",
        f"- Peak traced memory: {report['measurement']['peak_traced_python_memory']}.",
        f"- Timing: {report['measurement']['timing_boundary']}",
        f"- Instrumentation: {report['measurement']['instrumentation']}",
        f"- Latency: {report['measurement']['sequential_latency']}",
        f"- Parallel latency: {report['measurement']['parallel_latency_definition']}",
        f"- Completion timestamp instrumentation: {report['measurement']['completion_timestamp_instrumentation']}",
        f"- Whole-system CPU limitations: {report['measurement']['whole_system_cpu_limitations']}",
        "",
        "## Attempted-throughput speedup",
        "",
        f"- Definition: {report['speedup']['definition']}.",
        f"- Ratio of mean throughput: {report['speedup']['ratio_of_mean_attempted_throughput']}",
        f"- Per measured run: {report['speedup']['per_measured_run']}",
        "",
        "## Measured runs",
        "",
        "| Run | Path | Equivalent | Attempted | Successful | Participants | Conflicts | Rejected | Wall/batch (s) | Process CPU (s) | Whole-system CPU (%) | Peak traced bytes | Attempted tx/s |",
        "|---:|---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run_index, run in enumerate(report["measured_runs"], start=1):
        for path, elapsed_key in (
            ("sequential", "elapsed_seconds"),
            ("parallel", "batch_latency_seconds"),
        ):
            metrics = run[path]
            lines.append(
                f"| {run_index} | {path} | {run['outcomes_equivalent']} | "
                f"{metrics['attempted']} | {metrics['successful']} | "
                f"{metrics['conflict_participants']} | {metrics['conflicting']} | "
                f"{metrics['rejected']} | {metrics[elapsed_key]:.9f} | "
                f"{metrics['process_cpu_seconds']:.9f} | "
                f"{metrics['whole_system_cpu_utilization_percent'] if metrics['whole_system_cpu_utilization_percent'] is not None else 'n/a'} | "
                f"{metrics['peak_traced_memory_bytes']} | "
                f"{metrics['throughput_attempted_per_second']:.6f} |"
            )
    lines.extend(["", "## Summary (mean and sample standard deviation)", ""])
    for path in ("sequential", "parallel"):
        lines.extend([f"### {path.title()}", ""])
        for metric, values in report["summary"][path].items():
            if metric == "batch_submission_to_final_outcome_latency":
                continue
            if values["mean"] is None or values["sample_standard_deviation"] is None:
                lines.append(f"- {metric}: mean n/a; sample standard deviation n/a")
                continue
            lines.append(
                f"- {metric}: mean {values['mean']:.9f}; sample standard "
                f"deviation {values['sample_standard_deviation']:.9f}"
            )
        lines.append("")
    lines.extend([
        "## Parallel batch-submission-to-final-outcome latency (ms)", "",
        "Includes time waiting in the validation queue. Percentiles are computed "
        "from recorded per-transaction completion timestamps.", "",
    ])
    for run_index, run in enumerate(report["measured_runs"], start=1):
        latency = run["parallel"]["batch_submission_to_final_outcome_latency"]
        lines.append(
            f"- Run {run_index}: "
            + ", ".join(f"{key}={value:.9f}" for key, value in latency.items())
        )
    lines.append("- Across measured runs:")
    for metric, values in report["summary"][
        "parallel_batch_submission_to_final_outcome_latency"
    ].items():
        lines.append(
            f"  - {metric}: mean {values['mean']:.9f}; sample standard "
            f"deviation {values['sample_standard_deviation']:.9f}"
        )
    lines.append("")
    lines.extend(["## Sequential per-transaction latency (ms)", ""])
    for run_index, run in enumerate(report["measured_runs"], start=1):
        latency = run["sequential"]["per_transaction_latency"]
        lines.append(
            f"- Run {run_index}: "
            + ", ".join(f"{key}={value:.9f}" for key, value in latency.items())
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report, output_dir):
    """Write JSON and Markdown reports to unique paths, creating the directory."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = report["configuration"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stem = (
        f"compare_{timestamp}_n{config['transaction_count']}"
        f"_w{config['workers']}_c{config['contention_percent']}"
        f"_{config.get('collision_pattern', 'pairwise')}"
    )
    candidate = stem
    suffix = 1
    while (output_dir / f"{candidate}.json").exists() or (
        output_dir / f"{candidate}.md"
    ).exists():
        candidate = f"{stem}_{suffix}"
        suffix += 1

    json_path = output_dir / f"{candidate}.json"
    markdown_path = output_dir / f"{candidate}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count",
        type=int,
        nargs="+",
        choices=SUPPORTED_TRANSACTION_COUNTS,
        default=[100],
        help="one or more transaction counts (100, 1000, 10000)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        nargs="+",
        choices=SUPPORTED_WORKER_COUNTS,
        default=[4],
        help="one or more parallel worker counts (1, 2, 4, 8)",
    )
    parser.add_argument(
        "--contention",
        type=int,
        nargs="+",
        choices=SUPPORTED_CONTENTION_PROFILES,
        default=[0],
        help="one or more participant contention profiles (0, 20, 50)",
    )
    parser.add_argument(
        "--collision-pattern",
        choices=SUPPORTED_COLLISION_PATTERNS,
        nargs="+",
        default=["pairwise"],
        help="input collision shape: pairwise (preserved default) or hotspot",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "results",
        help="directory for unique JSON and Markdown reports",
    )
    args = parser.parse_args()
    print("Timing excludes wallet creation, funding, workload generation, and signing.")
    print("Parallel timing includes process_batch and worker-pool setup/shutdown.")
    print("Sequential timing includes each transfer_signed call.")
    print("Process CPU is process CPU time in seconds.")
    print(
        "Whole-system CPU utilization uses Windows GetSystemTimes; other "
        "processes contribute and unavailable reads are shown as n/a."
    )
    print(
        "Peak traced memory is additional Python allocation peak in bytes; "
        "tracemalloc runs during both timed paths and adds instrumentation overhead."
    )
    print("Ledger preparation, integrity checks, and outcome comparison are untimed.")
    for configuration in run_matrix(
        args.count, args.workers, args.contention, args.collision_pattern
    ):
        result = configuration["comparison"]
        report = build_report(configuration)
        json_path, markdown_path = write_report(report, args.output_dir)
        print(f"Saved JSON report: {json_path}")
        print(f"Saved Markdown report: {markdown_path}")
        print(
            f"\nTransactions: {configuration['transaction_count']}; "
            f"parallel workers: {configuration['workers']}; "
            f"contention: {configuration['contention_percent']}%"
            f"; pattern: {configuration['collision_pattern']}"
        )
        if configuration["transaction_count"] > MAX_DISTINCT_WALLETS:
            print(
                "Workload note: uses up to 1,000 distinct senders; "
                "only designated conflict-pair members share inputs."
            )
        print(
            "Contention definition: "
            f"{report['configuration']['contention_definition']}"
        )
        print(
            "Warm-up ledger outcomes equivalent: "
            f"{result['warmup_outcomes_equivalent']}"
        )
        print()
        print(
            "| Run | Path | Outcomes equivalent | Attempted | Successful | "
            "Conflict participants | Conflicting losers | Rejected | "
            "Elapsed / batch (s) | Process CPU (s) | Whole-system CPU (%) | Peak traced memory (bytes) | "
            "Throughput attempted (tx/s) |"
        )
        print("|---:|---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for run_index, run in enumerate(result["measured_runs"], start=1):
            for name, elapsed_key in (
                ("sequential", "elapsed_seconds"),
                ("parallel", "batch_latency_seconds"),
            ):
                metrics = run[name]
                print(
                    f"| {run_index} | {name} | {run['outcomes_equivalent']} | "
                    f"{metrics['attempted']} | {metrics['successful']} | "
                    f"{metrics['conflict_participants']} | "
                    f"{metrics['conflicting']} | {metrics['rejected']} | "
                    f"{metrics[elapsed_key]:.6f} | "
                    f"{metrics['process_cpu_seconds']:.6f} | "
                    f"{metrics['whole_system_cpu_utilization_percent'] if metrics['whole_system_cpu_utilization_percent'] is not None else 'n/a'} | "
                    f"{metrics['peak_traced_memory_bytes']} | "
                    f"{metrics['throughput_attempted_per_second']:.2f} |"
                )

        print("\nMeasured-run summary (mean +/- sample standard deviation):")
        print(
            "  Counts per run: "
            + ", ".join(
                f"{key}={value}"
                for key, value in result["summary"]["counts"].items()
            )
        )
        for name, elapsed_key in (
            ("sequential", "elapsed_seconds"),
            ("parallel", "batch_latency_seconds"),
        ):
            summary = result["summary"][name]
            for metric in (
                elapsed_key,
                "process_cpu_seconds",
                "process_cpu_capacity_percent",
                "whole_system_cpu_utilization_percent",
                "peak_traced_memory_bytes",
                "throughput_attempted_per_second",
                "throughput_successful_per_second",
            ):
                values = summary[metric]
                if name == "parallel" and metric not in values:
                    continue
                mean = values["mean"]
                deviation = values["sample_standard_deviation"]
                print(
                    f"  {name} {metric}: "
                    + ("n/a" if mean is None else f"{mean:.6f} +/- {deviation:.6f}")
                )
        latency_summary = result["summary"][
            "parallel_batch_submission_to_final_outcome_latency"
        ]
        print("\nParallel batch-submission-to-final-outcome latency (ms):")
        for run_index, run in enumerate(result["measured_runs"], start=1):
            values = run["parallel"]["batch_submission_to_final_outcome_latency"]
            print(
                f"  Run {run_index}: "
                + ", ".join(f"{key}={value:.6f}" for key, value in values.items())
            )
        print("  Measured-run latency percentile summary:")
        for metric, values in latency_summary.items():
            print(
                f"    {metric}: {values['mean']:.6f} +/- "
                f"{values['sample_standard_deviation']:.6f}"
            )
        print(
            "  Timestamp-recording overhead mean per run (ns): "
            + ", ".join(
                f"{run['parallel']['completion_timestamp_recording_overhead_mean_ns']:.2f}"
                for run in result["measured_runs"]
            )
        )

        print("\nSequential per-transaction latency by measured run (ms):")
        for run_index, run in enumerate(result["measured_runs"], start=1):
            print(f"  Run {run_index}:")
            for key, value in run["sequential"]["per_transaction_latency"].items():
                print(f"    {key}: {value:.6f}")
        print(report["measurement"]["parallel_latency_definition"])
        print(
            "\nAttempted-throughput speedup (parallel / sequential, ratio of means): "
            f"{report['speedup']['ratio_of_mean_attempted_throughput']}"
        )


if __name__ == "__main__":
    main()
