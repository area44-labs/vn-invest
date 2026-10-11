# Subsystem Architecture & Canonical Boundaries

This document specifies the system package boundaries, package hierarchy, end-to-end data flow, entry points, and architectural rules for **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Purpose & When to Consult

Consult this document when adding new packages, designing cross-layer features, tracing data flow, or checking architectural boundaries and responsibilities.

---

## 2. Shared End-to-End System Flow

The end-to-end flow connects backend market acquisition to frontend visualization:

$$\text{Market Data} \longrightarrow \text{Backend Validation \& Quant} \longrightarrow \text{JSON Artifacts (`generated/`)} \longrightarrow \text{Frontend Loaders (`loader.ts`)} \longrightarrow \text{UI}$$

```text
┌─────────────────────────────────────────────────────────────┐
│                 Python Quantitative Backend                 │
│                         (scripts/)                          │
│ Market Data -> Canonical Validation -> Indicators & Signals │
│     -> T+2.5 Risk Models -> Monitoring -> Schema Check      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               │ Schema-Validated Static Artifacts
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      Artifact Contract                      │
│                        (generated/)                         │
│ recommendations.json / market.json / monitoring.json / ...  │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               │ SSG Build (Vite+ Prerender)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      React SSG Frontend                     │
│                           (src/)                            │
│     TanStack Start -> Typed Loaders -> Visual UI            │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Package Structure & Hierarchy (`scripts/`)

Backend logic is organized into 9 specialized Python packages under `scripts/`:

```text
scripts/
├── domain/          # Immutable frozen domain contracts, models, and universe definitions
├── data/            # Market data acquisition, normalization, and canonical validation
├── quant/           # Pure quantitative engines, indicator features, signals, and T+2.5 risk
├── pipeline/        # Stage-based orchestration runner and context
├── backtest/        # PIT backtesting, cost models, and portfolio evaluation
├── performance/     # Runtime timing, provider metrics, and budget checks
├── monitoring/      # Operational quality checks, schema validation, and drift evaluation
├── artifacts/       # Atomic publishing, POSIX locks, transactions, and provenance
└── schema/          # Centralized version-aware schema registry (resolving schemas/v2/)
```

### Dependency Flow Constraint

$$\text{domain} \longrightarrow \text{data} / \text{quant} \longrightarrow \text{pipeline} / \text{backtest} \longrightarrow \text{performance} / \text{monitoring} / \text{artifacts}$$

- **`scripts/domain`**: Zero internal dependencies. Contains immutable domain models (`UniverseCandidate`, `Recommendation`, `OHLCVData`).
- **`scripts/data` & `scripts/quant`**: Depend on `domain`. Contain pure data adapters and calculation engines without file I/O.
- **`scripts/pipeline`**: Orchestrates stages across `data`, `quant`, `performance`, `monitoring`, and `artifacts`.
- **`scripts/artifacts`**: Manages POSIX locking and file transaction rollbacks. Zero top-level import dependency on `pipeline`.

---

## 4. Subsystem Responsibilities & Cross-Layer Rules

### 4.1 Subsystem Boundaries

- **Backend (`scripts/`)**: Owns market acquisition, financial calculations, technical indicators, T+2.5 risk modeling, backtesting, monitoring checks, and schema validation.
- **Artifact Interface (`generated/`)**: Single canonical interface between backend and frontend.
- **Frontend (`src/`)**: Read-only static visualizer. Renders pages using pre-rendered JSON payloads. **Zero financial or quantitative calculations occur in the frontend.**

### 4.2 Cross-Layer Changes & Backward Compatibility

When modifying payload structures or introducing new fields:

1. Trace the change from backend producer (`scripts/pipeline/stages.py` / `scripts/quant/`) to schema validator (`schemas/v2/*.schema.json`).
2. Update frontend TypeScript interfaces (`src/types/`) and typed data loader guards (`src/data/loader.ts`).
3. Update UI presentation components (`src/components/`).
4. Ensure relevant backend pytest tests (`scripts/tests/`) and frontend Vitest tests (`src/tests/`) pass before publishing.
