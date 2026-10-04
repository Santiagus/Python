# Chaos Engineering & Failure Recovery Experiment Log

> **Generated**: `2026-10-04T21:56:33.060781+00:00`  
> **Status**: PASSED  
> **Average MTTR**: `3197.69 ms`

## 1. Executive Summary

| Total Experiments | Passed | Failed | Average MTTR |
| :---: | :---: | :---: | :---: |
| 5 | 5 | 0 | 3197.69 ms |

## 2. Chaos Experiment Execution Matrix

| ID | Experiment Name | Status | MTTR (ms) | Details / Invariants |
| :--- | :--- | :---: | :---: | :--- |
| **`EXP-01`** | Worker Hard Crash During Execution | `PASSED` | 200.84 | All financial & AMQP invariants verified |
| **`EXP-02`** | Early vs. Late Acknowledgement Trade-Offs | `PASSED` | 555.1 | All financial & AMQP invariants verified |
| **`EXP-03`** | RabbitMQ Broker Restart & Durable Recovery | `PASSED` | 8118.05 | All financial & AMQP invariants verified |
| **`EXP-04`** | Poison Pill Dead-Letter Exchange Quarantine | `PASSED` | 5015.84 | All financial & AMQP invariants verified |
| **`EXP-05`** | Mean Time to Recovery (MTTR) & Drift | `PASSED` | 2098.64 | All financial & AMQP invariants verified |

## 3. Financial Invariant Verification

* **Ledger Drift**: $0\text{ cents}$ (Exact mathematical balance $\sum \text{Debits} == \sum \text{Credits}$).
* **Double Disbursements**: $0$ phantom payouts detected.
* **Zero Lost Wires**: 100% of publisher-confirmed messages settled.
