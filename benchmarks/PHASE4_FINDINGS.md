# Phase 4 Benchmark Findings

**Current authoritative matrix:** 36 pairwise JSON reports matching `benchmarks/results/compare_20261011T171052*_pairwise.json`, generated October 11, 2026 (filename timestamps range from `20261011T171052602738Z` through `20261011T171052840854Z`). Each has a matching Markdown report. Older timestamped reports, including the `20261011T165800…` matrix, remain in `benchmarks/results/` as historical runs and are not mixed into these results. Hotspot smoke reports are excluded.

**Environment:** Python 3.13.5, Windows 11 (`Windows-11-10.0.26300-SP0`), 12 logical processors reported by Python.

## Matrix and validation

The matrix crosses 100, 1,000, and 10,000 transactions; 1, 2, 4, and 8 workers; and 0%, 20%, and 50% pairwise input contention. Each of the 36 configurations has one warm-up and three measured comparisons. I independently read the run-level measurements from all 36 JSON reports and recomputed the aggregates below. All **108 measured comparisons** reported equivalent sequential and parallel outcomes, and all attempted counts reconcile to successes, conflicts, and rejections. Every report includes the parallel p50/p95/p99 and whole-system CPU values.

The benchmark's ledger checks execute before a report is written. They validate supply conservation, unique spent inputs, fee/history consistency, transaction sequence, and outcome counts. Pairwise final ledgers are also compared for UTXO state, spent inputs, history, fees, and transaction IDs. No saved run reported an outcome mismatch or unavailable whole-system CPU measurement.

## Methodology and aggregation

Sequential execution calls `UTXOEngine.transfer_signed` in order. Parallel execution calls `BatchTransactionProcessor.process_batch`. The same ordered signed transaction payloads and equivalent fresh ledgers are used for each paired comparison. Wallet creation, transaction generation and signing, ledger funding, integrity checks, outcome comparison, and report writing are outside execution timing. Sequential timing includes per-transfer timing/bookkeeping. Parallel timing includes `process_batch`, including worker-pool setup/shutdown, dispatch, parallel validation, and synchronized commits. `tracemalloc` runs during both paths. Optional parallel completion timestamps provide batch-submission-to-final-outcome latency and add instrumentation overhead; the benchmark records an estimate of timestamp-recording cost.

Aggregate attempted throughput is total attempts divided by total measured wall time across all 108 runs per path. Aggregate successful throughput uses the same elapsed time and counts only committed transactions.

For each configuration, I independently recomputed each measured run's attempted rate as attempts / elapsed seconds, averaged the three sequential run rates and the three parallel run rates separately, then divided mean parallel rate by mean sequential rate. This matches the JSON `ratio_of_mean_attempted_throughput` definition. Mean and median in the speedup distribution are across these 36 configuration ratios. The effective-tie band is ±1% around 1.0. The matrix-wide aggregate ratio is a different aggregation: aggregate parallel attempted rate divided by aggregate sequential attempted rate.

For grouped latency, I averaged each run's p50/p95/p99, then equally averaged those run-level percentiles across configurations in the group. These are means of saved percentiles, not percentiles recomputed over pooled transactions. Whole-system CPU uses Windows `GetSystemTimes`; process CPU time is separately reported. Peak memory is traced Python allocation above the per-execution baseline, not resident memory.

## Aggregate throughput

Each path attempted 399,600 transactions over its measured runs: 352,980 succeeded, 46,620 conflicted, and zero were rejected.

| Path | Total measured wall time | Attempted throughput | Successful throughput |
|---|---:|---:|---:|
| Sequential | 74.193 s | 5,385.95 tx/s | 4,757.59 tx/s |
| Parallel | 95.615 s | 4,179.26 tx/s | 3,691.68 tx/s |

**Observation:** Parallel execution did not improve aggregate throughput in this matrix. The aggregate parallel/sequential attempted-throughput ratio was 0.776x. This is a result for these workloads and this implementation, not a claim that parallel processing is universally slower.

## Speedup distribution by configuration

Mean configuration speedup was **0.828x** and median was **0.818x**. With the ±1% effective-tie definition, parallel was faster in **0**, slower in **36**, and tied in **0** configurations. The smallest ratio was 0.707x and the largest was 0.981x.

| Transactions | Workers | 0% contention | 20% contention | 50% contention |
|---:|---:|---:|---:|---:|
| 100 | 1 | 0.801x | 0.783x | 0.832x |
| 100 | 2 | 0.872x | 0.824x | 0.826x |
| 100 | 4 | 0.879x | 0.889x | 0.896x |
| 100 | 8 | 0.857x | 0.842x | 0.728x |
| 1,000 | 1 | 0.924x | 0.806x | 0.807x |
| 1,000 | 2 | 0.853x | 0.885x | 0.895x |
| 1,000 | 4 | 0.808x | 0.927x | 0.981x |
| 1,000 | 8 | 0.776x | 0.961x | 0.937x |
| 10,000 | 1 | 0.761x | 0.782x | 0.809x |
| 10,000 | 2 | 0.812x | 0.759x | 0.771x |
| 10,000 | 4 | 0.835x | 0.720x | 0.724x |
| 10,000 | 8 | 0.813x | 0.727x | 0.707x |

## Parallel batch-submission-to-final-outcome latency

Values are the mean of the three run-level percentiles across each group, in milliseconds.

| Grouped by transaction count | p50 | p95 | p99 |
|---:|---:|---:|---:|
| 100 | 17.311 | 19.670 | 19.877 |
| 1,000 | 175.216 | 203.034 | 205.649 |
| 10,000 | 2,051.193 | 2,371.587 | 2,399.456 |

| Grouped by workers | p50 | p95 | p99 |
|---:|---:|---:|---:|
| 1 | 734.512 | 849.207 | 858.929 |
| 2 | 730.534 | 847.568 | 859.055 |
| 4 | 731.880 | 845.634 | 854.910 |
| 8 | 794.702 | 916.645 | 927.082 |

| Grouped by contention participants | p50 | p95 | p99 |
|---:|---:|---:|---:|
| 0% | 724.245 | 841.583 | 851.882 |
| 20% | 778.840 | 896.609 | 906.188 |
| 50% | 740.636 | 856.098 | 866.911 |

These latency summaries include queue waiting and commit delay. Contention changes the mix of successful and conflicting outcomes, so grouped latency changes should not be interpreted as throughput improvements.

## Worker-count comparisons

For each worker change, I paired parallel mean attempted throughput at the two worker settings for the same nine transaction-count/contention combinations. The ratio is new worker rate / old worker rate. “Improved” and “worse” use ±1%; “tied” is within that band.

| Worker change | Mean paired rate ratio | Improved | Worse | Tied |
|---|---:|---:|---:|---:|
| 1 → 2 | 1.033x | 6 | 3 | 0 |
| 2 → 4 | 1.037x | 6 | 2 | 1 |
| 4 → 8 | 0.949x | 1 | 8 | 0 |
| 1 → 4 | 1.071x | 7 | 2 | 0 |
| 1 → 8 | 1.015x | 4 | 5 | 0 |

Four workers generally improved on two in these paired comparisons, while moving from four to eight reduced throughput in eight of nine. The one-to-eight mean ratio is close to parity and mixed across configurations; scaling is not monotonic.

## Contention and outcome counts

The contention percentage is the share of attempted transactions participating in pairwise shared-input groups. Every pair has two participants, one successful spender, and one conflict loser. Thus 20% participant contention produces 10% losing attempts; 50% produces 25% losing attempts.

| Contention | Attempts per path | Successes | Conflict losers | Rejected |
|---:|---:|---:|---:|---:|
| 0% | 133,200 | 133,200 | 0 | 0 |
| 20% | 133,200 | 119,880 | 13,320 | 0 |
| 50% | 133,200 | 99,900 | 33,300 | 0 |

Pooled throughput by contention profile:

| Contention | Sequential attempted tx/s | Parallel attempted tx/s | Sequential successful tx/s | Parallel successful tx/s |
|---:|---:|---:|---:|---:|
| 0% | 5,307.71 | 4,289.92 | 5,307.71 | 4,289.92 |
| 20% | 5,321.43 | 4,037.50 | 4,789.28 | 3,633.75 |
| 50% | 5,534.65 | 4,218.56 | 4,150.99 | 3,163.92 |

Attempted rates include conflict losers. As designed, successful share falls from 100% to 90% to 75%; therefore successful throughput does not track attempted throughput as contention changes.

## CPU and peak traced Python memory

Means across configurations and measured runs within each transaction-count group:

| Transactions | Sequential whole-system CPU | Parallel whole-system CPU | Sequential process CPU time | Parallel process CPU time | Sequential traced peak | Parallel traced peak |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 15.61% | 16.20% | 15.625 ms | 29.514 ms | 0.094 MiB | 0.250 MiB |
| 1,000 | 15.70% | 18.80% | 181.424 ms | 286.458 ms | 0.905 MiB | 2.441 MiB |
| 10,000 | 14.16% | 18.21% | 1,855.035 ms | 3,357.639 ms | 9.582 MiB | 26.119 MiB |

Across all runs, mean whole-system CPU utilization was **15.16% sequential** and **17.74% parallel**. Mean process CPU time was **684.028 ms sequential** and **1,224.537 ms parallel**. Whole-system readings ranged from 5.26% to 46.89% sequential and 4.76% to 60.00% parallel; unrelated Windows processes affect these measurements. Process CPU time is not CPU utilization and showed 15.625 ms granularity in the recorded environment.

## Run-to-run variability

For each configuration/path, throughput coefficient of variation is sample standard deviation of its three run-level throughput rates divided by their mean. Statistics below summarize the 36 configuration CVs separately for each path.

| Path | Mean CV | Median CV | Maximum CV and configuration |
|---|---:|---:|---|
| Sequential | 4.21% | 2.79% | 22.59% — 1,000 transactions, 1 worker, 0% contention |
| Parallel | 4.29% | 2.71% | 20.29% — 100 transactions, 8 workers, 50% contention |

Three measured runs per configuration are a small sample; CV and sample standard deviation are descriptive and do not establish statistical significance or repeatability.

## Limitations and threats to validity

- `tracemalloc` adds timing overhead and covers Python allocations, not native cryptography allocations or total resident memory.
- Completion timestamp instrumentation adds work to the parallel path. Its reported cost is an estimate; the full observer overhead is not subtracted from measured latency.
- Parallel timing includes worker-pool creation/shutdown, queueing, validation, and commit work. These are real costs of this API and make the benchmark more than a signature-verification-only comparison.
- Whole-system CPU utilization includes uncontrolled background processes. Short intervals and Windows counter granularity limit precision; process CPU time is a separate, coarse measurement.
- Only three measured repetitions were collected per configuration. Run order, cache, thermal, and background-load effects are not controlled.
- The benchmark records Python/platform/logical processor count, but not a controlled CPU model or machine workload profile.
- The 10,000-transaction workload is capped at 1,000 distinct sender wallets. It is a synthetic in-memory signed-payment workload, not a large identity-registration benchmark.
- Same-batch chained spends are unsupported. Generated inputs are independently spendable except for the deliberate pairwise conflicts.
- This educational simulator has no networking, persistence, consensus, production issuance, or cryptographic transaction privacy. Results do not establish production CBDC performance.

## Conclusion and Phase 4 status

The newest authoritative pairwise matrix preserved the tested ledger invariants and produced equivalent sequential/parallel outcomes in all 108 measured comparisons. Its aggregate attempted throughput was 5,385.95 tx/s sequential versus 4,179.26 tx/s parallel; aggregate successful throughput was 4,757.59 versus 3,691.68 tx/s. Parallel did not improve throughput in this tested matrix. This does not establish that parallel execution is universally slower, and the limited repetitions and uncontrolled environment preclude broad performance claims.

Phase 4 acceptance criteria remain satisfied. Older matrix reports remain available as historical evidence but are excluded from this current analysis.
