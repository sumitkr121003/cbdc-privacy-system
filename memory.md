# Project Memory: CBDC Privacy System

**Last Updated:** October 11, 2026
**Status:** Phases 1–5 Complete
**Project Path:** `C:\Users\sumit\cbdc-privacy-system`

---

## 1. Project Purpose and Research Question

* **Project Purpose:** Educational and research digital currency transaction simulator using a Python-based Unspent Transaction Output (UTXO) model.
* **Core Research Question:** *"Can safe parallel transaction validation improve throughput compared with sequential validation while preserving UTXO integrity?"*
* **Hypothesis:** Multi-threaded parallel validation can improve throughput for non-conflicting transactions by executing CPU-heavy Ed25519 signature checks across worker threads (releasing the Python GIL in C), provided state commitment is synchronized to eliminate double-spending.

---

## 2. Current Architecture and Verified Implementation State

* **Core State Machine:** `src/utxo_engine.py`
  - In-memory UTXO mapping (`self.utxos`) and spent set (`self.spent_utxos`).
  - Simulator test-fund issuance (`issue_test_funds`).
  - Read-only validation split (`_prepare_transfer`, `validate_transfer`).
  - Single-transaction execution with fee accounting and change output creation (`transfer`, `transfer_signed`).
  - Immutable history tracking (`get_transaction_history`).
* **Wallet Subsystem:** `src/wallet.py`
  - Ed25519 asymmetric cryptography keypairs using `cryptography` library.
  - Public key hex address generation (64 hex characters).
  - Canonical JSON payment signing with sorted keys and sorted inputs.
* **Test Suite:** `tests/`
  - 87 tests passed in full-suite runs before and after the Phase 4 matrix (October 11, 2026).
* **Batch Authorization:** `BatchTransactionProcessor` requires a registered sender wallet and a valid Ed25519 signature for every structurally valid payment. Missing signatures are rejected before ledger validation/commit. Sequential simulator `UTXOEngine.transfer()` and test-fund issuance behavior are unchanged.

---

## 3. Important File Locations and Commands

| Resource | Path / Command | Purpose |
| :--- | :--- | :--- |
| **Virtual Environment** | `C:\Users\sumit\cbdc-privacy-system\.venv` | Python 3.13.5 environment |
| **Test Command** | `.\.venv\Scripts\python.exe -m pytest -q` | Run full automated test suite |
| **Baseline Benchmark** | `.\.venv\Scripts\python.exe benchmarks\baseline.py` | Run 1,000 tx sequential benchmark |
| **PRD Specification** | `C:\Users\sumit\cbdc-privacy-system\PRD.md` | Primary product requirements |
| **System Architecture**| `C:\Users\sumit\cbdc-privacy-system\architecture.md` | Two-phase architecture & concurrency |
| **System Design** | `C:\Users\sumit\cbdc-privacy-system\design.md` | Data structures & CLI specs |
| **Rules & Conventions**| `C:\Users\sumit\cbdc-privacy-system\rules.md` | Development rules & guidelines |
| **Milestone Plan** | `C:\Users\sumit\cbdc-privacy-system\phases.doc.md` | Ordered implementation roadmap |

---

## 4. Approved Design Decisions

1. **Concurrency Model:** Thread-based parallelism (`ThreadPoolExecutor`) for Phase 1 read-only validation; re-entrant mutex (`threading.RLock`) for Phase 2 state commit.
2. **GIL Opportunity:** Ed25519 signature verification in `cryptography` executes in C and releases the Python GIL, enabling multi-core parallelism for signed transactions.
3. **Double-Spend Resolution Policy:** First-to-commit wins. Competing transactions spending the same UTXO are rejected with `CONFLICT_DOUBLE_SPEND`.
4. **Interface:** CLI-only interface; no web UI or API server.
5. **Metrics Required:** Throughput (tx/s), execution time, latency distribution (mean, p50, p95, p99), CPU %, and peak memory (`tracemalloc`).
6. **Workloads & Contention Matrix:** 100, 1,000, and 10,000 transactions across 0%, 20%, and 50% contention tiers.

---

## 5. Current Phase and Status

* **Completed Phases:**
  - **Phase 1 — Thread-Safe State Synchronization & Formal Transaction Data Models** (Complete, verified)
  - **Phase 2 — Two-Phase Batch Validation Pipeline (`BatchTransactionProcessor`)** (Complete, verified)
  - **Phase 3 — Concurrency & Double-Spend Stress Test Suite** (Complete, verified)
  - **Phase 4 — Comparative Performance Benchmark Harness** (Complete, verified)
  - **Phase 5 — Research Analysis, Findings Report, and Final Documentation** (Complete, owner review passed)
* **Status:** Phases 1–5 complete.
* **Current Phase:** None; all documented phases are complete.

---

## 6. Latest Verified Test and Benchmark Results

* **Date:** October 11, 2026
* **Test Suite Result:** **87 passed** in the full suite immediately before and after the Phase 4 matrix (`.\.venv\Scripts\python.exe -m pytest -q`; 4.95s before and 5.43s after).
* **Current authoritative Phase 4 Matrix:** 36 configurations (3 transaction counts × 4 worker counts × 3 pairwise contention profiles), one warm-up and three measured runs each. The current reports match `benchmarks/results/compare_20261011T171052*_pairwise.json` and have matching Markdown files. Older `20261011T165800…` reports and hotspot smoke reports remain historical and are excluded from current findings. All 108 current measured comparisons passed outcome-equivalence and ledger-integrity checks.
* **Latest full test suite:** **100 passed in 5.86 seconds** (`.\.venv\Scripts\python.exe -m pytest -q`; latest verified run).
* **Historical full test results:** 87 passed before and after the Phase 4 matrix; the earlier Phase 5 verification recorded 100 passed. These historical results are retained separately from the latest 100-passed, 5.86-second run above.
* **Verified Phase 4 findings:** Independently recomputed from the 36 current JSON reports and documented in `benchmarks/PHASE4_FINDINGS.md` and `docs/research-findings.md`. Aggregate attempted throughput: 5,385.95 tx/s sequential and 4,179.26 tx/s parallel; aggregate successful throughput: 4,757.59 and 3,691.68 tx/s. Mean/median per-configuration speedup from run-level rate means: 0.828x/0.818x; parallel was faster in 0 configurations, slower in 36, and tied in 0 using the ±1% band. These three-run results do not establish a universal performance result.
* **Resource observations:** Newest matrix whole-system CPU means were 15.16% sequential and 17.74% parallel; mean process CPU time was 684.028 ms and 1,224.537 ms, respectively. Process CPU time is not CPU utilization. Parallel peak traced memory also exceeded sequential in all transaction-count groups; detailed grouped measurements and limitations are in the findings report.
* **Historical baseline benchmark result:** (`.\.venv\Scripts\python.exe benchmarks\baseline.py`)
  - Attempted: 1,000 transactions
  - Successful: 1,000 transactions
  - Wall-clock time: 0.006673 s
  - Sequential Throughput: 149,848.65 tx/s (in-memory unsigned transfers with re-entrant lock synchronization; one run)

---

## 7. Known Issues and Next Step

* **Verified Limitations:** Batch validation checks inputs against the pre-batch ledger, so transactions cannot spend outputs created earlier in the same batch.
* **Historical Batch Authorization Verification (Phase 3):** `tests/test_batch_processor.py` and `tests/test_concurrency.py` passed together (14 passed in 1.61s); the full suite at that earlier point passed 66 tests. Missing and invalid signatures were rejected without balance, spent-input, fee, transaction-ID, or history changes.
* **Phase 3 Verification:** `tests/test_concurrency.py` passed three consecutive targeted runs before the batch authorization policy change (5 passed each). No deadlocks, unhandled concurrency exceptions, duplicate committed spends, or supply-conservation failures were observed in the verified tests.
* **Phase 4 status:** Complete. All documented Phase 4 acceptance criteria are checked in `phases.doc.md`; matrix evidence and interpretation are in `benchmarks/PHASE4_FINDINGS.md`.
* **Phase 4 follow-up verification (October 11, 2026):** Added attempted-throughput speedup fields to generated JSON reports (parallel / sequential, safely null for invalid rates), separate `hotspot` contention alongside default `pairwise`, optional final-outcome timestamp collection, and Windows whole-system CPU utilization from `GetSystemTimes`. Process CPU time and process CPU capacity share remain separately labeled. Derived speedups were backfilled into 37 earlier JSON/Markdown pairs; no historical benchmark execution or measured value changed. All 41 JSON reports contain speedup fields. Parallel latency is now measured as batch-submission-to-final-outcome latency, including queue waiting; reports state this definition and instrument overhead.
* **Verified follow-up tests:** `tests/test_compare_parallel.py` — 28 passed; full suite — 94 passed. Small 100-transaction, 2-worker, 20% smoke runs passed integrity/equivalence checks for both pairwise (90 successes, 10 conflicts) and hotspot (81 successes, 19 conflicts), with zero rejections. Reports: `benchmarks/results/compare_20261011T121801047200Z_n100_w2_c20_pairwise.json` and matching `.md`; `benchmarks/results/compare_20261011T121801049641Z_n100_w2_c20_hotspot.json` and matching `.md`. At that checkpoint the full matrix had not yet been rerun and Phase 4 was still in progress.
* **Latest verified latency/CPU update:** `tests/test_batch_processor.py` plus `tests/test_compare_parallel.py` — 43 passed; full suite — 100 passed. A 100-transaction hotspot smoke run recorded 81 successes, 19 conflicts, zero rejections, equivalent ledgers, parallel per-run p50/p95/p99 values, and whole-system CPU readings. Completion timestamp recording estimates were 630, 649, and 658 ns per outcome in that smoke run. See `benchmarks/results/compare_20261011T123807333983Z_n100_w2_c20_hotspot.json` and its matching Markdown. These smoke readings are not general performance findings.
* **Phase 4 completion verification (October 11, 2026):** The current `20261011T171052…` pairwise matrix contains 36 unique configurations and 108 measured comparisons. All outcomes are equivalent, outcome totals reconcile, parallel p50/p95/p99 and whole-system CPU measurements are present, and no CPU values are unavailable. Phase 4 acceptance criteria are satisfied.
* **Phase 5 documentation progress:** `README.md`, `docs/research-findings.md`, and `benchmarks/PHASE4_FINDINGS.md` use the newest 36 pairwise JSON reports (`compare_20261011T171052*_pairwise.json`) and independently recomputed results. The full-matrix analysis and hypothesis-evaluation criteria are checked; the owner reviewed the documentation and found no inconsistencies. All Phase 5 acceptance criteria are satisfied and Phase 5 is complete.
