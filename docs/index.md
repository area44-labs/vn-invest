# VN Invest Documentation Map

This directory contains the authoritative technical documentation for **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Shared Guidance & System Overview

| Document                                          | Description                                                                     | When should I read this?                                            |
| :------------------------------------------------ | :------------------------------------------------------------------------------ | :------------------------------------------------------------------ |
| [`AGENTS.md`](../AGENTS.md)                       | Mandatory AI agent guidelines, core constraints, and entry commands.            | Read before starting any development or maintenance task.           |
| [`docs/agent-workflow.md`](agent-workflow.md)     | Canonical step-by-step decision rules and execution sequence for coding agents. | Read when planning code edits, testing, or submitting changes.      |
| [`docs/architecture.md`](architecture.md)         | Subsystem boundaries, end-to-end data flow, package hierarchy, and rules.       | Read when designing new features or modifying subsystem boundaries. |
| [`docs/coding-standards.md`](coding-standards.md) | Python engineering conventions, typing rules, error handling, and formatting.   | Read before writing or refactoring Python code in `scripts/`.       |
| [`docs/naming.md`](naming.md)                     | Canonical system terminology, versioning contracts, and file naming rules.      | Read when naming new files, modules, classes, variables, or fields. |

---

## 2. Shared Data Contracts & Artifacts

| Document                                      | Description                                                                             | When should I read this?                                                     |
| :-------------------------------------------- | :-------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------- |
| [`docs/data-contracts.md`](data-contracts.md) | JSON Schemas (`schemas/v2/`), validation boundaries, version contracts, and invariants. | Read when altering payload structures, adding fields, or updating schemas.   |
| [`docs/artifacts.md`](artifacts.md)           | Generated JSON payload specifications, POSIX locking, transactions, and provenance.     | Read when modifying artifact generation, publishing, or historical indexing. |

---

## 3. Backend Subsystems

| Document                                  | Description                                                                                   | When should I read this?                                                  |
| :---------------------------------------- | :-------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------ |
| [`docs/pipeline.md`](pipeline.md)         | 9 production pipeline execution stages, orchestration lifecycle, and context flow.            | Read when altering pipeline stage logic or execution order.               |
| [`docs/quantitative.md`](quantitative.md) | Technical indicators, signal scoring, T+2.5 risk modeling, regime detection, and backtesting. | Read when updating financial models, technical indicators, or risk rules. |
| [`docs/monitoring.md`](monitoring.md)     | Operational data quality checks, data/model drift tracking, and baseline qualification.       | Read when modifying monitoring evaluator checks or drift thresholds.      |

---

## 4. Frontend Subsystem

| Document                          | Description                                                                              | When should I read this?                                              |
| :-------------------------------- | :--------------------------------------------------------------------------------------- | :-------------------------------------------------------------------- |
| [`docs/frontend.md`](frontend.md) | React SSG architecture, routing, typed data loaders (`LoadResult<T>`), and UI standards. | Read before making changes to `src/`, UI components, or data loaders. |

---

## 5. Testing & Operations

| Document                        | Description                                                                                | When should I read this?                                             |
| :------------------------------ | :----------------------------------------------------------------------------------------- | :------------------------------------------------------------------- |
| [`docs/testing.md`](testing.md) | Test suite organization, network isolation, fixtures, markers, and execution commands.     | Read when writing new tests or running backend/frontend test suites. |
| [`docs/ci-cd.md`](ci-cd.md)     | GitHub Actions workflows, triggers, path filters, scheduled updates, and Pages deployment. | Read when modifying `.github/workflows/` or operational schedules.   |
