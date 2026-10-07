# Repository Architecture Baseline Inventory & Freeze

## 1. Purpose

This document records the architecture baseline of `area44-labs/vn-invest` before structural cleanup begins.

M0 is an **audit-only phase**.

No production behavior, test behavior, API, workflow, or file structure is intentionally changed as part of this inventory.

The purpose is to establish an evidence-based baseline from which M1–M5 can be implemented independently.

### M0 objectives

1. Inventory the current `scripts/` architecture.
2. Identify production entry points.
3. Identify canonical modules and subsystem boundaries.
4. Identify legacy modules and compatibility layers.
5. Map `scripts.lib` production dependencies.
6. Map tests to production modules/APIs.
7. Map generated artifacts to their producers.
8. Identify public/internal API surfaces.
9. Identify migration, removal, and unresolved candidates.
10. Record uncertainty explicitly as `UNKNOWN` instead of guessing.

---

# 2. Classification Rules

Every audited component is assigned one or more of the following architectural statuses.

| Classification | Meaning                                                                                                            |
| -------------- | ------------------------------------------------------------------------------------------------------------------ |
| `CANONICAL`    | Current authoritative implementation and intended architectural home.                                              |
| `LEGACY`       | Existing implementation that remains functional but belongs to an older architecture.                              |
| `REMOVE`       | Confirmed obsolete/dead/compatibility-only component that can be deleted after its remaining callers are migrated. |
| `KEEP`         | Valid implementation that must remain; relocation is not currently required.                                       |
| `MIGRATE`      | Active code that must be moved or have callers redirected to the canonical architecture.                           |
| `UNKNOWN`      | Insufficient evidence or unresolved architectural decision. Must not be deleted based on assumption.               |

### Important rule

`MIGRATE` does **not** mean the implementation itself is wrong.

A module may contain valid business logic while still requiring migration because its current location is architectural legacy.

Likewise, `REMOVE` means removal is supported by current evidence; it does not authorize deletion during M0.

---

# 3. Current Architecture

The current repository is organized around the following major layers:

```text
scripts/
├── domain/          # Canonical domain models and contracts
├── data/            # Canonical market-data acquisition/normalization/validation
├── pipeline/        # Production pipeline orchestration
├── quant/           # Quantitative engines and configuration
├── performance/     # Performance instrumentation and evaluation
├── monitoring/      # Production monitoring and drift evaluation
├── artifacts/       # Artifact publishing, transaction, manifest and provenance
├── schema/          # Schema registry/version resolution
├── lib/             # Legacy compatibility/business modules
├── tests/            # Python test suite
└── generate_report.py  # Production CLI entry point
```

Additional architectural surfaces:

```text
schemas/v2/          # Versioned artifact schemas
src/data/            # Frontend data loading/adapters
generated/           # Published runtime artifacts
.github/workflows/   # CI and production automation
```

The intended architectural direction is:

```text
Provider
   ↓
Data Acquisition
   ↓
Canonical Data Validation
   ↓
Domain / Universe
   ↓
PipelineContext
   ↓
Quantitative Engines
   ↓
Performance
   ↓
Monitoring
   ↓
Artifact Publishing
   ↓
generated/
   ↓
Frontend
```

---

# 4. Production Entry Points

| Entry point                         | Purpose                                            | Status                               |
| ----------------------------------- | -------------------------------------------------- | ------------------------------------ |
| `scripts/generate_report.py`        | Main production CLI for pipeline/report generation | `CANONICAL`                          |
| `.github/workflows/update-data.yml` | Scheduled/manual production data update            | `CANONICAL`                          |
| `.github/workflows/tests.yml`       | Python CI test execution                           | `CANONICAL`, migration planned in M1 |
| `.github/workflows/pages.yml`       | Frontend/static deployment                         | `CANONICAL`                          |
| `src/data/loader.ts`                | Frontend runtime data loading                      | `CANONICAL`                          |

### Production command

The current production update command is:

```bash
uv run --frozen python scripts/generate_report.py --update
```

The current production workflow is:

```text
.github/workflows/update-data.yml
        ↓
checkout main
        ↓
Python 3.14 / uv
        ↓
uv sync --frozen
        ↓
generate_report.py --update
        ↓
generated/
        ↓
commit generated artifacts
        ↓
push main
```

### Important baseline finding

The workflow is named:

```text
.github/workflows/update-data.yml
```

and the workflow invokes:

```text
scripts/generate_report.py --update
```

This is the authoritative M0 baseline.

---

# 5. Canonical Architecture Inventory

## 5.1 Domain

```text
scripts/domain/
```

### Classification

`CANONICAL`

### Responsibility

Owns domain-level models and contracts such as:

- `Universe`
- `UniverseCandidate`
- pipeline/domain result objects
- domain validation/invariants

The domain layer should not depend on legacy `scripts.lib` modules.

---

# 5.2 Data

```text
scripts/data/
```

### Classification

`CANONICAL`

### Responsibility

Owns market-data acquisition, provider integration, normalization and validation.

Important canonical concepts include:

- market-data acquisition
- provider boundary
- canonical OHLCV representation
- market-data validation
- provider-specific handling

The long-term architecture is to keep provider-specific concerns inside `scripts/data/` rather than `scripts.lib`.

---

# 5.3 Pipeline

```text
scripts/pipeline/
```

### Classification

`CANONICAL`

### Responsibility

Owns production orchestration and stage execution.

Major responsibilities include:

- pipeline context
- stage sequencing
- data acquisition
- validation
- universe construction
- quantitative execution
- performance
- monitoring
- artifact publishing
- pipeline failure handling

The production pipeline should be the authoritative path for report generation.

---

# 5.4 Quantitative Layer

```text
scripts/quant/
```

### Classification

`CANONICAL`

### Responsibility

Owns quantitative engines and quantitative contracts.

Examples:

```text
scripts/quant/config.py
scripts/quant/features.py
scripts/quant/recommendation.py
scripts/quant/regime.py
scripts/quant/risk.py
scripts/quant/signal.py
scripts/quant/contracts.py
```

These modules are the intended destination for quantitative logic currently exposed through legacy `scripts.lib` adapters.

---

# 5.5 Performance

```text
scripts/performance/
```

### Classification

`CANONICAL`

### Responsibility

Owns:

- performance tracking
- stage metrics
- performance budgets
- regression evaluation
- performance schema integration

---

# 5.6 Monitoring

```text
scripts/monitoring/
```

### Classification

`CANONICAL`

### Responsibility

Owns:

- production monitoring
- drift detection
- monitoring evaluation
- data-quality checks
- monitoring models
- performance/regression monitoring

The monitoring implementation should not depend on `scripts.lib.monitoring` long term.

---

# 5.7 Artifacts

```text
scripts/artifacts/
```

### Classification

`CANONICAL`

### Responsibility

Owns:

- artifact publishing
- manifest generation
- provenance
- atomic publishing
- transaction/recovery behavior
- artifact integrity

Important modules include:

```text
scripts/artifacts/publisher.py
scripts/artifacts/manifest.py
scripts/artifacts/provenance.py
scripts/artifacts/transaction.py
scripts/artifacts/recovery.py
```

---

# 5.8 Schema

```text
scripts/schema/
schemas/v2/
```

### Classification

`CANONICAL`

### Responsibility

Owns explicit artifact schema resolution and versioning.

The repository now uses explicit schema-version architecture. Schema version must remain authoritative and fail-closed.

---

# 6. `scripts/lib/*` Legacy Inventory

`script/lib/` remains an active compatibility/business layer.

Therefore:

> **Do not delete `scripts/lib/` during M0.**

The audit identified production references that must be migrated before removal is safe.

## 6.1 Summary

| Module                              | Classification     | Current situation                                                      | Target                                                                                 |
| ----------------------------------- | ------------------ | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `scripts/lib/config.py`             | `MIGRATE`          | Production configuration adapter still referenced                      | `scripts/pipeline/constants.py`, `scripts/quant/config.py`, monitoring-owned constants |
| `scripts/lib/features.py`           | `REMOVE` candidate | No known production caller; test dependency remains                    | `scripts/quant/features.py`                                                            |
| `scripts/lib/monitoring.py`         | `REMOVE` candidate | Compatibility re-export; tests still reference it                      | `scripts/monitoring/*`                                                                 |
| `scripts/lib/recommendation.py`     | `MIGRATE`          | Production/test callers remain                                         | `scripts/quant/recommendation.py` / related quant contracts                            |
| `scripts/lib/regime.py`             | `MIGRATE`          | Production and legacy backtest callers remain                          | `scripts/quant/regime.py`                                                              |
| `scripts/lib/risk.py`               | `MIGRATE`          | Contains active risk/liquidity logic and legacy exports                | `scripts/quant/risk.py`                                                                |
| `scripts/lib/vietnam_market.py`     | `MIGRATE`          | Large legacy market-data/universe surface with production callers      | `scripts/data/*`, `scripts/domain/universe.py`                                         |
| `scripts/lib/backtest.py`           | `KEEP` + `MIGRATE` | Valid backtesting implementation but located in legacy package         | Dedicated canonical backtest location                                                  |
| `scripts/lib/portfolio_backtest.py` | `KEEP` + `MIGRATE` | Valid portfolio backtesting implementation; primarily test/offline use | Dedicated canonical backtest location                                                  |

---

# 7. Detailed Legacy Trace

## 7.1 `scripts/lib/config.py`

### Classification

`MIGRATE`

### Current role

Compatibility/configuration adapter exposing constants and configuration from multiple canonical subsystems.

### Known production dependency areas

Includes references from areas such as:

```text
scripts/generate_report.py
scripts/pipeline/context.py
scripts/pipeline/stages.py
scripts/pipeline/constants.py
scripts/monitoring/*
scripts/performance/*
scripts/artifacts/provenance.py
```

### Target

Split responsibility according to ownership:

```text
quantitative configuration
    → scripts/quant/config.py

pipeline constants/version information
    → scripts/pipeline/constants.py

monitoring-specific thresholds
    → scripts/monitoring/*
```

### Action

Migrate callers first.

Do not delete until all production and required test references are gone.

---

## 7.2 `scripts/lib/features.py`

### Classification

`REMOVE` candidate

### Current evidence

No known production dependency was identified during the audit.

Tests still reference legacy APIs.

### Target

```text
scripts/quant/features.py
```

### Action

Migrate remaining tests and verify repository-wide references.

Then remove the legacy module.

---

## 7.3 `scripts/lib/monitoring.py`

### Classification

`REMOVE` candidate

### Current role

Compatibility/re-export layer around:

```text
scripts/monitoring/*
```

### Current evidence

No known production dependency.

Tests still contain legacy imports.

### Action

Migrate tests to canonical monitoring modules.

Then remove the compatibility layer.

---

## 7.4 `scripts/lib/recommendation.py`

### Classification

`MIGRATE`

### Current role

Legacy adapter around quantitative recommendation/signal functionality.

### Target

```text
scripts/quant/recommendation.py
scripts/quant/signal.py
scripts/quant/contracts.py
```

### Action

Redirect production and test callers.

Remove only after repository-wide reference verification.

---

## 7.5 `scripts/lib/regime.py`

### Classification

`MIGRATE`

### Current role

Legacy wrapper around:

```text
scripts/quant/regime.py
```

### Known dependency areas

Includes:

```text
scripts/generate_report.py
scripts/lib/backtest.py
scripts/lib/portfolio_backtest.py
tests
```

### Action

Migrate callers to the canonical quantitative module.

---

## 7.6 `scripts/lib/risk.py`

### Classification

`MIGRATE`

### Current role

Contains active risk-related logic in addition to delegating quantitative risk functionality.

### Target

```text
scripts/quant/risk.py
```

### Important

This file must **not** be classified as pure compatibility code.

Some functionality still has to be relocated or otherwise proven redundant before removal.

### Action

First establish the canonical owner of:

```text
normalize_universe_liquidity_scores
```

and other remaining logic.

Then migrate callers.

---

## 7.7 `scripts/lib/vietnam_market.py`

### Classification

`MIGRATE`

### Current role

Large legacy market-data/universe module containing functionality related to:

- historical data retrieval
- OHLCV validation
- cleaned OHLCV data
- universe/provider behavior
- exchange price limits
- throttling

### Target architecture

```text
Market data
    → scripts/data/

Universe/domain
    → scripts/domain/

Pipeline-specific orchestration
    → scripts/pipeline/

Quantitative calculations
    → scripts/quant/
```

### Action

Migrate production callers incrementally.

Do not delete the module until all production dependencies have been removed and the real production pipeline has been validated.

---

## 7.8 `scripts/lib/backtest.py`

### Classification

`KEEP` + `MIGRATE`

### Current role

Contains substantive backtesting functionality including:

- point-in-time evaluation
- forward outcomes
- execution eligibility
- execution return calculations
- temporal/date handling
- walk-forward behavior

### Architectural conclusion

This is **not dead code**.

The logic should be preserved while the package location is reconsidered.

### Target

A dedicated canonical backtesting package is preferred, for example:

```text
scripts/backtest/
```

Possible target modules:

```text
scripts/backtest/engine.py
scripts/backtest/portfolio.py
```

The exact destination remains an architectural decision.

### Status

`UNKNOWN` for exact target package location.

---

## 7.9 `scripts/lib/portfolio_backtest.py`

### Classification

`KEEP` + `MIGRATE`

### Current role

Portfolio-level backtesting including:

- allocation
- position sizing
- portfolio aggregation
- transaction-cost awareness
- deterministic portfolio evaluation

### Architectural conclusion

The implementation remains useful and should not be deleted merely because it is not part of the daily production path.

### Target

Prefer a dedicated backtesting package:

```text
scripts/backtest/portfolio.py
```

Exact destination remains subject to architectural confirmation.

---

# 8. `scripts.lib` Dependency Map

The current repository still contains production references to `scripts.lib`.

Important dependency categories include:

```text
scripts/generate_report.py
    ├── scripts.lib.backtest
    ├── scripts.lib.config
    ├── scripts.lib.recommendation
    ├── scripts.lib.regime
    ├── scripts.lib.risk
    └── scripts.lib.vietnam_market

scripts/pipeline/*
    ├── scripts.lib.config
    └── scripts.lib.vietnam_market

scripts/quant/*
    └── selected legacy market-data dependencies

scripts/monitoring/*
    └── selected legacy market-data/config dependencies

scripts/performance/*
    └── selected legacy configuration dependencies

scripts/artifacts/*
    └── selected legacy configuration dependencies
```

### M2 acceptance requirement

After M2:

```bash
grep/search "scripts.lib"
```

must produce no unexplained production dependency.

Any remaining reference must be explicitly documented.

---

# 9. Public vs Internal API Surface

The repository does not currently have a formally isolated public Python package API.

The following should therefore be treated as **internal APIs unless explicitly documented otherwise**:

```text
scripts/*
scripts/lib/*
scripts/pipeline/*
scripts/quant/*
scripts/data/*
scripts/domain/*
```

The primary externally meaningful interfaces are:

```text
CLI:
scripts/generate_report.py

Generated artifacts:
generated/*.json

Versioned schemas:
schemas/v2/*.json

Frontend data contract:
generated/ + src/data/
```

### Architectural rule

Internal module paths must not be preserved indefinitely merely for backward compatibility if the architecture has formally replaced them.

Migration should update:

```text
production callers
+
tests
+
documentation
```

together.

---

# 10. Test → Production Mapping

The current test suite is located under:

```text
scripts/tests/
```

and is currently executed through:

```text
scripts/tests/run_tests.py
```

The mapping below records the major ownership boundaries.

| Test area                        | Primary production owner                        |
| -------------------------------- | ----------------------------------------------- |
| `test_domain.py`                 | `scripts/domain/`                               |
| `test_data_*.py`                 | `scripts/data/` and data-provider boundaries    |
| `test_pipeline*.py`              | `scripts/pipeline/`                             |
| `test_engines.py`                | `scripts/quant/`                                |
| `test_recommendation.py`         | `scripts/quant/`                                |
| `test_regime.py`                 | `scripts/quant/regime.py`                       |
| `test_risk.py`                   | `scripts/quant/risk.py`                         |
| `test_performance*.py`           | `scripts/performance/`                          |
| `test_monitoring*.py`            | `scripts/monitoring/`                           |
| `test_artifact*.py`              | `scripts/artifacts/`                            |
| `test_provenance.py`             | `scripts/artifacts/provenance.py`               |
| `test_schema.py`                 | `scripts/schema/` + `schemas/v2/`               |
| `test_historical_report.py`      | `scripts/generate_report.py` / pipeline history |
| `test_history_index.py`          | history/report generation                       |
| `test_output_integrity.py`       | pipeline/artifact validation                    |
| `test_e2e_backtest_integrity.py` | backtesting subsystem                           |
| `test_execution_costs.py`        | backtesting subsystem                           |
| `test_portfolio_backtest.py`     | portfolio backtesting                           |
| `test_parity.py`                 | pipeline/report parity                          |
| `test_ssg_html.py`               | frontend/static artifact integration            |

### Legacy test dependencies

Some tests still import or patch legacy modules such as:

```text
scripts.lib.monitoring
scripts.lib.features
scripts.lib.recommendation
scripts.lib.regime
scripts.lib.risk
scripts.lib.vietnam_market
```

These references are migration targets.

They should not be interpreted as evidence that the legacy modules are still architecturally canonical.

---

# 11. Current Test Infrastructure

Current CI executes:

```bash
uv run --frozen python scripts/tests/run_tests.py
```

The custom runner currently provides:

- `unittest` discovery
- custom filtering
- custom timing output
- network-isolation initialization

The custom runner is therefore a real compatibility/test infrastructure surface and is **not** simply dead code.

### M1 target

Issue #222 explicitly requires migration to:

```bash
uv run --frozen pytest
```

with appropriate fixtures/plugins replacing the custom mechanisms.

Therefore:

```text
scripts/tests/run_tests.py
```

is classified:

`MIGRATE → REMOVE`

rather than immediate `REMOVE`.

---

# 12. Generated Artifact Mapping

Generated artifacts are runtime outputs and should be treated as part of the production contract.

| Artifact                            | Producer                                            | Architectural owner                                         |
| ----------------------------------- | --------------------------------------------------- | ----------------------------------------------------------- |
| `generated/recommendations.json`    | Recommendation/quant pipeline + artifact publishing | `scripts/quant/`, `scripts/pipeline/`, `scripts/artifacts/` |
| `generated/market.json`             | Market analysis pipeline stage                      | `scripts/pipeline/` + `scripts/quant/`                      |
| `generated/performance.json`        | Performance pipeline stage                          | `scripts/performance/`                                      |
| `generated/monitoring.json`         | Monitoring pipeline stage                           | `scripts/monitoring/`                                       |
| `generated/provenance.json`         | Artifact publishing/provenance                      | `scripts/artifacts/`                                        |
| `generated/history/index.json`      | Historical report/index generation                  | `scripts/generate_report.py` + artifact layer               |
| `generated/history/YYYY-MM-DD.json` | Historical report generation                        | `scripts/generate_report.py` + pipeline/artifact layer      |

### Artifact invariant

The frontend consumes generated artifacts.

The frontend is not the producer of these artifacts.

---

# 13. Compatibility Layer Inventory

| Component                           | Classification     | Reason                                              |
| ----------------------------------- | ------------------ | --------------------------------------------------- |
| `scripts/lib/monitoring.py`         | `REMOVE` candidate | Compatibility re-export; no known production caller |
| `scripts/lib/features.py`           | `REMOVE` candidate | No known production caller; remaining test imports  |
| `scripts/lib/recommendation.py`     | `MIGRATE`          | Production/test callers remain                      |
| `scripts/lib/regime.py`             | `MIGRATE`          | Production/legacy callers remain                    |
| `scripts/lib/risk.py`               | `MIGRATE`          | Contains substantive remaining logic                |
| `scripts/lib/config.py`             | `MIGRATE`          | Production callers remain                           |
| `scripts/lib/vietnam_market.py`     | `MIGRATE`          | Major production dependency surface                 |
| `scripts/lib/backtest.py`           | `KEEP` + `MIGRATE` | Valid backtesting engine in legacy location         |
| `scripts/lib/portfolio_backtest.py` | `KEEP` + `MIGRATE` | Valid backtesting engine in legacy location         |
| `scripts/tests/run_tests.py`        | `MIGRATE → REMOVE` | Replaced by pytest in M1                            |

No new compatibility layers should be introduced merely to make M1/M2 easier.

---

# 14. UNKNOWN / Decision Required

M0 intentionally leaves unresolved questions where the evidence is insufficient.

## 14.1 Backtest canonical package

Current:

```text
scripts/lib/backtest.py
scripts/lib/portfolio_backtest.py
```

Candidate:

```text
scripts/backtest/
```

Alternative:

```text
scripts/quant/
```

Decision required before relocation.

---

## 14.2 `scripts/lib/features.py`

Current evidence indicates no production caller.

Before deletion:

```text
search repository references
→ migrate tests
→ run complete test suite
→ verify no dynamic/import dependency
```

---

## 14.3 `scripts/lib/risk.py`

Some functionality is still substantive rather than purely compatibility.

The canonical ownership of:

```text
normalize_universe_liquidity_scores
```

must be confirmed before deleting the legacy module.

---

## 14.4 `scripts/lib/config.py`

Configuration ownership is currently distributed.

Each constant should be assigned to exactly one canonical subsystem before the compatibility module is removed.

---

## 14.5 External/internal consumers

The repository audit cannot prove whether external private tooling imports internal `scripts.*` modules.

Therefore:

> Internal module paths should be considered repository-internal unless explicitly documented as public API.

Do not preserve legacy paths indefinitely based on an unverified external-consumer assumption.

---

# 15. Architecture Freeze Findings

The following findings are considered established baseline facts for M1–M5:

### Finding 1 — Canonical architecture already exists

The repository has distinct canonical layers:

```text
domain
data
pipeline
quant
performance
monitoring
artifacts
schema
```

The cleanup should consolidate callers into these layers rather than introduce another parallel architecture.

### Finding 2 — `scripts/lib` is not yet removable

Production references remain.

Therefore:

```text
M0: audit
M1: test migration / safe shim cleanup
M2: legacy architecture removal
```

is the correct dependency order.

### Finding 3 — Some legacy modules contain real business logic

In particular:

```text
scripts/lib/backtest.py
scripts/lib/portfolio_backtest.py
scripts/lib/risk.py
scripts/lib/vietnam_market.py
```

must not be treated as disposable wrappers.

### Finding 4 — Test infrastructure is part of the migration

The current custom test runner is still active in CI.

M1 must replace it with pytest rather than deleting it prematurely.

### Finding 5 — Production correctness remains a separate milestone

Architecture cleanup does not prove production `update-data` correctness.

M5 must independently validate a real production run and generated artifacts.

---

# 16. M1–M5 Cleanup Roadmap

The roadmap below follows Issue #222.

```text
M0
Baseline Audit & Freeze
        │
        ▼
M1
pytest Migration
        │
        ▼
M2
Remove Legacy Architecture
        │
        ▼
M3
Documentation Architecture
        │
        ▼
M4
Naming & Code Standards
        │
        ▼
M5
Production update-data Validation
```

---

## M1 — Migrate Tests to pytest

### Goal

Replace the current custom `unittest` infrastructure with pytest.

### Required work

- add `pytest`
- migrate `unittest.TestCase`
- convert `setUp/tearDown` to fixtures
- convert assertions
- introduce parametrization where appropriate
- create `conftest.py`
- migrate network isolation to fixture/plugin mechanism
- introduce markers:

```text
unit
integration
e2e
live
slow
frontend
```

- replace CI command:

```text
python scripts/tests/run_tests.py
```

with:

```text
uv run --frozen pytest
```

### Acceptance

- all tests execute through pytest
- no `unittest.TestCase`
- no custom test runner
- no custom test discovery
- coverage is not intentionally reduced
- no significant runtime regression without justification

---

# 17. M2 — Remove Legacy Architecture

Audit every legacy module individually:

```text
scripts/lib/backtest.py
scripts/lib/config.py
scripts/lib/features.py
scripts/lib/monitoring.py
scripts/lib/portfolio_backtest.py
scripts/lib/recommendation.py
scripts/lib/regime.py
scripts/lib/risk.py
scripts/lib/vietnam_market.py
```

For each module:

```text
Canonical replacement?
        │
   ┌────┴────┐
   │         │
  YES       NO
   │         │
 migrate    KEEP + document
   │
remove legacy path
```

### Acceptance

Repository-wide search should show no unexplained production dependency on:

```text
scripts.lib
```

No compatibility wrapper should remain merely because an old test still imports it.

---

# 18. M3 — Documentation Architecture

Create the architecture documentation defined by Issue #222:

```text
docs/
├── architecture.md
├── coding-standards.md
├── testing.md
├── naming.md
├── data-contracts.md
├── pipeline.md
├── quantitative.md
├── monitoring.md
├── artifacts.md
├── frontend.md
├── ci-cd.md
└── agent-workflow.md
```

`AGENTS.md` should remain concise and link to these documents rather than duplicating them.

---

# 19. M4 — Naming & Code Standards

Establish canonical terminology such as:

```text
Recommendation
Signal
RiskAssessment
TradePlan
Performance
Monitoring
Artifact
Report
DataAsOf
SchemaVersion
PipelineStage
```

Define standards for:

- module names
- classes
- functions
- constants
- private functions
- type aliases
- dataclasses
- exceptions
- test names

Preferred test naming:

```python
def test_history_artifact_rejects_missing_schema_version():
    ...
```

Avoid meaningless historical names such as:

```text
test_23_xxx
test_old_xxx
```

unless the historical distinction is itself part of the behavior.

Comments should explain:

- business invariants
- temporal invariants
- provider constraints
- architecture boundaries
- intentional trade-offs

Avoid comments that merely restate obvious implementation.

---

# 20. M5 — Production `update-data`

M5 is explicitly a **real production validation milestone**, not only a CI cleanup.

The production command is:

```bash
uv run --frozen python scripts/generate_report.py --update
```

The complete production path must be validated:

```text
VNINDEX / required market benchmarks
        +
candidate universe
        ↓
required data acquisition
        ↓
data validation
        ↓
data_as_of
        ↓
quant engines
        ↓
performance
        ↓
monitoring
        ↓
schema validation
        ↓
artifact publishing
        ↓
generated/
```

### Required verification

At minimum:

```text
generated/recommendations.json
generated/market.json
generated/monitoring.json
generated/history/index.json
generated/history/YYYY-MM-DD.json
```

### Production acceptance

A production run is valid only when:

```text
all required symbols processed
        +
correct trading date
        +
latest valid prices
        +
schema valid
        +
monitoring valid
        +
artifacts published
```

The following state is explicitly unacceptable:

```text
CI green
+
report invalid
```

Likewise:

```text
partial universe
→ report published as if complete
```

is not acceptable.

---

# 21. M0 Exit Criteria

M0 is complete when this document provides:

- [ ] architecture inventory
- [ ] production entry points
- [ ] canonical modules
- [ ] legacy modules
- [ ] `scripts.lib` dependency map
- [ ] test → production ownership map
- [ ] generated artifact → producer map
- [ ] compatibility-layer inventory
- [ ] `UNKNOWN` decisions explicitly recorded
- [ ] M1–M5 follow-up work derivable from the inventory
- [ ] no intentional production refactor performed as part of M0

---

# 22. Final Baseline Statement

As of **2026-10-07**, the repository has a substantially established canonical architecture, but legacy compatibility and business logic remain under `scripts/lib`.

The immediate architectural priority is therefore **not** to redesign the system.

It is to:

```text
1. migrate the test infrastructure to pytest
2. remove obsolete compatibility layers
3. migrate remaining legacy production dependencies
4. document the canonical architecture
5. standardize naming and code conventions
6. validate the real production update-data path
```

M0 freezes this baseline.

Any structural change introduced after this point should belong to an explicitly scoped M1–M5 issue/PR and should be evaluated against this inventory.
