# Data Contracts, Schemas & Validation Boundaries

This document specifies the JSON Schema contracts, validation boundaries, version semantics, and fail-closed rules enforced in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Purpose & When to Consult

Consult this document when modifying JSON payload structures, adding fields to recommendations or market summaries, updating `schemas/v2/`, or debugging schema validation failures.

---

## 2. Version-Aware Schema Registry (`scripts/schema/registry.py`)

All published payloads in `generated/` are governed by versioned JSON Schemas stored in `schemas/v2/`.

- **Registry Interface**: `resolve_schema(schema_type, schema_version)` and `load_schema_for_version(...)`.
- **Registry Mapping**: Maps `("recommendations", "2.0") -> schemas/v2/recommendations.schema.json` and `("performance", "2.0") -> schemas/v2/performance.schema.json`.
- **Fail-Closed Resolution**: Requesting an unregistered or missing `schema_version` raises `SchemaResolutionError` immediately.

### Four Metadata Version Contracts

| Version Contract                     | Source Module                   | Purpose                                      |
| :----------------------------------- | :------------------------------ | :------------------------------------------- |
| **`PIPELINE_VERSION`** (`"2.0.0"`)   | `scripts/pipeline/constants.py` | Pipeline execution runner software version.  |
| **`SIGNAL_MODEL_VERSION`** (`"2.0"`) | `scripts/quant/config.py`       | Quantitative signal scoring formula version. |
| **`QUANT_VERSION`** (`"2.0.0"`)      | `scripts/quant/config.py`       | Quantitative configuration schema version.   |
| **`SCHEMA_VERSION`** (`"2.0"`)       | `scripts/schema/registry.py`    | Versioned JSON Schema definition version.    |

---

## 3. Four Sequential Validation Boundaries

```text
1. Provider Data  ──► Canonical OHLCV Check (scripts/data/validation.py)
                           │
2. Stage Context  ──► Universe Completeness Audit (scripts/pipeline/stages.py)
                           │
3. Pipeline Output──► Final Payload Integrity (scripts/pipeline/validation.py)
                           │
4. Publication    ──► Publisher Schema & Provenance Lock (scripts/artifacts/publisher.py)
```

1. **Boundary 1 (Canonical OHLCV)**: Rejects datasets with missing columns, non-positive prices, negative volumes, non-monotonic dates, or duplicate trading sessions.
2. **Boundary 2 (Universe Completeness)**: Rejects pipeline runs with missing benchmarks (`VNINDEX`, `VN30`) or unhandled candidate stocks.
3. **Boundary 3 (Final Payload Integrity)**: Ensures recommendations list is non-empty, top-level metadata matches, and numeric fields contain no `NaN`/`Inf`.
4. **Boundary 4 (Publisher Schema Validation)**: Validates generated JSON files against JSON Schemas in `schemas/v2/` prior to atomic persistence.

---

## 4. Date Integrity & Fail-Closed Rules

- **`data_as_of`**: Canonical point-in-time trading session date (`YYYY-MM-DD`) derived strictly from clean `VNINDEX` market data.
- **Fail-Closed Protection**: In update mode (`--update`), any unrecoverable provider failure, rate limit error, or schema mismatch raises `RuntimeError`, preserving on-disk artifacts in `generated/` untouched.
