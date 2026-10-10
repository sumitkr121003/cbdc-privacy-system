\# Stage 0 — Project Scope



\## Project Title



Privacy-Preserving Digital Currency Payment and Performance Evaluation System



\## Problem Statement



Digital currency payment systems need to validate transactions correctly while balancing performance, privacy, and auditability. This project will build a Python UTXO simulator and evaluate transaction correctness and processing performance.



\## Research Question



Can safe parallel transaction validation improve throughput compared with sequential validation while preserving UTXO integrity?



\## Improvement Hypothesis



Parallel validation may improve performance for non-conflicting transactions. Experiments will determine whether any improvement occurs without double spending or balance errors.



\## Initial Scope



1\. Represent UTXOs, transaction inputs, and outputs.

2\. Implement test-fund issuance, payments, fees, and change.

3\. Reject reused UTXOs and insufficient-fund transactions.

4\. Add automated correctness tests.

5\. Measure throughput, latency, CPU, memory, and failures.

6\. Compare sequential and safe parallel validation if feasible.



\## Evaluation Plan



Use workloads of 100, 1,000, and 10,000 transactions where practical. Establish a sequential baseline and document test conditions before evaluating optimizations.



\## Threat Model



Prevent double spending, insufficient-fund payments, unauthorized issuance, and invalid transaction modifications. Add digital signatures and role-based audit access in later stages.



\## Limitations



This is an educational prototype using test currency, not a real CBDC or a production-ready payment system.



\## Stage 0 Acceptance Criteria



\* Research question and hypothesis documented.

\* Initial scope defined.

\* Evaluation metrics identified.

\* Threats and expected system responses documented.



