"""Payload validation utilities for VN Invest pipeline orchestration."""

import math

import jsonschema

from scripts.lib.backtest import _parse_canonical_date
from scripts.pipeline.constants import PERFORMANCE_SCHEMA_PATH
from scripts.schema import SCHEMA_VERSION, load_schema_for_version


def load_performance_schema(version: str = SCHEMA_VERSION) -> dict:
    """Load performance JSON Schema for a given version (default '2.0')."""
    return load_schema_for_version("performance", version)


def validate_performance_payload(
    performance_data: dict, schema: dict | None = None, version: str | None = None
) -> None:
    """Validate canonical performance object structure and schema.

    Enforces that schema_version declared inside performance_data is the sole authoritative
    version source. Ignores caller-supplied schema or version overrides to prevent registry bypasses.

    Raises jsonschema.ValidationError, TypeError, SchemaResolutionError, or ValueError on validation failure.
    """
    if not isinstance(performance_data, dict):
        raise TypeError(
            f"Performance payload must be a dict, got {type(performance_data).__name__}"
        )

    s_ver = performance_data.get("schema_version")
    if not s_ver or not isinstance(s_ver, str) or not s_ver.strip():
        from scripts.schema import SchemaResolutionError

        raise SchemaResolutionError(
            "Performance payload is missing required non-empty 'schema_version'"
        )

    schema_to_use = load_schema_for_version("performance", s_ver.strip())
    jsonschema.validate(instance=performance_data, schema=schema_to_use)


def load_schema(version: str = SCHEMA_VERSION) -> dict:
    """Load recommendations JSON Schema for a given version (default '2.0')."""
    return load_schema_for_version("recommendations", version)


def find_payload_integrity_issues(payload: dict, schema: dict | None = None) -> list[str]:
    """Audit final report payload for schema compliance, numeric types, NaN/Inf, summary consistency, score ranges, and date consistency."""
    issues = []

    if schema:
        try:
            jsonschema.validate(instance=payload, schema=schema)
        except jsonschema.ValidationError as err:
            path_str = "/".join(str(p) for p in err.path)
            issues.append(f"JSON Schema validation error: {err.message} at path '{path_str}'")
        except (jsonschema.SchemaError, TypeError, ValueError) as err:
            issues.append(f"JSON Schema validation error: {err}")

    def _walk_check(obj, path=""):
        if obj is None:
            return
        loc = path if path else "root"
        obj_type_mod = getattr(type(obj), "__module__", "")
        if obj_type_mod.startswith(("numpy", "pandas")):
            issues.append(f"Non-serializable {type(obj).__name__} scalar/object at {loc}")

        if isinstance(obj, float):
            if math.isnan(obj):
                issues.append(f"NaN floating point value at {loc}")
            elif math.isinf(obj):
                issues.append(f"Infinity floating point value at {loc}")
        elif isinstance(obj, str):
            if obj.lower() in ("nan", "infinity", "-infinity", "inf", "-inf"):
                issues.append(f"Invalid numeric string representation '{obj}' at {loc}")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _walk_check(v, f"{path}.{k}" if path else str(k))
        elif isinstance(obj, (list, tuple)):
            for idx, item in enumerate(obj):
                _walk_check(item, f"{path}[{idx}]")

    _walk_check(payload)

    data_as_of = payload.get("data_as_of")
    source_date = payload.get("source_date")
    generated_at = payload.get("generated_at")

    if "source_date" in payload and data_as_of != source_date:
        issues.append(
            f"Date inconsistency: top-level data_as_of ({data_as_of}) != source_date ({source_date})"
        )

    if data_as_of:
        try:
            _parse_canonical_date(data_as_of)
        except ValueError, TypeError:
            issues.append(
                f"Invalid YYYY-MM-DD date format for top-level data_as_of: '{data_as_of}'"
            )

    if generated_at is not None and (not isinstance(generated_at, str) or not generated_at):
        issues.append("generated_at must be a non-empty string")

    universe_info = payload.get("universe_info")
    if universe_info is not None:
        if not isinstance(universe_info, dict):
            issues.append("universe_info must be an object")
        else:
            u_size = universe_info.get("universe_size")
            if u_size is not None and (not isinstance(u_size, int) or u_size < 0):
                issues.append(f"universe_info.universe_size invalid: {u_size}")

    recs = payload.get("recommendations")
    if isinstance(recs, list):
        summary = payload.get("summary")
        if isinstance(summary, dict):
            actual_counts = {
                "total_scanned": len(recs),
                "buy_count": sum(
                    1 for r in recs if isinstance(r, dict) and r.get("action") == "BUY"
                ),
                "watch_count": sum(
                    1 for r in recs if isinstance(r, dict) and r.get("action") == "WATCH"
                ),
                "hold_count": sum(
                    1 for r in recs if isinstance(r, dict) and r.get("action") == "HOLD"
                ),
                "sell_count": sum(
                    1 for r in recs if isinstance(r, dict) and r.get("action") == "SELL"
                ),
                "avoid_count": sum(
                    1 for r in recs if isinstance(r, dict) and r.get("action") == "AVOID"
                ),
            }
            for k, expected_val in summary.items():
                if k in actual_counts and expected_val != actual_counts[k]:
                    issues.append(
                        f"Summary mismatch for '{k}': summary specifies {expected_val}, "
                        f"but actual recommendation count is {actual_counts[k]}"
                    )

            if universe_info is not None and isinstance(universe_info, dict):
                u_size = universe_info.get("universe_size")
                if u_size is not None and u_size != len(recs):
                    issues.append(
                        f"Universe info size ({u_size}) does not match recommendations count ({len(recs)})"
                    )

        for idx, rec in enumerate(recs):
            if not isinstance(rec, dict):
                issues.append(f"Recommendation item at index {idx} is not a dictionary")
                continue

            sym = rec.get("symbol", f"index_{idx}")
            rec_as_of = rec.get("data_as_of")
            dq = rec.get("data_quality")

            for req_f in ("symbol", "company_name", "exchange", "sector", "action"):
                if rec.get(req_f) is None:
                    issues.append(f"Recommendation [{sym}] required field '{req_f}' cannot be None")

            if data_as_of and rec_as_of and rec_as_of != data_as_of:
                issues.append(
                    f"Recommendation [{sym}] data_as_of ({rec_as_of}) does not match top-level data_as_of ({data_as_of})"
                )

            if dq == "INSUFFICIENT":
                if rec.get("signal_score") is not None:
                    issues.append(
                        f"Recommendation [{sym}] with INSUFFICIENT data quality has non-null signal_score"
                    )
                if rec.get("risk_adjusted_score") is not None:
                    issues.append(
                        f"Recommendation [{sym}] with INSUFFICIENT data quality has non-null risk_adjusted_score"
                    )
                rm = rec.get("risk_metrics")
                if isinstance(rm, dict) and rm.get("liquidity_score") is not None:
                    issues.append(
                        f"Recommendation [{sym}] with INSUFFICIENT data quality has non-null liquidity_score"
                    )

            for sc_key in ("signal_score", "risk_adjusted_score"):
                val = rec.get(sc_key)
                if val is not None and (
                    not isinstance(val, (int, float))
                    or isinstance(val, bool)
                    or not (0.0 <= val <= 100.0)
                ):
                    issues.append(
                        f"Recommendation [{sym}] '{sc_key}' value {val} out of range [0.0, 100.0]"
                    )

            conf = rec.get("confidence")
            if conf is not None and (
                not isinstance(conf, (int, float))
                or isinstance(conf, bool)
                or not (0.0 <= conf <= 1.0)
            ):
                issues.append(
                    f"Recommendation [{sym}] 'confidence' value {conf} out of range [0.0, 1.0]"
                )

            rm = rec.get("risk_metrics")
            if isinstance(rm, dict):
                liq = rm.get("liquidity_score")
                if liq is not None and (
                    not isinstance(liq, (int, float))
                    or isinstance(liq, bool)
                    or not (0.0 <= liq <= 100.0)
                ):
                    issues.append(
                        f"Recommendation [{sym}] 'liquidity_score' value {liq} out of range [0.0, 100.0]"
                    )

            tp = rec.get("trade_plan")
            if isinstance(tp, dict):
                pos = tp.get("position_percent")
                if pos is not None and (
                    not isinstance(pos, (int, float))
                    or isinstance(pos, bool)
                    or not (0.0 <= pos <= 100.0)
                ):
                    issues.append(
                        f"Recommendation [{sym}] 'position_percent' value {pos} out of range [0.0, 100.0]"
                    )

    mkt = payload.get("market")
    if isinstance(mkt, dict):
        m_conf = mkt.get("confidence")
        if m_conf is not None and (
            not isinstance(m_conf, (int, float))
            or isinstance(m_conf, bool)
            or not (0.0 <= m_conf <= 1.0)
        ):
            issues.append(f"Market 'confidence' value {m_conf} out of range [0.0, 1.0]")
        m_score = mkt.get("regime_score")
        if m_score is not None and (
            not isinstance(m_score, (int, float))
            or isinstance(m_score, bool)
            or not (0.0 <= m_score <= 100.0)
        ):
            issues.append(f"Market 'regime_score' value {m_score} out of range [0.0, 100.0]")
        m_metrics = mkt.get("metrics")
        if isinstance(m_metrics, dict):
            mb = m_metrics.get("market_breadth_ratio")
            if mb is not None and (
                not isinstance(mb, (int, float)) or isinstance(mb, bool) or not (0.0 <= mb <= 1.0)
            ):
                issues.append(f"Market breadth ratio {mb} out of range [0.0, 1.0]")

    return issues


def validate_final_payload_integrity(
    payload: dict, schema: dict | None = None, payload_name: str = "payload"
) -> list[dict]:
    """Validate final report payload integrity. Raises ValueError if any integrity check fails."""
    issues = find_payload_integrity_issues(payload, schema)
    if issues:
        diagnostics = [
            {
                "stage": "OUTPUT_VALIDATION",
                "category": "OUTPUT_VALIDATION_FAILURE",
                "payload": payload_name,
                "status": "FAIL",
                "reason": iss,
            }
            for iss in issues
        ]
        err_msg = "\n".join(f"  - [{diag['payload']}] {diag['reason']}" for diag in diagnostics)
        exc = ValueError(
            f"Final payload integrity validation failed with {len(issues)} issue(s) at stage OUTPUT_VALIDATION:\n{err_msg}"
        )
        exc.diagnostics = diagnostics
        raise exc
    return []


__all__ = [
    "PERFORMANCE_SCHEMA_PATH",
    "find_payload_integrity_issues",
    "load_performance_schema",
    "load_schema",
    "validate_final_payload_integrity",
    "validate_performance_payload",
]
