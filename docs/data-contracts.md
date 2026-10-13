# Data Contracts, Schemas & Validation Boundaries

Schema-governed JSON artifacts published by **VN Invest** (`recommendations.json`, `performance.json`, and point-in-time historical snapshots `history/YYYY-MM-DD.json`) are governed by Draft 2020-12 JSON Schemas stored in `schemas/v2/` via `scripts/schema/registry.py`. Other published artifacts (`market.json`, `monitoring.json`, `provenance.json`, `history/index.json`) validate against artifact-specific internal payload contracts.

---

## 1. Version-Aware Schema Registry (`scripts/schema/registry.py`)

Schema loading and resolution are strictly version-aware:

- **Registry Interface**: `resolve_schema(schema_type, schema_version)` and `load_schema_for_version(...)`.
- **Registry Mapping**: Maps `("recommendations", "2.0") -> schemas/v2/recommendations.schema.json` and `("performance", "2.0") -> schemas/v2/performance.schema.json`.
- **Fail-Closed Resolution**: Requesting an unregistered or missing `schema_version` raises `SchemaResolutionError` immediately.

### Four Metadata Version Contracts

| Version Contract                     | Source Module                   | Purpose                                                                             |
| :----------------------------------- | :------------------------------ | :---------------------------------------------------------------------------------- |
| **`PIPELINE_VERSION`** (`"2.0.0"`)   | `scripts/pipeline/constants.py` | Pipeline execution runner software version.                                         |
| **`SIGNAL_MODEL_VERSION`** (`"2.0"`) | `scripts/quant/signal.py`       | Quantitative signal scoring formula version (`DEFAULT_QUANT_CONFIG.model_version`). |
| **`QUANT_VERSION`** (`"1.0.0"`)      | `scripts/quant/config.py`       | Quantitative configuration schema version (`DEFAULT_QUANT_CONFIG.quant_version`).   |
| **`SCHEMA_VERSION`** (`"2.0"`)       | `scripts/schema/registry.py`    | Versioned JSON Schema definition version.                                           |

---

## 2. Four Sequential Validation Boundaries

```text
1. Provider Data   -> Canonical OHLCV Check (scripts/data/validation.py)
2. Stage Context   -> Universe Completeness Audit (scripts/pipeline/stages.py)
3. Pipeline Output -> Final Payload Integrity (scripts/pipeline/validation.py)
4. Publication     -> Publisher Schema & Provenance Lock (scripts/artifacts/publisher.py)
```

1. **Boundary 1 (Canonical OHLCV)**: Rejects datasets with missing columns, non-positive prices, negative volumes, non-monotonic dates, or duplicate trading sessions.
2. **Boundary 2 (Universe Completeness)**: Rejects pipeline runs with missing benchmarks (`VNINDEX`, `VN30`) or unhandled candidate stocks.
3. **Boundary 3 (Final Payload Integrity)**: Ensures recommendations list is non-empty, top-level metadata matches, and numeric fields contain no `NaN`/`Inf`.
4. **Boundary 4 (Publisher Validation)**: Validates schema-governed artifacts against their registered JSON Schemas and applies the relevant internal payload, date-consistency, and provenance checks before atomic persistence.

---

## 3. Date Integrity & Fail-Closed Rules

- **`data_as_of`**: Canonical point-in-time trading session date (`YYYY-MM-DD`) derived strictly from clean `VNINDEX` market data.
- **Fail-Closed Protection**: In update mode (`--update`), any unrecoverable provider failure, rate limit error, or schema mismatch raises `RuntimeError`, preserving on-disk artifacts in `generated/` untouched.
