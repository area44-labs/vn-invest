"""Individual check functions for production monitoring."""

import json
import os
from datetime import UTC, datetime
from typing import Any

import jsonschema

from scripts.lib.config import VALID_MARKET_REGIMES
from scripts.lib.vietnam_market import validate_ohlcv_data
from scripts.monitoring.metrics import normalize_market_payload
from scripts.monitoring.models import (
    DEFAULT_SCHEMA_PATH,
    VALID_EXCLUSION_CATEGORIES,
    CheckResult,
    find_nan_or_inf,
)


def check_required_artifacts(
    generated_dir: str,
    data_as_of: str | None = None,
    in_memory_artifacts: dict[str, Any] | None = None,
) -> CheckResult:
    """Verify presence and accessibility of required generated JSON artifacts (either in-memory or on disk)."""
    req_rel_paths = [
        "recommendations.json",
        "market.json",
        os.path.join("history", "index.json"),
    ]
    if data_as_of:
        req_rel_paths.append(os.path.join("history", f"{data_as_of}.json"))

    in_mem = in_memory_artifacts or {}
    missing = []
    unreadable = []

    for rel_p in req_rel_paths:
        file_name = os.path.basename(rel_p)
        if rel_p in in_mem or file_name in in_mem:
            data = in_mem.get(rel_p) if rel_p in in_mem else in_mem.get(file_name)
            if not isinstance(data, dict):
                unreadable.append(f"{file_name} (in-memory root is not object)")
        else:
            fpath = os.path.join(generated_dir, rel_p)
            if not os.path.exists(fpath):
                missing.append(file_name)
            else:
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        unreadable.append(f"{file_name} (root is not object)")
                except Exception as e:  # noqa: BLE001
                    unreadable.append(f"{file_name} ({e})")

    if missing or unreadable:
        msgs = []
        if missing:
            msgs.append(f"Missing files: {', '.join(missing)}")
        if unreadable:
            msgs.append(f"Unreadable files: {', '.join(unreadable)}")
        return CheckResult(
            check_name="artifact_existence",
            status="FAIL",
            measured_value={"missing": missing, "unreadable": unreadable},
            expected_condition="All required generated JSON artifacts exist and are valid JSON",
            message="; ".join(msgs),
        )

    found_count = len(req_rel_paths) - len(missing)
    return CheckResult(
        check_name="artifact_existence",
        status="PASS",
        measured_value={"required_count": len(req_rel_paths), "found_count": found_count},
        expected_condition="All required generated JSON artifacts exist and are valid JSON",
        message=f"All {len(req_rel_paths)} required artifacts exist and are readable",
    )


def check_schema_validation(
    recommendations_payload: dict, schema_path: str = DEFAULT_SCHEMA_PATH
) -> CheckResult:
    """Validate recommendations payload against canonical JSON schema using version-aware resolution."""
    if not isinstance(recommendations_payload, dict):
        return CheckResult(
            check_name="schema_validation",
            status="FAIL",
            measured_value={"type": type(recommendations_payload).__name__},
            expected_condition="recommendations_payload is a dict",
            message="Recommendations payload is not a dictionary",
        )

    schema_ver = recommendations_payload.get("schema_version")
    if not schema_ver or not isinstance(schema_ver, str) or not schema_ver.strip():
        return CheckResult(
            check_name="schema_validation",
            status="FAIL",
            measured_value={"schema_version": schema_ver},
            expected_condition="Payload contains non-empty string schema_version",
            message="Recommendations payload is missing required non-empty 'schema_version'",
        )

    try:
        from scripts.schema import SchemaResolutionError, load_schema_for_version

        schema = load_schema_for_version("recommendations", schema_ver.strip())
        jsonschema.validate(instance=recommendations_payload, schema=schema)
        return CheckResult(
            check_name="schema_validation",
            status="PASS",
            measured_value={"schema_version": schema_ver.strip()},
            expected_condition="Payload matches versioned recommendations.schema.json",
            message="Recommendations payload passed JSON schema validation",
        )
    except SchemaResolutionError as err:
        return CheckResult(
            check_name="schema_validation",
            status="FAIL",
            measured_value={"schema_version": schema_ver},
            expected_condition="Payload declares valid supported schema_version",
            message=f"Schema resolution failed: {err}",
        )
    except jsonschema.ValidationError as err:
        return CheckResult(
            check_name="schema_validation",
            status="FAIL",
            measured_value={"error_path": list(err.absolute_path), "failed_keyword": err.validator},
            expected_condition="Payload matches recommendations.schema.json",
            message=f"Schema validation failed at path {list(err.absolute_path)}: {err.message}",
        )
    except Exception as err:  # noqa: BLE001
        return CheckResult(
            check_name="schema_validation",
            status="FAIL",
            measured_value={"error": str(err)},
            expected_condition="Payload matches recommendations.schema.json",
            message=f"Schema validation error: {err}",
        )


def check_data_freshness(data_as_of: str | None, reference_date: str | None = None) -> CheckResult:
    """Check data freshness / latest available date against explicit reference date.

    Fail-closed semantics:
    - Missing data_as_of when expected -> FAIL
    - Malformed date string -> FAIL
    - Future data_as_of relative to reference_date -> FAIL (anti-lookahead protection)
    - Staleness > 14 days -> FAIL
    - Staleness > 3 days -> WARNING
    - Staleness <= 3 days -> PASS
    """
    if not data_as_of:
        return CheckResult(
            check_name="data_freshness",
            status="FAIL",
            measured_value={"data_as_of": None},
            expected_condition="Valid YYYY-MM-DD date string for data_as_of",
            message="data_as_of is missing or None in production payload",
        )

    try:
        data_dt = datetime.strptime(data_as_of, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return CheckResult(
            check_name="data_freshness",
            status="FAIL",
            measured_value={"data_as_of": data_as_of},
            expected_condition="Valid YYYY-MM-DD date string",
            message=f"data_as_of '{data_as_of}' is not a valid YYYY-MM-DD date",
        )

    if reference_date:
        try:
            ref_dt = datetime.strptime(reference_date, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return CheckResult(
                check_name="data_freshness",
                status="FAIL",
                measured_value={"reference_date": reference_date},
                expected_condition="Valid YYYY-MM-DD reference_date string",
                message=f"reference_date '{reference_date}' is not a valid YYYY-MM-DD date",
            )
    else:
        ref_dt = datetime.now(UTC)

    diff_days = (ref_dt.date() - data_dt.date()).days

    if diff_days < 0:
        return CheckResult(
            check_name="data_freshness",
            status="FAIL",
            measured_value={
                "data_as_of": data_as_of,
                "reference_date": ref_dt.strftime("%Y-%m-%d"),
                "future_days": -diff_days,
            },
            expected_condition="data_as_of <= reference_date",
            message=f"data_as_of ({data_as_of}) is in the future relative to reference_date ({ref_dt.strftime('%Y-%m-%d')})",
        )

    if diff_days > 14:
        return CheckResult(
            check_name="data_freshness",
            status="FAIL",
            measured_value={"data_as_of": data_as_of, "staleness_days": diff_days},
            expected_condition="staleness_days <= 14",
            message=f"Data is critically stale ({diff_days} days old relative to reference date)",
        )

    if diff_days > 3:
        return CheckResult(
            check_name="data_freshness",
            status="WARNING",
            measured_value={"data_as_of": data_as_of, "staleness_days": diff_days},
            expected_condition="staleness_days <= 3",
            message=f"Data is slightly stale ({diff_days} days old relative to reference date)",
        )

    return CheckResult(
        check_name="data_freshness",
        status="PASS",
        measured_value={"data_as_of": data_as_of, "staleness_days": diff_days},
        expected_condition="staleness_days <= 3",
        message=f"Data is fresh ({diff_days} days old as of {data_as_of})",
    )


def check_numeric_sanity(payload: dict, market_payload: dict | None = None) -> CheckResult:
    """Scan recommendations payload and market payload for NaN/Inf float values or out-of-bounds scores."""
    nan_inf_issues = find_nan_or_inf(payload, path="recommendations_payload")
    if market_payload:
        nan_inf_issues.extend(find_nan_or_inf(market_payload, path="market_payload"))

    if nan_inf_issues:
        return CheckResult(
            check_name="numeric_sanity",
            status="FAIL",
            measured_value={"nan_inf_issues": nan_inf_issues[:10]},
            expected_condition="No NaN or Inf float values anywhere in recommendations or market payload",
            message=f"Found {len(nan_inf_issues)} NaN/Inf values: {'; '.join(nan_inf_issues[:3])}",
        )

    recs = payload.get("recommendations", [])
    out_of_bounds = []
    for r in recs:
        sym = r.get("symbol", "UNKNOWN")
        act = r.get("action")
        sig_score = r.get("signal_score")
        risk_adj = r.get("risk_adjusted_score")
        conf = r.get("confidence")

        if act != "AVOID":
            if sig_score is not None and not (0.0 <= sig_score <= 100.0):
                out_of_bounds.append(f"{sym}.signal_score={sig_score}")
            if risk_adj is not None and not (0.0 <= risk_adj <= 100.0):
                out_of_bounds.append(f"{sym}.risk_adjusted_score={risk_adj}")
            if conf is not None and not (0.0 <= conf <= 1.0):
                out_of_bounds.append(f"{sym}.confidence={conf}")

    if out_of_bounds:
        return CheckResult(
            check_name="numeric_sanity",
            status="FAIL",
            measured_value={"out_of_bounds": out_of_bounds},
            expected_condition="All scores strictly within allowed bounds [0..100] or [0..1]",
            message=f"Out-of-bounds score values detected: {'; '.join(out_of_bounds[:3])}",
        )

    return CheckResult(
        check_name="numeric_sanity",
        status="PASS",
        measured_value={"scanned_recommendations": len(recs)},
        expected_condition="No NaN/Inf values and scores strictly within allowed numeric bounds",
        message="All numeric values in recommendations payload are valid and within bounds",
    )


def check_symbol_processing_counts(payload: dict) -> CheckResult:
    """Verify symbol processing counts, summary invariants, and coverage ratios.

    Distinguishes:
    - Genuine pipeline failure: sum mismatch, total_scanned mismatch, action mismatch, 0 total scanned, or < 50% processed ratio.
    - Expected insufficient-data condition: individual stock with INSUFFICIENT data_quality (decoupled from AVOID action), processed ratio >= 80%.
    - Warning condition: processed ratio between 50% and 80%.
    """
    recs = payload.get("recommendations", [])
    summary = payload.get("summary", {})

    total_scanned = summary.get("total_scanned", len(recs))
    buy_cnt = summary.get("buy_count", 0)
    watch_cnt = summary.get("watch_count", 0)
    hold_cnt = summary.get("hold_count", 0)
    sell_cnt = summary.get("sell_count", 0)
    avoid_cnt = summary.get("avoid_count", 0)

    sum_actions = buy_cnt + watch_cnt + hold_cnt + sell_cnt + avoid_cnt

    if total_scanned == 0 or len(recs) == 0:
        return CheckResult(
            check_name="symbol_processing_counts",
            status="FAIL",
            measured_value={"total_scanned": total_scanned, "len_recommendations": len(recs)},
            expected_condition="total_scanned > 0 and len(recommendations) > 0",
            message="Zero symbols were processed in recommendations payload",
        )

    if total_scanned != len(recs) or sum_actions != total_scanned:
        return CheckResult(
            check_name="symbol_processing_counts",
            status="FAIL",
            measured_value={
                "total_scanned": total_scanned,
                "len_recs": len(recs),
                "sum_actions": sum_actions,
            },
            expected_condition="summary counts sum to total_scanned and match recommendations length",
            message=f"Summary counts mismatch: total_scanned={total_scanned}, len_recs={len(recs)}, sum_actions={sum_actions}",
        )

    # Compute actual action counts directly from recommendation items
    actual_buy = sum(1 for r in recs if r.get("action") == "BUY")
    actual_watch = sum(1 for r in recs if r.get("action") == "WATCH")
    actual_hold = sum(1 for r in recs if r.get("action") == "HOLD")
    actual_sell = sum(1 for r in recs if r.get("action") == "SELL")
    actual_avoid = sum(1 for r in recs if r.get("action") == "AVOID")

    action_mismatches = []
    if buy_cnt != actual_buy:
        action_mismatches.append(f"buy_count: summary={buy_cnt} vs actual={actual_buy}")
    if watch_cnt != actual_watch:
        action_mismatches.append(f"watch_count: summary={watch_cnt} vs actual={actual_watch}")
    if hold_cnt != actual_hold:
        action_mismatches.append(f"hold_count: summary={hold_cnt} vs actual={actual_hold}")
    if sell_cnt != actual_sell:
        action_mismatches.append(f"sell_count: summary={sell_cnt} vs actual={actual_sell}")
    if avoid_cnt != actual_avoid:
        action_mismatches.append(f"avoid_count: summary={avoid_cnt} vs actual={actual_avoid}")

    if action_mismatches:
        return CheckResult(
            check_name="symbol_processing_counts",
            status="FAIL",
            measured_value={
                "summary": summary,
                "actual_actions": {
                    "BUY": actual_buy,
                    "WATCH": actual_watch,
                    "HOLD": actual_hold,
                    "SELL": actual_sell,
                    "AVOID": actual_avoid,
                },
            },
            expected_condition="summary action counts strictly match actual recommendation actions",
            message=f"Summary action count mismatch: {'; '.join(action_mismatches)}",
        )

    processed_count = sum(1 for r in recs if r.get("data_quality") in ("SUFFICIENT", "PARTIAL"))
    insufficient_count = sum(1 for r in recs if r.get("data_quality") == "INSUFFICIENT")

    processed_ratio = processed_count / total_scanned if total_scanned > 0 else 0.0

    metrics_detail = {
        "total_scanned": total_scanned,
        "processed_count": processed_count,
        "insufficient_count": insufficient_count,
        "processed_ratio": round(processed_ratio, 4),
        "actions": {
            "BUY": buy_cnt,
            "WATCH": watch_cnt,
            "HOLD": hold_cnt,
            "SELL": sell_cnt,
            "AVOID": avoid_cnt,
        },
    }

    if processed_ratio < 0.50:
        return CheckResult(
            check_name="symbol_processing_counts",
            status="FAIL",
            measured_value=metrics_detail,
            expected_condition="processed_ratio >= 0.50",
            message=f"Critical coverage loss: only {processed_count}/{total_scanned} ({processed_ratio:.1%}) symbols successfully processed",
        )

    if processed_ratio < 0.80:
        return CheckResult(
            check_name="symbol_processing_counts",
            status="WARNING",
            measured_value=metrics_detail,
            expected_condition="processed_ratio >= 0.80",
            message=f"Moderate symbol processing warnings: {insufficient_count}/{total_scanned} symbols skipped or had insufficient data",
        )

    return CheckResult(
        check_name="symbol_processing_counts",
        status="PASS",
        measured_value=metrics_detail,
        expected_condition="processed_ratio >= 0.80",
        message=f"Successfully processed {processed_count}/{total_scanned} ({processed_ratio:.1%}) candidate universe symbols",
    )


def check_market_regime_status(market_payload: dict) -> CheckResult:
    """Validate market regime object, validity, confidence, and required metrics."""
    if not isinstance(market_payload, dict):
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value={"type": type(market_payload).__name__},
            expected_condition="market object is a dict",
            message="Market regime payload is not an object",
        )

    norm_market = normalize_market_payload(market_payload)
    market_obj = norm_market.get("market", {})

    regime = market_obj.get("regime")
    conf = market_obj.get("confidence")
    metrics = market_obj.get("metrics")

    if regime not in VALID_MARKET_REGIMES:
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value={"regime": regime},
            expected_condition=f"regime in {sorted(VALID_MARKET_REGIMES)}",
            message=f"Invalid market regime '{regime}'",
        )

    if conf is not None and not (0.0 <= conf <= 1.0):
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value={"confidence": conf},
            expected_condition="0.0 <= confidence <= 1.0",
            message=f"Market regime confidence out of bounds: {conf}",
        )

    if not isinstance(metrics, dict):
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value={"metrics": metrics},
            expected_condition="metrics is a dict",
            message="Market regime metrics object is missing or invalid",
        )

    vn_val = metrics.get("vnindex_value")
    vn_pct = metrics.get("vnindex_change_pct")
    breadth = metrics.get("market_breadth_ratio")

    if vn_val is None or vn_pct is None:
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value=metrics,
            expected_condition="vnindex_value and vnindex_change_pct present in metrics",
            message="Mandatory market regime metrics (vnindex_value/change_pct) are null",
        )

    if breadth is not None and not (0.0 <= breadth <= 1.0):
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value={"market_breadth_ratio": breadth},
            expected_condition="0.0 <= market_breadth_ratio <= 1.0",
            message=f"Market breadth ratio out of bounds: {breadth}",
        )

    return CheckResult(
        check_name="market_regime_status",
        status="PASS",
        measured_value={
            "regime": regime,
            "confidence": conf,
            "vnindex_value": vn_val,
            "market_breadth_ratio": breadth,
        },
        expected_condition="Valid regime, bounded confidence, and valid metrics",
        message=f"Market regime '{regime}' verified successfully",
    )


def check_history_index_status(
    generated_dir: str,
    data_as_of: str | None = None,
    in_memory_artifacts: dict[str, Any] | None = None,
) -> CheckResult:
    """Validate history index (history/index.json) integrity, chronological ordering, and inclusion of data_as_of."""
    in_mem = in_memory_artifacts or {}
    data = None

    if "history/index.json" in in_mem:
        data = in_mem["history/index.json"]
    elif "index.json" in in_mem:
        data = in_mem["index.json"]
    else:
        index_path = os.path.join(generated_dir, "history", "index.json")
        if not os.path.exists(index_path):
            return CheckResult(
                check_name="history_index_status",
                status="FAIL",
                measured_value={"index_path": index_path},
                expected_condition="history/index.json exists",
                message="History index file history/index.json does not exist",
            )

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as err:  # noqa: BLE001
            return CheckResult(
                check_name="history_index_status",
                status="FAIL",
                measured_value={"error": str(err)},
                expected_condition="history/index.json is valid JSON",
                message=f"Failed to read history index JSON: {err}",
            )

    if not isinstance(data, dict) or "dates" not in data:
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"root_type": type(data).__name__},
            expected_condition="Dict root with 'dates' array",
            message="Invalid history index payload structure",
        )

    dates = data.get("dates")
    if not isinstance(dates, list):
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"dates_type": type(dates).__name__},
            expected_condition="'dates' field is a list",
            message="History index 'dates' field is not a list",
        )

    invalid_date_items = []
    for d in dates:
        if not isinstance(d, str):
            invalid_date_items.append(str(d))
        else:
            try:
                datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                invalid_date_items.append(d)

    if invalid_date_items:
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"invalid_items": invalid_date_items},
            expected_condition="All items in dates list are valid canonical YYYY-MM-DD calendar date strings",
            message=f"History index contains invalid date entries: {', '.join(invalid_date_items[:5])}",
        )

    # Check that corresponding history date JSON files exist on disk or in memory
    missing_history_files = []
    for d in dates:
        file_path = os.path.join(generated_dir, "history", f"{d}.json")
        rel_path = os.path.join("history", f"{d}.json")
        file_name = f"{d}.json"
        if not os.path.exists(file_path) and rel_path not in in_mem and file_name not in in_mem:
            missing_history_files.append(f"history/{d}.json")

    if missing_history_files:
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"missing_files": missing_history_files[:10]},
            expected_condition="Every date in history index has a corresponding history/YYYY-MM-DD.json artifact file",
            message=f"History index references missing report files: {', '.join(missing_history_files[:3])}",
        )

    # Check duplicate dates
    if len(dates) != len(set(dates)):
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"total_dates": len(dates), "unique_dates": len(set(dates))},
            expected_condition="No duplicate dates in history index",
            message="History index contains duplicate date entries",
        )

    # Check sorting order (index.json requires reverse chronological order YYYY-MM-DD descending)
    sorted_desc = sorted(dates, reverse=True)
    if dates != sorted_desc:
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"dates_sample": dates[:5]},
            expected_condition="Dates list sorted descending (newest first)",
            message="History index dates are not sorted in descending chronological order",
        )

    if data_as_of and data_as_of not in dates:
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"data_as_of": data_as_of, "dates": dates[:5]},
            expected_condition=f"data_as_of '{data_as_of}' must be present in history/index.json dates list",
            message=f"data_as_of '{data_as_of}' is missing from history/index.json dates",
        )

    return CheckResult(
        check_name="history_index_status",
        status="PASS",
        measured_value={"total_reports": len(dates), "latest_date": dates[0] if dates else None},
        expected_condition="Valid sorted dates list containing data_as_of",
        message=f"History index verified with {len(dates)} historical report entries",
    )


def check_ohlcv_data_quality(df_ohlcv: Any, symbol_name: str) -> CheckResult:
    """Validate clean data boundary quality for an OHLCV dataset using validate_ohlcv_data."""
    val_res = validate_ohlcv_data(df_ohlcv, symbol_name)
    status_raw = val_res.get("status")
    issues = val_res.get("issues", [])

    if status_raw == "INSUFFICIENT":
        return CheckResult(
            check_name=f"ohlcv_quality_{symbol_name.lower()}",
            status="FAIL",
            measured_value={"status": status_raw, "issues": issues},
            expected_condition=f"OHLCV data for {symbol_name} is SUFFICIENT or PARTIAL",
            message=f"OHLCV data quality for '{symbol_name}' is INSUFFICIENT: {', '.join(issues)}",
        )

    if status_raw == "PARTIAL":
        return CheckResult(
            check_name=f"ohlcv_quality_{symbol_name.lower()}",
            status="WARNING",
            measured_value={"status": status_raw, "issues": issues},
            expected_condition=f"OHLCV data for {symbol_name} is SUFFICIENT",
            message=f"OHLCV data quality for '{symbol_name}' has partial warnings: {', '.join(issues)}",
        )

    return CheckResult(
        check_name=f"ohlcv_quality_{symbol_name.lower()}",
        status="PASS",
        measured_value={"status": status_raw, "valid_row_count": val_res.get("valid_row_count")},
        expected_condition=f"OHLCV data for {symbol_name} is SUFFICIENT",
        message=f"OHLCV data quality for '{symbol_name}' is SUFFICIENT ({val_res.get('valid_row_count')} valid rows)",
    )


def check_universe_audit_invariants(
    universe_audit: dict, recommendations_payload: dict
) -> CheckResult:
    """Verify production audit universe invariants, cross-checks, and set consistency."""
    if not isinstance(universe_audit, dict):
        return CheckResult(
            check_name="universe_audit_invariants",
            status="FAIL",
            measured_value={"universe_audit_type": type(universe_audit).__name__},
            expected_condition="universe_audit is a dictionary",
            message="universe_audit is missing or not a dictionary",
        )

    required_keys = [
        "expected_symbols",
        "processed_symbols",
        "invalid_symbols",
        "insufficient_history_symbols",
        "failed_symbols",
        "missing_symbols",
        "counts",
        "exclusions",
    ]
    for k in required_keys:
        if k not in universe_audit:
            return CheckResult(
                check_name="universe_audit_invariants",
                status="FAIL",
                measured_value={"missing_key": k},
                expected_condition=f"universe_audit contains key '{k}'",
                message=f"universe_audit is missing required key '{k}'",
            )

    counts = universe_audit.get("counts", {})
    if not isinstance(counts, dict):
        return CheckResult(
            check_name="universe_audit_invariants",
            status="FAIL",
            measured_value={"counts_type": type(counts).__name__},
            expected_condition="counts is a dictionary",
            message="universe_audit.counts is not a dictionary",
        )

    count_keys = [
        "expected_count",
        "processed_count",
        "invalid_count",
        "insufficient_history_count",
        "failed_count",
        "missing_count",
    ]
    for ck in count_keys:
        val = counts.get(ck)
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            return CheckResult(
                check_name="universe_audit_invariants",
                status="FAIL",
                measured_value={ck: val},
                expected_condition=f"{ck} is non-negative integer",
                message=f"universe_audit.counts.{ck} ({val}) is invalid or negative",
            )

    exp_syms = universe_audit.get("expected_symbols", [])
    proc_syms = universe_audit.get("processed_symbols", [])
    inv_syms = universe_audit.get("invalid_symbols", [])
    insuf_syms = universe_audit.get("insufficient_history_symbols", [])
    fail_syms = universe_audit.get("failed_symbols", [])
    miss_syms = universe_audit.get("missing_symbols", [])

    for name, sym_list, expected_c in [
        ("expected", exp_syms, counts["expected_count"]),
        ("processed", proc_syms, counts["processed_count"]),
        ("invalid", inv_syms, counts["invalid_count"]),
        ("insufficient_history", insuf_syms, counts["insufficient_history_count"]),
        ("failed", fail_syms, counts["failed_count"]),
        ("missing", miss_syms, counts["missing_count"]),
    ]:
        if not isinstance(sym_list, list):
            return CheckResult(
                check_name="universe_audit_invariants",
                status="FAIL",
                measured_value={f"{name}_symbols_type": type(sym_list).__name__},
                expected_condition=f"{name}_symbols is a list",
                message=f"universe_audit.{name}_symbols is not a list",
            )
        if len(sym_list) != expected_c:
            return CheckResult(
                check_name="universe_audit_invariants",
                status="FAIL",
                measured_value={"list_len": len(sym_list), "reported_count": expected_c},
                expected_condition=f"len({name}_symbols) == {name}_count",
                message=f"Count mismatch for {name}: list length {len(sym_list)} != reported count {expected_c}",
            )

    # Universal sum invariant: expected = processed + invalid + insufficient + failed + missing
    sum_calculated = (
        counts["processed_count"]
        + counts["invalid_count"]
        + counts["insufficient_history_count"]
        + counts["failed_count"]
        + counts["missing_count"]
    )
    if counts["expected_count"] != sum_calculated:
        return CheckResult(
            check_name="universe_audit_invariants",
            status="FAIL",
            measured_value={"expected": counts["expected_count"], "sum_parts": sum_calculated},
            expected_condition="expected_count == processed + invalid + insufficient + failed + missing",
            message=f"Audit sum invariant failed: expected ({counts['expected_count']}) != sum of parts ({sum_calculated})",
        )

    # Check set disjointness (single classification per symbol)
    s_proc = set(proc_syms)
    s_inv = set(inv_syms)
    s_insuf = set(insuf_syms)
    s_fail = set(fail_syms)
    s_miss = set(miss_syms)
    s_exp = set(exp_syms)

    parts = [
        ("processed", s_proc),
        ("invalid", s_inv),
        ("insufficient_history", s_insuf),
        ("failed", s_fail),
        ("missing", s_miss),
    ]
    overlap_issues = []
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            name1, set1 = parts[i]
            name2, set2 = parts[j]
            inter = set1 & set2
            if inter:
                overlap_issues.append(f"Overlap between {name1} and {name2}: {sorted(inter)}")

    if overlap_issues:
        return CheckResult(
            check_name="universe_audit_invariants",
            status="FAIL",
            measured_value={"overlap_issues": overlap_issues},
            expected_condition="Every symbol belongs to exactly one final classification set",
            message=f"Duplicate symbol classification detected: {'; '.join(overlap_issues)}",
        )

    union_parts = s_proc | s_inv | s_insuf | s_fail | s_miss
    if union_parts != s_exp:
        diff_missing = s_exp - union_parts
        diff_extra = union_parts - s_exp
        return CheckResult(
            check_name="universe_audit_invariants",
            status="FAIL",
            measured_value={
                "missing_from_parts": sorted(diff_missing),
                "extra_in_parts": sorted(diff_extra),
            },
            expected_condition="Union of parts equals expected_symbols",
            message=f"Classification set union mismatch: missing={sorted(diff_missing)}, extra={sorted(diff_extra)}",
        )

    # Exclusions validation
    exclusions = universe_audit.get("exclusions")
    if not isinstance(exclusions, list):
        return CheckResult(
            check_name="universe_audit_invariants",
            status="FAIL",
            measured_value={"exclusions_type": type(exclusions).__name__},
            expected_condition="exclusions is a list",
            message="universe_audit.exclusions is not a list",
        )

    excluded_symbols_expected = s_inv | s_insuf | s_fail | s_miss
    exclusion_syms_found = set()
    for idx, ex_item in enumerate(exclusions):
        if not isinstance(ex_item, dict):
            return CheckResult(
                check_name="universe_audit_invariants",
                status="FAIL",
                measured_value={"index": idx, "type": type(ex_item).__name__},
                expected_condition="Exclusion item is a dict",
                message=f"Exclusion item at index {idx} is not a dictionary",
            )
        sym = ex_item.get("symbol")
        cat = ex_item.get("category")
        reason = ex_item.get("reason")

        if not sym or not isinstance(sym, str):
            return CheckResult(
                check_name="universe_audit_invariants",
                status="FAIL",
                measured_value={"index": idx, "symbol": sym},
                expected_condition="Exclusion item has non-empty string 'symbol'",
                message=f"Exclusion item at index {idx} missing valid symbol",
            )

        if cat not in VALID_EXCLUSION_CATEGORIES:
            return CheckResult(
                check_name="universe_audit_invariants",
                status="FAIL",
                measured_value={"index": idx, "symbol": sym, "category": cat},
                expected_condition=f"Exclusion category in {sorted(VALID_EXCLUSION_CATEGORIES)}",
                message=f"Exclusion item [{sym}] has invalid category '{cat}'",
            )

        if not reason or not isinstance(reason, str):
            return CheckResult(
                check_name="universe_audit_invariants",
                status="FAIL",
                measured_value={"index": idx, "symbol": sym, "reason": reason},
                expected_condition="Exclusion item has non-empty string 'reason'",
                message=f"Exclusion item [{sym}] missing valid diagnostic reason",
            )

        exclusion_syms_found.add(sym)

    if exclusion_syms_found != excluded_symbols_expected:
        return CheckResult(
            check_name="universe_audit_invariants",
            status="FAIL",
            measured_value={
                "missing_exclusions": sorted(excluded_symbols_expected - exclusion_syms_found),
                "unexpected_exclusions": sorted(exclusion_syms_found - excluded_symbols_expected),
            },
            expected_condition="Exclusions list matches all non-processed excluded symbols 1-to-1",
            message=f"Exclusions coverage mismatch: missing={sorted(excluded_symbols_expected - exclusion_syms_found)}, extra={sorted(exclusion_syms_found - excluded_symbols_expected)}",
        )

    # Cross-check consistency with recommendations payload
    recs = recommendations_payload.get("recommendations", [])
    if isinstance(recs, list):
        for idx, r in enumerate(recs):
            if isinstance(r, dict):
                sym = r.get("symbol")
                dq = r.get("data_quality")
                sig = r.get("signal_score")
                risk_adj = r.get("risk_adjusted_score")

                if dq in ("SUFFICIENT", "PARTIAL"):
                    if sym not in s_proc:
                        return CheckResult(
                            check_name="universe_audit_invariants",
                            status="FAIL",
                            measured_value={"symbol": sym, "data_quality": dq},
                            expected_condition="Symbol with SUFFICIENT/PARTIAL data quality must be in processed_symbols",
                            message=f"Recommendation [{sym}] has data_quality='{dq}' but is not in processed_symbols",
                        )
                elif dq == "INSUFFICIENT":
                    if sym in s_proc:
                        return CheckResult(
                            check_name="universe_audit_invariants",
                            status="FAIL",
                            measured_value={"symbol": sym, "data_quality": dq},
                            expected_condition="Symbol with INSUFFICIENT data quality must NOT be in processed_symbols",
                            message=f"Recommendation [{sym}] has INSUFFICIENT data quality but is marked in processed_symbols",
                        )
                    if sig is not None or risk_adj is not None:
                        return CheckResult(
                            check_name="universe_audit_invariants",
                            status="FAIL",
                            measured_value={
                                "symbol": sym,
                                "signal_score": sig,
                                "risk_adjusted_score": risk_adj,
                            },
                            expected_condition="Failed/insufficient recommendation must have null scores",
                            message=f"Excluded/insufficient symbol [{sym}] has non-null score(s) in recommendations",
                        )

    return CheckResult(
        check_name="universe_audit_invariants",
        status="PASS",
        measured_value={
            "expected_count": counts["expected_count"],
            "processed_count": counts["processed_count"],
            "excluded_count": len(excluded_symbols_expected),
        },
        expected_condition="All audit counts, set disjointness, exclusion reasons, and pipeline state cross-checks pass",
        message=f"Universe audit trail verified: {counts['processed_count']}/{counts['expected_count']} processed, {len(excluded_symbols_expected)} excluded with full invariant cross-checks passing",
    )


__all__ = [
    "check_data_freshness",
    "check_history_index_status",
    "check_market_regime_status",
    "check_numeric_sanity",
    "check_ohlcv_data_quality",
    "check_required_artifacts",
    "check_schema_validation",
    "check_symbol_processing_counts",
    "check_universe_audit_invariants",
]
