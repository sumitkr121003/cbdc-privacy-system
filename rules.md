# Project Rules and Development Guidelines: CBDC Privacy System

**Version:** 1.0.0
**Effective Date:** October 11, 2026
**Project Path:** `C:\Users\sumit\cbdc-privacy-system`

---

## 1. Document Hierarchy & Sources of Truth

1. **`PRD.md`** is the ultimate authority on project scope, requirements, invariants, and success metrics.
2. **`architecture.md`** is the authority on system boundaries, concurrency model, pipeline stages, and threat mitigations.
3. **`design.md`** is the authority on data structures, validation rules, CLI commands, and test scenarios.
4. **`phases.doc.md`** is the authority on implementation sequencing, milestones, and definitions of done.
5. **`memory.md`** is the dynamic record of verified project state, completed phases, and observed benchmark/test metrics.
6. **Conflict Resolution:** If code or proposals contradict `PRD.md` or `architecture.md`, the code/proposal must be adapted—never weaken the core requirements or integrity guarantees.

---

## 2. Python Coding Conventions

- **Target Version:** Python 3.13.x.
- **Type Annotations:** Use standard Python type hinting (`str`, `int`, `list`, `dict`, `tuple`, `Optional`, `Union` or `|` syntax).
- **Data Modeling:** Use `@dataclass(frozen=True)` for immutable value objects (`UTXO`, `Transaction`, `TransactionResult`).
- **Formatting & Style:** Clean, readable PEP 8 compliant code. Meaningful variable and function names.
- **Docstrings & Comments:** Preserve all existing docstrings and explanatory comments. Document every new public class and method clearly.
- **Imports:** Standard library first, third-party (`cryptography`, `pytest`) second, local modules (`src.*`) third.

---

## 3. Small, Focused Changes Policy

- **Single Purpose:** Every code change must address one specific phase or requirement. Avoid monolithic or multi-phase commits.
- **Zero Unrelated Edits:** Do not reformat unrelated files, reorder existing functions, or remove working code unless explicitly requested.
- **Preserve Uncommitted Work:** Never overwrite, discard, or silently revert uncommitted working-tree changes without explicit authorization.

---

## 4. Transaction Correctness and UTXO Invariants

1. **Value Conservation:** $\sum \text{Inputs} = \text{Amount} + \text{Fee} + \text{Change}$. Value must never be created or destroyed during transfers.
2. **Double-Spend Invariance:** Any output ID recorded in `spent_utxos` must never be spent again by any subsequent transaction.
3. **Non-Negative & Positive Values:** Payment amounts must strictly be positive integers ($> 0$). Fees must be non-negative integers ($\ge 0$). No floating-point math for currency amounts.
4. **Distinct Parties:** Sender address and recipient address must not be identical.
5. **Input Ownership:** Every consumed UTXO must be registered as owned by the sender.
6. **Failure Insulation:** A failed or rejected transaction must produce **zero side-effects** on balances, unspent sets, fees, or transaction history.

---

## 5. Concurrency and Atomic Commit Rules

1. **Separation of Concerns:**
   - Phase 1 (Verification) is read-only and parallelizable (worker threads).
   - Phase 2 (Commit) is state-mutating and must be strictly atomic and synchronized.
2. **Re-entrant Mutex Protection:** All state mutations and state queries on `UTXOEngine` must be protected by a re-entrant lock (`threading.RLock`).
3. **Check-and-Set Inside Lock:** Input unspent verification and marking inputs as spent must occur atomically within the same lock acquisition to eliminate TOCTOU race conditions.
4. **Deterministic Conflict Resolution:** First-to-commit wins. Any competing concurrent spend of an already-committed UTXO must be rejected immediately with `CONFLICT_DOUBLE_SPEND`.

---

## 6. Testing and Regression Requirements

1. **100% Pass Rate:** The entire pytest test suite must pass after every modification. Zero test failures or regressions are permitted.
2. **Test Command:** Run `.\.venv\Scripts\python.exe -m pytest -q`.
3. **Behavior Coverage:** Any new behavior, invariant, or error condition must be accompanied by automated unit or integration tests before marking a phase complete.
4. **Concurrency Testing:** Concurrency features must be tested with multi-threaded stress tests simulating both disjoint workloads and concurrent double-spend race conditions.

---

## 7. Benchmark Reproducibility Rules

1. **Isolation of Timing:** Benchmark timers (`time.perf_counter()`) must only measure transaction validation and execution. Initial setup (wallet generation, genesis funding) must occur outside the timer.
2. **Warm-up and Repetition:** Benchmarks must include 1 warm-up run followed by multiple timed runs, recording both mean and standard deviation.
3. **Standard Workloads:** Use standardized transaction sizes (100, 1,000, 10,000) and contention profiles (0%, 20%, 50%).
4. **No Unsubstantiated Claims:** Never declare a throughput increase or speedup without presenting actual recorded benchmark output.

---

## 8. Dependency Management Rules

- Only use standard library modules (`concurrent.futures`, `threading`, `dataclasses`, `time`, `tracemalloc`, `json`, `copy`) and already-installed packages (`cryptography`, `pytest`).
- Do not introduce web frameworks (FastAPI, Flask), databases (SQLite, SQLAlchemy), message brokers (RabbitMQ, Celery), or heavy dependencies unless explicitly authorized in an approved phase.

---

## 9. Error Handling and Documentation Expectations

- Public APIs must raise clear, actionable exceptions (`ValueError` for invalid input parameters or business rule violations).
- Batch processing APIs must return structured result objects (`TransactionResult`) indicating status (`SUCCESS`, `REJECTED`, `CONFLICT_DOUBLE_SPEND`) with explicit error reasons.
- Keep documentation up to date: any architectural adjustment must be documented in `memory.md`.

---

## 10. Git and Change Management Policy

- Inspect `git status` and `git diff` before and after every modification.
- **Do not commit Git changes** autonomously. Leave staging and committing to the user unless explicitly instructed.
- Ensure the working tree remains in a clean, working state with all tests passing.

---

## 11. Security and Secret Handling

- This is an educational simulator using test funds. Real credentials or secrets must never be committed.
- Private keys must remain encapsulated inside `Wallet` instances; never log private keys or raw key bytes.
- Wallets use standard Ed25519 cryptography with constant-time operations provided by `cryptography`.

---

## 12. Instructions for Updating `memory.md`

- Update `memory.md` after every completed phase.
- Only record **verified facts** (actual test counts, observed benchmark throughput numbers, exact file paths).
- Keep verified facts strictly separated from future plans or assumptions.
