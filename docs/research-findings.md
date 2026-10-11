# Research Findings: Sequential and Parallel UTXO Transaction Processing

**Project:** CBDC Privacy System (educational simulator)
**Evidence date:** October 11, 2026
**Environment:** Python 3.13.5; Windows 11 (`Windows-11-10.0.26300-SP0`); 12 logical processors reported by Python
**Current authoritative evidence:** Exactly the 36 pairwise JSON reports matching `benchmarks/results/compare_20261011T171052*_pairwise.json` (filename timestamp range `20261011T171052602738Z`â€“`20261011T171052840854Z`) and their matching Markdown reports. Older reports, including the `20261011T165800â€¦` matrix, remain available as historical runs and are excluded here. Hotspot smoke reports are excluded. Detailed evidence summary: [`../benchmarks/PHASE4_FINDINGS.md`](../benchmarks/PHASE4_FINDINGS.md).

## Research question and hypothesis

The research question is: **Can safe parallel transaction validation improve throughput compared with sequential validation while preserving UTXO integrity?**

The hypothesis was that non-conflicting signed transactions might benefit from parallel Ed25519 signature verification, while contention, synchronized commits, scheduling, and worker-pool overhead might offset those gains. The hypothesis concerns this simulator and workload; it is not a claim about all parallel transaction systems.

## Methodology

The benchmark compared ordered `UTXOEngine.transfer_signed` calls with `BatchTransactionProcessor.process_batch`. Each paired comparison uses identical ordered signed transaction payloads and equivalent fresh ledgers. The matrix includes:

- 100, 1,000, and 10,000 attempted transactions;
- 1, 2, 4, and 8 parallel workers;
- 0%, 20%, and 50% pairwise input-contention participant shares;
- one warm-up and three measured runs per configuration.

There are 36 unique configurations and 108 measured sequential/parallel comparisons. Wallet creation, signing, workload construction, ledger funding, integrity checks, outcome comparison, and report writing are excluded from timed execution. Sequential timing covers the ordered signed-transfer calls, including their per-transaction latency bookkeeping. Parallel timing covers the full `process_batch` call, including thread-pool startup/shutdown, dispatch, read-only validation, and synchronized commit. `tracemalloc` is active in both paths. Parallel completion timestamps measure batch-submission-to-final-outcome latency, including queue waiting and commit delay; timestamp instrumentation adds overhead, for which the benchmark records an estimate.

For aggregate rates, I summed the run-level attempts and divided by the sum of elapsed execution times. For per-configuration speedup, I recomputed every run's attempted rate from its actual attempt count and wall duration, took the arithmetic mean of the three rates for each path, and divided mean parallel rate by mean sequential rate. This corresponds to the JSON field `ratio_of_mean_attempted_throughput`. The matrix-wide aggregate speedup uses the ratio of aggregate rates, so it is not the same statistic as the arithmetic mean across configuration speedups.

Grouped parallel p50/p95/p99 values are means of each run's saved percentile, averaged equally across configurations in the group. They are not percentiles recomputed over pooled transaction samples. Whole-system CPU utilization is measured from Windows `GetSystemTimes`; process CPU time is reported separately. Peak memory is `tracemalloc` Python allocation above the per-execution starting baseline, not total RSS.

## Results

### Aggregate throughput

Each path attempted **399,600** transactions across all measured executions. Both paths recorded **352,980 successes**, **46,620 conflict losers**, and **zero rejections**.

| Path | Total measured wall time | Attempted throughput | Successful throughput |
|---|---:|---:|---:|
| Sequential | 74.193 s | 5,385.95 tx/s | 4,757.59 tx/s |
| Parallel | 95.615 s | 4,179.26 tx/s | 3,691.68 tx/s |

**Measured result:** Parallel execution did not improve aggregate throughput in the newest tested pairwise matrix. The ratio of aggregate attempted rates was 0.776x.

**Interpretation:** This result does not establish that parallel execution is universally slower. It describes one implementation, synthetic workload family, Windows environment, and timing boundary.

### Per-configuration speedup

Each cell is the ratio of the mean of three run-level parallel attempted-throughput rates to the mean of three sequential rates. The 36 ratios have mean **0.828x** and median **0.818x**. Using the established Â±1% tie band, parallel was faster in **0**, slower in **36**, and tied in **0** configurations. The range was **0.707xâ€“0.981x**.

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

### Parallel transaction-outcome latency

Values are means of run-level batch-submission-to-final-outcome percentiles, equally averaged over configurations in each group. Units are milliseconds.

| Transaction count | p50 | p95 | p99 |
|---:|---:|---:|---:|
| 100 | 17.311 | 19.670 | 19.877 |
| 1,000 | 175.216 | 203.034 | 205.649 |
| 10,000 | 2,051.193 | 2,371.587 | 2,399.456 |

| Worker count | p50 | p95 | p99 |
|---:|---:|---:|---:|
| 1 | 734.512 | 849.207 | 858.929 |
| 2 | 730.534 | 847.568 | 859.055 |
| 4 | 731.880 | 845.634 | 854.910 |
| 8 | 794.702 | 916.645 | 927.082 |

| Contention participants | p50 | p95 | p99 |
|---:|---:|---:|---:|
| 0% | 724.245 | 841.583 | 851.882 |
| 20% | 778.840 | 896.609 | 906.188 |
| 50% | 740.636 | 856.098 | 866.911 |

These measurements include validation queue wait and commit delay. The outcome mix varies with contention; conflict losers can finish sooner than committed payments, so a lower latency summary does not imply better successful throughput.

### Worker-count comparisons

For each change, I compared mean parallel attempted-throughput rates for the same nine transaction-count/contention combinations. The ratio is the new worker setting's rate divided by the old setting's rate. Changes greater than 1% count as improved; changes below -1% count as worse; values within Â±1% count as ties.

| Change | Mean paired throughput ratio | Improved | Worse | Tied |
|---|---:|---:|---:|---:|
| 1 â†’ 2 workers | 1.033x | 6 | 3 | 0 |
| 2 â†’ 4 workers | 1.037x | 6 | 2 | 1 |
| 4 â†’ 8 workers | 0.949x | 1 | 8 | 0 |
| 1 â†’ 4 workers | 1.071x | 7 | 2 | 0 |
| 1 â†’ 8 workers | 1.015x | 4 | 5 | 0 |

The measurements show gains in many 1â†’2 and 2â†’4 comparisons, followed by lower throughput in most 4â†’8 comparisons. The worker response is not monotonic across the full matrix.

### Contention and outcomes

Contention is the percentage of attempted transactions that participate in pairwise shared-input groups. Each pair has two participants; one succeeds and one becomes a conflict loser. Thus 20% participants yield 10% conflict losers and 50% participants yield 25% losers.

| Participant contention | Attempts per path | Successful | Conflicting | Rejected |
|---:|---:|---:|---:|---:|
| 0% | 133,200 | 133,200 | 0 | 0 |
| 20% | 133,200 | 119,880 | 13,320 | 0 |
| 50% | 133,200 | 99,900 | 33,300 | 0 |

| Contention | Sequential attempted tx/s | Parallel attempted tx/s | Sequential successful tx/s | Parallel successful tx/s |
|---:|---:|---:|---:|---:|
| 0% | 5,307.71 | 4,289.92 | 5,307.71 | 4,289.92 |
| 20% | 5,321.43 | 4,037.50 | 4,789.28 | 3,633.75 |
| 50% | 5,534.65 | 4,218.56 | 4,150.99 | 3,163.92 |

Attempted throughput counts conflict losers; successful throughput counts committed transactions. Success share declines by construction from 100% to 90% to 75%. The higher attempted-rate mean at 50% contention for the sequential path should not be interpreted as higher successful-payment performance.

### CPU and peak traced memory

Means within transaction-count groups, over all workers and contention levels and all three runs:

| Transactions | Sequential whole-system CPU | Parallel whole-system CPU | Sequential process CPU time | Parallel process CPU time | Sequential peak traced memory | Parallel peak traced memory |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 15.61% | 16.20% | 15.625 ms | 29.514 ms | 0.094 MiB | 0.250 MiB |
| 1,000 | 15.70% | 18.80% | 181.424 ms | 286.458 ms | 0.905 MiB | 2.441 MiB |
| 10,000 | 14.16% | 18.21% | 1,855.035 ms | 3,357.639 ms | 9.582 MiB | 26.119 MiB |

Across all runs, mean whole-system CPU utilization was **15.16% sequential** and **17.74% parallel**. Mean process CPU time was **684.028 ms sequential** and **1,224.537 ms parallel**. Whole-system readings ranged from 5.26%â€“46.89% sequential and 4.76%â€“60.00% parallel. They include unrelated system processes. Process CPU time is not CPU utilization and showed 15.625 ms increments in this Windows environment.

Peak traced memory measures Python allocations above the execution baseline. It does not include native cryptography allocations or total resident memory. Tracemalloc instrumentation is active during both execution paths and adds overhead.

### Run-to-run variability

For each configuration and path, the coefficient of variation is the sample standard deviation of the three run-level throughput rates divided by their mean. Across 36 configurations per path:

| Path | Mean CV | Median CV | Maximum CV and configuration |
|---|---:|---:|---|
| Sequential | 4.21% | 2.79% | 22.59% â€” 1,000 transactions, 1 worker, 0% contention |
| Parallel | 4.29% | 2.71% | 20.29% â€” 100 transactions, 8 workers, 50% contention |

Three runs provide only a limited view of variability. These descriptive statistics do not establish statistical significance or repeatable speedups.

## Ledger integrity and path equivalence

All 108 measured comparisons report equivalent final outcomes. The benchmark checks conserved supply including fees; unique spent inputs; agreement between the spent set and history; recorded fees; successful history length and transaction sequence; reconciled attempted/success/conflict/rejection counts; and equal final UTXOs, spent inputs, history, fees, and next transaction ID between the paired paths. No integrity, equivalence, or outcome-count failure was found in the selected reports.

## Threats to validity and scope limitations

- **Small sample:** Three measured runs per configuration limit confidence in both mean and variability estimates.
- **Timing boundary:** Parallel time includes worker-pool startup/shutdown and dispatch as well as validation and commits. Sequential time includes per-transfer latency bookkeeping. The results compare current APIs, not only cryptographic verification costs.
- **Instrumentation:** `tracemalloc` and parallel completion timestamp instrumentation add overhead. Timestamp overhead is estimated and recorded, but not fully removed from measured latency.
- **Uncontrolled system activity:** Whole-system CPU comes from Windows counters and includes other processes. Counter readings over short runs have limited precision; CPU model and background workload were not controlled or fully recorded.
- **Workload coverage:** The benchmark uses synthetic signed transactions and caps distinct senders at 1,000 for 10,000-transaction workloads. It does not cover networking, persistence, consensus, realistic payment distributions, or same-batch chained spends.
- **External validity and privacy:** The project is an in-memory educational simulator. Public-key-derived addresses are pseudonymous identifiers; the system does not implement zero-knowledge proofs, ring signatures, transaction-data encryption, or production CBDC privacy/security controls.

## Conclusion

The newest matrix demonstrates that the tested parallel batch path preserved ledger integrity and produced outcomes equivalent to sequential signed transfers. It did not improve aggregate throughput: sequential measured 5,385.95 attempted tx/s and 4,757.59 successful tx/s, compared with 4,179.26 attempted tx/s and 3,691.68 successful tx/s in parallel. Every configuration's recomputed mean-rate speedup was below 0.99 in this run set. These results evaluate this simulator under the stated conditions; they do not establish that parallel execution is universally slower. More repetitions under controlled system load and broader representative workloads would be needed for generalization.

This report uses the `20261011T171052â€¦` pairwise matrix as current. Older reports remain historical evidence. Phase 5 is **COMPLETE**; the project-owner documentation review passed with no inconsistencies.
