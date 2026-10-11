# CBDC Privacy System

An educational, in-memory UTXO simulator and benchmark project. It explores whether parallel validation of signed transactions can improve throughput over sequential processing without violating ledger integrity.

> **Scope:** This is a pseudonymous UTXO simulation using synthetic test funds. It is not a production CBDC, payment rail, or cryptographic privacy system. Ed25519 signatures authenticate payment payloads; they do not conceal transaction data or make users anonymous.

## Research problem

Sequential transaction validation is straightforward and avoids concurrency races, but each signed transaction is processed in order. Parallel validation may increase throughput by checking transaction signatures and structure in worker threads. It must still prevent double spending and preserve the ledger's value and history invariants when transactions compete for the same UTXO.

The project's research question is: **Can safe parallel transaction validation improve throughput compared with sequential validation while preserving UTXO integrity?** The hypothesis is that non-conflicting signed transactions may benefit from parallel signature verification, while contention and coordination costs may reduce gains. The completed Phase 4 measurements did not show aggregate throughput improvement in the tested matrix; see [the research findings](docs/research-findings.md) and [Phase 4 findings](benchmarks/PHASE4_FINDINGS.md).

## Scope and current implementation

The repository currently implements:

- An in-memory UTXO ledger with simulator-only test-fund issuance, balance queries, fees, change outputs, spent-input tracking, and transaction history.
- Ed25519 wallets with public-key-derived hexadecimal addresses and canonical payment serialization/signing.
- Signed single transfers and signed batch transactions. Batch transactions with missing or invalid signatures are rejected.
- A thread-safe engine using a re-entrant lock and a batch processor with parallel read-only validation followed by synchronized commits and double-spend conflict detection.
- Unit, authorization, concurrency, and benchmark tests.
- A simple baseline benchmark and a comparative signed-transfer benchmark with timestamped JSON and Markdown reports.

The command-line demo in `main.py` creates wallets, issues test funds, performs one signed payment, and prints balances, fee, and unspent outputs. The benchmark and test suite are research tools; the demo is not a wallet application or payment service.

## Architecture

```text
Wallet ── signs canonical payment payloads ──┐
                                             v
Sequential caller ───────────────────> UTXOEngine
Batch caller ──> BatchTransactionProcessor ─> UTXOEngine
                   parallel validation       synchronized commit
```

- `src/wallet.py` generates Ed25519 keys and signs/verifies canonical payment messages.
- `src/utxo_engine.py` owns the in-memory UTXO state, wallet registry, fees, and history. State access is synchronized with `threading.RLock`.
- `src/batch_processor.py` validates transaction structure and signatures in a `ThreadPoolExecutor`, then checks live input spend status and commits under the engine lock. Competing spends result in `CONFLICT_DOUBLE_SPEND`; invalid transactions are rejected.
- `benchmarks/compare_parallel.py` creates signed workloads and equivalent fresh ledgers, times the sequential and parallel APIs, checks outcomes and ledger invariants, and writes JSON/Markdown reports.

This architecture does not provide persistent storage, network consensus, block production, an issuing authority, or distributed settlement. A batch cannot spend outputs created earlier within that same batch; the benchmark uses independently spendable inputs except for deliberate collisions.

## Technology

- Python 3.13 (the recorded benchmark environment used Python 3.13.5)
- `cryptography` for Ed25519
- `pytest` for automated tests
- Python standard library for threading, timing, JSON reports, memory tracing, and Windows system CPU counters

There is no `requirements.txt` or `pyproject.toml` in the repository. The runtime dependency is `cryptography`; `pytest` is used for tests. The commands below install those packages into a project virtual environment.

## Windows setup

From PowerShell in the repository root, create the environment and install dependencies:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install cryptography pytest
```

The Python launcher command was verified with Python 3.13.5 in the project environment. If the virtual environment already exists, skip its creation and use its interpreter directly.

## Run the demo

```powershell
.\.venv\Scripts\python.exe main.py
```

The verified demo performs one signed payment and prints `SUCCESS`, both balances, the transaction fee, total fees, and the sender's remaining unspent output.

## Run tests

Run the complete test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Relevant focused suites include:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_utxo_engine.py tests\test_wallet.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_batch_processor.py tests\test_concurrency.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_compare_parallel.py -q
```

The latest full-suite result recorded in project memory is 100 passing tests. The repository's project rules prescribe the full-suite command above.

## Run benchmarks

The simple baseline runs 1,000 sequential, in-memory `transfer()` calls. It does not use signed transfers and should not be compared directly with the signed comparison benchmark.

```powershell
.\.venv\Scripts\python.exe benchmarks\baseline.py
```

For one small signed comparison and a timestamped JSON/Markdown report pair:

```powershell
.\.venv\Scripts\python.exe benchmarks\compare_parallel.py --count 100 --workers 2 --contention 20 --collision-pattern pairwise --output-dir benchmarks\results
```

To run the full Phase 4 pairwise matrix (36 configurations):

```powershell
.\.venv\Scripts\python.exe benchmarks\compare_parallel.py --count 100 1000 10000 --workers 1 2 4 8 --contention 0 20 50 --collision-pattern pairwise --output-dir benchmarks\results
```

The current CLI supports `--count` values 100/1000/10000, `--workers` values 1/2/4/8, `--contention` values 0/20/50, `--collision-pattern pairwise|hotspot`, and `--output-dir`. It writes unique timestamped JSON and Markdown reports. Use `--help` for the installed CLI options.

Setup, signing, funding, integrity checks, report generation, and outcome comparison are excluded from execution timing. Parallel timing includes `process_batch` worker-pool startup/shutdown, validation, and commit processing. `tracemalloc` is active during both paths. On Windows, the benchmark reports whole-system CPU utilization from `GetSystemTimes`; unrelated system processes affect it, and short runs limit precision. See the findings reports before interpreting results.

## Completed Phase 4 result

The current authoritative 36-configuration pairwise matrix is the JSON report set matching `benchmarks/results/compare_20261011T171052*_pairwise.json` (each has a matching Markdown report). It includes one warm-up and three measured runs per configuration; all 108 measured comparisons reported equivalent outcomes and passed ledger checks. Aggregate attempted throughput was **5,385.95 tx/s sequential** and **4,179.26 tx/s parallel**; aggregate successful throughput was **4,757.59 tx/s** and **3,691.68 tx/s**. Parallel did not improve aggregate throughput, and recomputed configuration speedups were below 1.0 in all 36 cases. These findings apply only to the tested simulator workloads and do not show that parallel processing is universally slower. The older `20261011T165800…` matrix and smoke reports remain available as historical runs and are excluded from the current findings. Full methodology, tables, and limitations are in [`docs/research-findings.md`](docs/research-findings.md) and [`benchmarks/PHASE4_FINDINGS.md`](benchmarks/PHASE4_FINDINGS.md).

## Limitations and privacy boundary

- The ledger and transaction history live only in process memory; there is no persistence, network, consensus, access control, or recovery model.
- Public-key-derived addresses are pseudonymous identifiers. The simulator does not encrypt transaction amounts or hide sender, recipient, input, output, or history data from an observer with ledger access.
- There are no zero-knowledge proofs, ring signatures, mixers, or formal privacy guarantees. Ed25519 provides authorization/integrity for signed payloads, not transaction confidentiality.
- Test-fund issuance is a simulator operation, not an authorized central-bank issuance process.
- Batch validation uses the pre-batch ledger for read-only checks, so same-batch chained spends are unsupported.
- The benchmark is synthetic and in-memory. It caps distinct sender wallets at 1,000 for 10,000-transaction workloads, includes worker-pool overhead in parallel timing, uses only three measured repetitions, and measures whole-system CPU on a machine with uncontrolled background load.
- The benchmark results do not establish production CBDC performance or that parallel execution is universally faster or slower.

## Project documents

- [Product requirements](PRD.md)
- [Architecture](architecture.md)
- [Design](design.md)
- [Implementation phases](phases.doc.md)
- [Project memory](memory.md)
- [Development rules](rules.md)
- [Stage 0 scope](docs/stage0-scope.md)
- [Phase 4 benchmark findings](benchmarks/PHASE4_FINDINGS.md)
- [Phase 5 research findings](docs/research-findings.md)
