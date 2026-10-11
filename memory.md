# Project Memory: CBDC Privacy System

**Last Updated:** October 11, 2026
**Status:** Phase 3 Complete; Phase 4 Pending
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
  - 66 tests pass, including UTXO, wallet, Phase 1, batch processor, and concurrency stress coverage.
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
* **Status:** Complete (Verified with 66 passing tests)
* **Next Active Phase:** **Phase 4 — Comparative Performance Benchmark Harness**

---

## 6. Latest Verified Test and Benchmark Results

* **Date:** October 11, 2026
* **Test Suite Result:** **66 passed in 1.71s** (`.\.venv\Scripts\python.exe -m pytest -q`)
  - `tests/test_utxo_engine.py`: 41 passed
  - `tests/test_wallet.py`: 6 passed
  - `tests/test_phase1.py`: 5 passed
  - `tests/test_batch_processor.py`: 9 passed (non-conflicting signed batches, 2-way and 3-way double spend detection, missing/invalid signature rejection, invalid parameter rejection, order preservation)
  - `tests/test_concurrency.py`: 5 passed (1,000 independent batch transactions, 100-thread spend race, read during locked commit, mixed batch outcomes, same-batch chained-spend limitation)
* **Baseline Benchmark Result:** (`.\.venv\Scripts\python.exe benchmarks\baseline.py`)
  - Attempted: 1,000 transactions
  - Successful: 1,000 transactions
  - Wall-clock time: 0.006673 s
  - Sequential Throughput: 149,848.65 tx/s (in-memory unsigned transfers with re-entrant lock synchronization; one run)

---

## 7. Known Issues and Next Step

* **Verified Limitations:** Batch validation checks inputs against the pre-batch ledger, so transactions cannot spend outputs created earlier in the same batch.
* **Batch Authorization Verification:** `tests/test_batch_processor.py` and `tests/test_concurrency.py` passed together (14 passed in 1.61s); the complete suite passed (66 passed in 1.71s). Missing and invalid signatures were rejected without balance, spent-input, fee, transaction-ID, or history changes.
* **Phase 3 Verification:** `tests/test_concurrency.py` passed three consecutive targeted runs before the batch authorization policy change (5 passed each). No deadlocks, unhandled concurrency exceptions, duplicate committed spends, or supply-conservation failures were observed in the verified tests.
* **Next Immediate Step:** Phase 4: implement the comparative benchmark harness described in `phases.doc.md`.
