# Data Contracts, Schemas & Validation Boundaries

This document specifies the JSON Schema contracts, domain models, validation boundaries, version semantics, and fail-closed rules enforced across **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Schema Registry & Versioning Architecture

All output artifacts published by the system are governed by versioned JSON Schemas stored under `schemas/v2/`.

### 1.1 Canonical Schema Registry (`scripts/schema/registry.py`)
Schema resolution is explicitly version-aware:
- **Registry Function**: `load_schema_for_version(schema_type, schema_version)` and `resolve_schema(schema_type, schema_version)`.
- **Supported Versions**: Mapped strictly in `SCHEMA_REGISTRY` (e.g. `("recommendations", "2.0") -> schemas/v2/recommendations.schema.json`, `("performance", "2.0") -> schemas/v2/performance.schema.json`).
- **No Direct Disk Reads**: Production code and validation modules load schemas exclusively through `scripts/schema/registry.py`. Direct file reads (`open(...)`) or duplicate top-level schemas are forbidden.
- **Fail-Closed Resolution**: Requesting a missing, empty, malformed, or unsupported `schema_version` raises `SchemaResolutionError` immediately without silent fallback to latest schema.

### 1.2 Four Versioning Metadata Contracts
The system strictly distinguishes between four independent version numbers:

| Version Contract | Example Value | Source Module | Description |
| :--- | :--- | :--- | :--- |
| **`PIPELINE_VERSION`** | `"2.0.0"` | `scripts/pipeline/constants.py` | Pipeline execution runner software version. |
| **`SIGNAL_MODEL_VERSION`** | `"2.0"` | `scripts/quant/config.py` | Quantitative signal scoring formula version. |
| **`QUANT_VERSION`** | `"2.0.0"` | `scripts/quant/config.py` | Quantitative configuration schema version. |
| **`SCHEMA_VERSION`** | `"2.0"` | `scripts/schema/registry.py` | Versioned JSON Schema definition version. |

---

## 2. Validation Boundaries

The pipeline enforces validation at four distinct sequential boundaries:

```text
1. Provider Payload ──► Canonical OHLCV Validation (scripts/data/validation.py)
                             │
2. Stage Context     ──► Universe Completeness Audit (scripts/pipeline/stages.py)
                             │
3. Pipeline Output   ──► Final Payload Integrity Check (scripts/pipeline/validation.py)
                             │
4. Artifact Publish  ──► Publisher Schema & Provenance Lock (scripts/artifacts/publisher.py)
```

### 2.1 Boundary 1: Canonical OHLCV Validation (`scripts/data/validation.py`)
- Function: `validate_ohlcv_data()` and `validate_canonical_market_data()`.
- Rejects datasets that are empty, missing required columns (`date`, `open`, `high`, `low`, `close`, `volume`), contain `NaN`/`Inf` values, exhibit non-positive prices (`<= 0`), negative volumes (`< 0`), invalid price relationships (`high < low`, `high < open/close`, `low > open/close`), duplicate dates, or non-monotonic date ordering.
- Produces clean DataFrames with zero corrupted rows.

### 2.2 Boundary 2: Universe Completeness Audit (`scripts/pipeline/stages.py`)
- Stage: `UniverseValidationStage`.
- Compares expected candidate universe against `processed_symbols`, `invalid_symbols`, `insufficient_history_symbols`, `failed_symbols`, and `missing_symbols`.
- Benchmarks (`VNINDEX`, `VN30`) MUST be in `processed_symbols` with valid data.

### 2.3 Boundary 3: Final Payload Integrity (`scripts/pipeline/validation.py`)
- Function: `validate_final_payload_integrity()`.
- Verifies that recommendation payloads contain required top-level metadata (`pipeline_version`, `signal_model_version`, `schema_version`, `data_as_of`, `generated_at`), that recommendations list is non-empty, and that numeric fields are non-NaN/finite.

### 2.4 Boundary 4: Publisher Schema & Provenance Lock (`scripts/artifacts/publisher.py`)
- Method: `ArtifactPublisher.publish()` and `validate_artifact()`.
- Validates all schema-governed artifacts (`recommendations.json`, `performance.json`, `history/YYYY-MM-DD.json`) against their declared JSON Schema and provenance manifest (`provenance.json`) prior to acquiring transaction locks.

---

## 3. Date & `data_as_of` Rules

- **Source of Truth**: `data_as_of` is derived strictly from the clean, validated `VNINDEX` trading session date string (`YYYY-MM-DD`).
- **Calendar vs Trading Days**: Non-trading days (weekends, holidays) are excluded. Temporal checks measure elapsed trading sessions rather than calendar days.
- **No Future Dates**: Market data with dates greater than the current execution reference date or future benchmark data relative to execution date are rejected by `validate_temporal_integrity()`.
- **Staleness Threshold**: Stock data older than `MAX_STOCK_STALENESS_DAYS = 7` relative to `data_as_of` is flagged and excluded from processed market breadth.

---

## 4. Fail-Closed Principles

1. **No Silent Defaults**: Missing schema versions, invalid data tags, or schema validation failures halt pipeline publishing immediately.
2. **No Data Fabrication**: If market data for a symbol is insufficient (e.g. fewer than 20 rows of OHLCV history), `liquidity_score` and `risk_adjusted_score` are set to `None`, and the symbol is classified as `INSUFFICIENT_HISTORICAL_DATA`.
3. **Artifact Protection**: In update mode (`--update`), any unrecoverable provider failure, rate limit error, or validation failure raises `RuntimeError`, preserving existing report artifacts on disk untouched.
