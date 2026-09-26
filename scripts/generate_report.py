"""Generate Report Script for VN Invest v2.

Command line usage:
    python scripts/generate_report.py
    python scripts/generate_report.py --update
    python scripts/generate_report.py --as-of 2025-01-20 --universe-snapshot history/snapshot.json --historical-ohlcv data/

Outputs:
    generated/recommendations.json
    generated/market.json
    generated/history/index.json
    generated/history/YYYY-MM-DD.json
"""

import argparse
import copy
import json
import logging
import math
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import jsonschema
import pandas as pd

from scripts.data_provider import (
    ProviderRateLimitError,
    VnstockDataProvider,
    aggregate_provider_performance,
    detect_duplicate_operations,
)
from scripts.lib.backtest import _parse_canonical_date, get_as_of_dataset
from scripts.lib.config import DEFAULT_UPDATE_THROTTLE_DELAY, is_recoverable_category
from scripts.lib.monitoring import evaluate_production_monitoring
from scripts.lib.recommendation import SIGNAL_MODEL_VERSION, generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.risk import normalize_universe_liquidity_scores
from scripts.lib.vietnam_market import (
    UniverseProvider,
    get_clean_ohlcv_data,
    get_historical_data,
    validate_temporal_integrity,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "recommendations.schema.json")
PERFORMANCE_SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "performance.schema.json")
GENERATED_DIR = os.path.join(ROOT_DIR, "generated")


def load_performance_schema() -> dict:
    """Load JSON Schema Draft 2020-12 from schemas/performance.schema.json."""
    if not os.path.exists(PERFORMANCE_SCHEMA_PATH):
        raise FileNotFoundError(f"Performance schema file not found at '{PERFORMANCE_SCHEMA_PATH}'")
    with open(PERFORMANCE_SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_performance_payload(performance_data: dict, schema: dict | None = None) -> None:
    """Validate canonical performance object structure and schema.

    Raises jsonschema.ValidationError, TypeError, FileNotFoundError, or ValueError on validation failure.
    """
    if not isinstance(performance_data, dict):
        raise TypeError(
            f"Performance payload must be a dict, got {type(performance_data).__name__}"
        )

    if schema is None:
        schema = load_performance_schema()

    jsonschema.validate(instance=performance_data, schema=schema)


def save_json_files(relative_path: str, data: dict):
    """Save JSON data atomically to generated/."""
    p = os.path.join(GENERATED_DIR, relative_path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp_p = f"{p}.tmp"
    with open(tmp_p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_p, p)


def publish_artifacts_atomically(artifacts: dict[str, dict], target_dir: str | None = None) -> None:
    """Publish multiple JSON artifacts atomically to target_dir.

    `artifacts` is a mapping from relative path (e.g. 'recommendations.json', 'history/2026-03-31.json')
    to dictionary payload data.

    All payloads are written to temporary files (.tmp) first. Once all temporary files are written
    and flushed successfully, they are moved to their target destinations via atomic `os.replace`.
    If writing any temporary file fails, all staging temp files are cleaned up and no target files are overwritten.
    """
    if target_dir is None:
        target_dir = GENERATED_DIR

    tmp_map: list[tuple[str, str]] = []  # (tmp_path, target_path)
    try:
        for rel_path, data in artifacts.items():
            target_path = os.path.join(target_dir, rel_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            tmp_path = f"{target_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            tmp_map.append((tmp_path, target_path))

        # Atomic commit stage: replace all target files
        for tmp_path, target_path in tmp_map:
            os.replace(tmp_path, target_path)
    except Exception as exc:
        logger.error(
            "Atomic artifact publishing failed during write/commit: stage=ARTIFACT_WRITE artifact=ALL operation=publish category=OUTPUT_VALIDATION_FAILURE reason=%s",
            exc,
        )
        # Cleanup temporary files
        for tmp_path, _ in tmp_map:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        raise


def load_schema():
    """Load JSON Schema Draft 2020-12 from schemas/recommendations.schema.json."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def find_payload_integrity_issues(payload: dict, schema: dict | None = None) -> list[str]:
    """Audit final report payload for schema compliance, numeric types, NaN/Inf, summary consistency, score ranges, and date consistency."""
    issues = []

    # 1. JSON Schema validation
    if schema:
        try:
            jsonschema.validate(instance=payload, schema=schema)
        except jsonschema.ValidationError as err:
            path_str = "/".join(str(p) for p in err.path)
            issues.append(f"JSON Schema validation error: {err.message} at path '{path_str}'")
        except (jsonschema.SchemaError, TypeError, ValueError) as err:
            issues.append(f"JSON Schema validation error: {err}")

    # Helper recursive walker for type, NaN/Inf, non-serializable objects, and string representations
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

    # 2. Date and metadata consistency checks
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

    # 3. Recommendations & Summary verification
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

            # Check required core fields
            for req_f in ("symbol", "company_name", "exchange", "sector", "action"):
                if rec.get(req_f) is None:
                    issues.append(f"Recommendation [{sym}] required field '{req_f}' cannot be None")

            if data_as_of and rec_as_of and rec_as_of != data_as_of:
                issues.append(
                    f"Recommendation [{sym}] data_as_of ({rec_as_of}) does not match top-level data_as_of ({data_as_of})"
                )

            # Insufficient data quality invariant checks
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

            # Score & Metric range validation
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

    # 4. Market object validation
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


class PerformanceTracker:
    """Deterministic structured performance timer and diagnostics collector."""

    def __init__(self):
        self.t_pipeline_start = time.perf_counter()
        self.stages: list[dict[str, Any]] = []
        self.symbol_requests: dict[str, int] = {}

    def record_request(self, symbol: str) -> None:
        if symbol:
            sym_u = str(symbol).strip().upper()
            self.symbol_requests[sym_u] = self.symbol_requests.get(sym_u, 0) + 1

    def record_stage(
        self, stage: str, elapsed_seconds: float, status: str = "SUCCESS"
    ) -> dict[str, Any]:
        record = {
            "stage": stage,
            "elapsed_seconds": round(max(0.0, elapsed_seconds), 4),
            "status": status,
        }
        self.stages.append(record)
        return record

    @contextmanager
    def measure_stage(self, stage: str):
        t0 = time.perf_counter()
        status = "SUCCESS"
        try:
            yield
        except Exception:
            status = "FAILED"
            raise
        finally:
            elapsed = time.perf_counter() - t0
            self.record_stage(stage, elapsed, status)

    def get_performance_payload(
        self,
        pipeline_elapsed: float | None = None,
        pipeline_status: str = "SUCCESS",
        call_history: list[dict] | None = None,
    ) -> dict[str, Any]:
        if call_history is None:
            call_history = VnstockDataProvider.get_global_call_history()

        provider_summary = aggregate_provider_performance(call_history)
        duplicates = detect_duplicate_operations(call_history, self.symbol_requests)

        stages_list = []
        if pipeline_elapsed is not None:
            stages_list.append(
                {
                    "stage": "pipeline",
                    "elapsed_seconds": round(max(0.0, pipeline_elapsed), 4),
                    "status": pipeline_status,
                }
            )

        stages_list.extend(self.stages)

        payload = {
            "stages": stages_list,
            "provider": provider_summary,
            "duplicate_operations": duplicates,
        }

        validate_performance_payload(payload)
        return payload


def build_universe_audit(
    expected_symbols: set[str] | list[str],
    processed_symbols: set[str] | list[str],
    invalid_symbols: set[str] | list[str],
    insufficient_history_symbols: set[str] | list[str],
    failed_symbols: set[str] | list[str],
    missing_symbols: set[str] | list[str],
    exclusions_map: dict[str, dict[str, Any]],
    update_data: bool = False,
    performance_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic production universe_audit dictionary from pipeline sets and exclusions map."""
    s_expected = set(expected_symbols)
    s_processed = set(processed_symbols)
    s_invalid = set(invalid_symbols)
    s_insufficient = set(insufficient_history_symbols)
    s_failed = set(failed_symbols)
    s_missing = set(missing_symbols)

    failed_stage = None
    if "VNINDEX" in s_failed or "VN30" in s_failed:
        failed_stage = "BENCHMARK_FETCH"
    elif any(e.get("stage") == "TEMPORAL_VALIDATION" for e in exclusions_map.values()):
        failed_stage = "TEMPORAL_VALIDATION"
    elif any(e.get("stage") == "STOCK_FETCH" for e in exclusions_map.values()):
        failed_stage = "STOCK_FETCH"
    elif s_missing:
        failed_stage = "UNIVERSE_DISCOVERY"

    pipeline_status = "SUCCESS"
    if failed_stage is not None:
        pipeline_status = "FAILED" if update_data else "DEGRADED"

    diagnostics_list = [exclusions_map[s] for s in sorted(exclusions_map.keys())]

    universe_summary = {
        "status": pipeline_status,
        "failed_stage": failed_stage,
        "expected_count": len(s_expected),
        "processed_count": len(s_processed),
        "invalid_count": len(s_invalid),
        "insufficient_history_count": len(s_insufficient),
        "failed_count": len(s_failed),
        "missing_count": len(s_missing),
        "diagnostic_count": len(diagnostics_list),
    }

    audit = {
        "status": pipeline_status,
        "failed_stage": failed_stage,
        "expected_symbols": sorted(s_expected),
        "processed_symbols": sorted(s_processed),
        "invalid_symbols": sorted(s_invalid),
        "insufficient_history_symbols": sorted(s_insufficient),
        "failed_symbols": sorted(s_failed),
        "missing_symbols": sorted(s_missing),
        "counts": universe_summary,
        "summary": universe_summary,
        "exclusions": diagnostics_list,
        "diagnostics": diagnostics_list,
    }

    if performance_data is not None:
        validate_performance_payload(performance_data)
        audit["performance"] = performance_data

    return audit


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


class PipelineResult(tuple):
    """Pipeline result tuple preserving 3-element unpacking backward compatibility."""

    def __new__(
        cls,
        recs_data: dict,
        market_data: dict,
        history_data: dict,
        df_vnindex: Any = None,
        df_vn30: Any = None,
        universe_audit: dict | None = None,
    ):
        obj = super().__new__(cls, (recs_data, market_data, history_data))
        obj.df_vnindex = df_vnindex
        obj.df_vn30 = df_vn30
        obj.universe_audit = universe_audit
        return obj


def run_pipeline(
    update_data: bool = False, tracker: PerformanceTracker | None = None
) -> tuple[dict, dict, dict]:
    """Execute market data pipeline following strict dependency order:

    1. Fetch VN-Index benchmark & stock universe EOD history
    2. Calculate Market Breadth across universe
    3. Calculate Final Market Regime
    4. Generate Stock Recommendations using the Final Market Regime
    5. Compute Universe Percentile Liquidity Scores
    """
    if tracker is None:
        tracker = PerformanceTracker()

    VnstockDataProvider.reset_global_call_history()
    t_pipeline_start = time.perf_counter()
    pipeline_status = "SUCCESS"

    generated_at = datetime.now(UTC).isoformat()
    use_cache = not update_data

    try:
        provider = UniverseProvider()
        raw_candidate_stocks = provider.candidates
        universe_info = provider.get_info()

        if not raw_candidate_stocks:
            raise RuntimeError(
                "Candidate universe is empty. Cannot generate report on empty universe."
            )

        # 1. Normalize and deduplicate candidate stock symbols first
        unique_candidate_stocks = []
        seen_candidate_syms = set()
        for item in raw_candidate_stocks:
            if isinstance(item, dict) and item.get("symbol"):
                sym_u = str(item["symbol"]).strip().upper()
                if sym_u and sym_u not in seen_candidate_syms:
                    seen_candidate_syms.add(sym_u)
                    item_copy = dict(item)
                    item_copy["symbol"] = sym_u
                    unique_candidate_stocks.append(item_copy)

        candidate_stocks = unique_candidate_stocks

        if not candidate_stocks:
            raise RuntimeError("Candidate universe contains no valid symbols.")

        # 2. Derive expected_symbols strictly from the normalized/deduplicated candidate universe + mandatory benchmarks
        expected_symbols = {"VNINDEX", "VN30"} | {item["symbol"] for item in candidate_stocks}

        throttle = DEFAULT_UPDATE_THROTTLE_DELAY if update_data else 0.0
        processed_symbols = set()
        invalid_symbols = set()
        insufficient_history_symbols = set()
        failed_symbols = set()
        exclusions_map = {}

        logger.info("Step 1: Fetching VN-Index benchmark & stock universe EOD history...")

        with tracker.measure_stage("benchmark_fetch"):
            tracker.record_request("VNINDEX")
            try:
                df_vnindex_raw, vn_source, _vn_warns = get_historical_data(
                    "VNINDEX",
                    max_retries=2 if update_data else 1,
                    use_cache_only=use_cache,
                    throttle_delay=throttle,
                )
                df_vnindex_clean, vnindex_val = get_clean_ohlcv_data(df_vnindex_raw, "VNINDEX")

                if (
                    vn_source
                    in (
                        "PROVIDER_FAILURE",
                        "PROVIDER_ERROR",
                        "EXPLICITLY_INVALID",
                        "INVALID_SYMBOL",
                        "INSUFFICIENT_HISTORICAL_DATA",
                    )
                    or df_vnindex_clean.empty
                    or vnindex_val.get("status") == "INSUFFICIENT"
                ):
                    failed_symbols.add("VNINDEX")
                    cat = (
                        "INSUFFICIENT_HISTORICAL_DATA"
                        if (
                            vn_source == "INSUFFICIENT_HISTORICAL_DATA"
                            or vnindex_val.get("status") == "INSUFFICIENT"
                        )
                        else "PROVIDER_FAILURE"
                    )
                    exclusions_map["VNINDEX"] = {
                        "symbol": "VNINDEX",
                        "stage": "BENCHMARK_FETCH",
                        "category": cat,
                        "status": "FAILED",
                        "reason": f"Benchmark VNINDEX check failed (source={vn_source}, status={vnindex_val.get('status')})",
                        "latest_date": vnindex_val.get("latest_date"),
                        "expected_date": None,
                        "processed": False,
                        "recoverable": is_recoverable_category(cat),
                    }
                else:
                    processed_symbols.add("VNINDEX")
            except ProviderRateLimitError:
                failed_symbols.add("VNINDEX")
                exclusions_map["VNINDEX"] = {
                    "symbol": "VNINDEX",
                    "stage": "BENCHMARK_FETCH",
                    "category": "RATE_LIMIT",
                    "status": "FAILED",
                    "reason": "Provider rate limit encountered fetching VNINDEX",
                    "latest_date": None,
                    "expected_date": None,
                    "processed": False,
                    "recoverable": is_recoverable_category("RATE_LIMIT"),
                }
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("Exception fetching VNINDEX: %s", exc)
                failed_symbols.add("VNINDEX")
                exclusions_map["VNINDEX"] = {
                    "symbol": "VNINDEX",
                    "stage": "BENCHMARK_FETCH",
                    "category": "PROVIDER_FAILURE",
                    "status": "FAILED",
                    "reason": f"Exception fetching VNINDEX: {type(exc).__name__}",
                    "latest_date": None,
                    "expected_date": None,
                    "processed": False,
                    "recoverable": is_recoverable_category("PROVIDER_FAILURE"),
                }
                df_vnindex_raw = pd.DataFrame()
                df_vnindex_clean, vnindex_val = get_clean_ohlcv_data(df_vnindex_raw, "VNINDEX")

            # Market-level data_as_of is derived strictly from validated VN-Index benchmark OHLCV dataset.
            data_as_of = vnindex_val.get("latest_date")
            source_date = data_as_of  # Backward compatibility alias
            data_source = vn_source if not df_vnindex_clean.empty else None

            tracker.record_request("VN30")
            try:
                df_vn30_raw, vn30_source, _ = get_historical_data(
                    "VN30",
                    max_retries=2 if update_data else 1,
                    use_cache_only=use_cache,
                    throttle_delay=throttle,
                )
                df_vn30_clean, vn30_val = get_clean_ohlcv_data(df_vn30_raw, "VN30")

                if (
                    vn30_source
                    in (
                        "PROVIDER_FAILURE",
                        "PROVIDER_ERROR",
                        "EXPLICITLY_INVALID",
                        "INVALID_SYMBOL",
                        "INSUFFICIENT_HISTORICAL_DATA",
                    )
                    or df_vn30_clean.empty
                    or vn30_val.get("status") == "INSUFFICIENT"
                ):
                    failed_symbols.add("VN30")
                    cat = (
                        "INSUFFICIENT_HISTORICAL_DATA"
                        if (
                            vn30_source == "INSUFFICIENT_HISTORICAL_DATA"
                            or vn30_val.get("status") == "INSUFFICIENT"
                        )
                        else "PROVIDER_FAILURE"
                    )
                    exclusions_map["VN30"] = {
                        "symbol": "VN30",
                        "stage": "BENCHMARK_FETCH",
                        "category": cat,
                        "status": "FAILED",
                        "reason": f"Benchmark VN30 check failed (source={vn30_source}, status={vn30_val.get('status')})",
                        "latest_date": vn30_val.get("latest_date"),
                        "expected_date": data_as_of,
                        "processed": False,
                        "recoverable": is_recoverable_category(cat),
                    }
                else:
                    processed_symbols.add("VN30")
            except ProviderRateLimitError:
                failed_symbols.add("VN30")
                exclusions_map["VN30"] = {
                    "symbol": "VN30",
                    "stage": "BENCHMARK_FETCH",
                    "category": "RATE_LIMIT",
                    "status": "FAILED",
                    "reason": "Provider rate limit encountered fetching VN30",
                    "latest_date": None,
                    "expected_date": data_as_of,
                    "processed": False,
                    "recoverable": is_recoverable_category("RATE_LIMIT"),
                }
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("Exception fetching VN30: %s", exc)
                failed_symbols.add("VN30")
                exclusions_map["VN30"] = {
                    "symbol": "VN30",
                    "stage": "BENCHMARK_FETCH",
                    "category": "PROVIDER_FAILURE",
                    "status": "FAILED",
                    "reason": f"Exception fetching VN30: {type(exc).__name__}",
                    "latest_date": None,
                    "expected_date": data_as_of,
                    "processed": False,
                    "recoverable": is_recoverable_category("PROVIDER_FAILURE"),
                }
                df_vn30_raw = pd.DataFrame()
                df_vn30_clean, vn30_val = get_clean_ohlcv_data(df_vn30_raw, "VN30")

        stock_data_map = {}
        stock_dates_map = {}

        with tracker.measure_stage("stock_fetch"):
            for idx, item in enumerate(candidate_stocks):
                sym = item["symbol"].upper()
                tracker.record_request(sym)
                try:
                    df_stock, tag, warns = get_historical_data(
                        sym,
                        max_retries=1,
                        use_cache_only=use_cache,
                        throttle_delay=throttle,
                        target_date=data_as_of if update_data else None,
                    )
                    stock_data_map[sym] = (df_stock, tag, warns)

                    df_clean_stock, stock_val = get_clean_ohlcv_data(df_stock, sym)
                    stock_dates_map[sym] = stock_val.get("latest_date")

                    if tag in ("PROVIDER_FAILURE", "PROVIDER_ERROR", "EXPLICITLY_INVALID"):
                        failed_symbols.add(sym)
                        cat = (
                            "EXPLICITLY_INVALID"
                            if tag == "EXPLICITLY_INVALID"
                            else "PROVIDER_FAILURE"
                        )
                        exclusions_map[sym] = {
                            "symbol": sym,
                            "stage": "STOCK_FETCH",
                            "category": cat,
                            "status": "FAILED",
                            "reason": f"Provider tag {tag} for symbol {sym}",
                            "latest_date": stock_dates_map.get(sym),
                            "expected_date": data_as_of,
                            "processed": False,
                            "recoverable": is_recoverable_category(cat),
                        }
                    elif tag == "INVALID_SYMBOL":
                        invalid_symbols.add(sym)
                        exclusions_map[sym] = {
                            "symbol": sym,
                            "stage": "STOCK_FETCH",
                            "category": "INVALID_SYMBOL",
                            "status": "INVALID",
                            "reason": f"Invalid stock symbol {sym}",
                            "latest_date": stock_dates_map.get(sym),
                            "expected_date": data_as_of,
                            "processed": False,
                            "recoverable": is_recoverable_category("INVALID_SYMBOL"),
                        }
                    elif df_stock is None or df_stock.empty or df_clean_stock.empty:
                        failed_symbols.add(sym)
                        exclusions_map[sym] = {
                            "symbol": sym,
                            "stage": "STOCK_FETCH",
                            "category": "OTHER_VALIDATION_FAILURE",
                            "status": "FAILED",
                            "reason": f"Empty OHLCV dataset for {sym}",
                            "latest_date": stock_dates_map.get(sym),
                            "expected_date": data_as_of,
                            "processed": False,
                            "recoverable": is_recoverable_category("OTHER_VALIDATION_FAILURE"),
                        }
                    elif (
                        tag == "INSUFFICIENT_HISTORICAL_DATA"
                        or stock_val.get("status") == "INSUFFICIENT"
                    ):
                        insufficient_history_symbols.add(sym)
                        exclusions_map[sym] = {
                            "symbol": sym,
                            "stage": "STOCK_FETCH",
                            "category": "INSUFFICIENT_HISTORICAL_DATA",
                            "status": "INSUFFICIENT",
                            "reason": f"Insufficient historical sessions for {sym}",
                            "latest_date": stock_dates_map.get(sym),
                            "expected_date": data_as_of,
                            "processed": False,
                            "recoverable": is_recoverable_category("INSUFFICIENT_HISTORICAL_DATA"),
                        }
                    else:
                        processed_symbols.add(sym)
                except ProviderRateLimitError:
                    failed_symbols.add(sym)
                    exclusions_map[sym] = {
                        "symbol": sym,
                        "stage": "STOCK_FETCH",
                        "category": "RATE_LIMIT",
                        "status": "FAILED",
                        "reason": f"Provider rate limit encountered fetching {sym}",
                        "latest_date": None,
                        "expected_date": data_as_of,
                        "processed": False,
                        "recoverable": is_recoverable_category("RATE_LIMIT"),
                    }
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.error("Exception fetching %s: %s", sym, exc)
                    failed_symbols.add(sym)
                    exclusions_map[sym] = {
                        "symbol": sym,
                        "stage": "STOCK_FETCH",
                        "category": "PROVIDER_FAILURE",
                        "status": "FAILED",
                        "reason": f"Exception fetching {sym}: {type(exc).__name__}",
                        "latest_date": None,
                        "expected_date": data_as_of,
                        "processed": False,
                        "recoverable": is_recoverable_category("PROVIDER_FAILURE"),
                    }
                    stock_data_map[sym] = (pd.DataFrame(), "PROVIDER_FAILURE", [str(exc)])
                    stock_dates_map[sym] = None

        with tracker.measure_stage("temporal_validation"):
            temporal_res = validate_temporal_integrity(
                data_as_of=data_as_of,
                stock_dates_map={
                    s: stock_dates_map[s] for s in processed_symbols if s not in ("VNINDEX", "VN30")
                },
                reference_date=generated_at,
                strict_date_match=update_data,
            )

            if not temporal_res["is_valid"]:
                logger.warning("Temporal integrity validation failure: %s", temporal_res["issues"])
                temporal_invalid_syms = (
                    temporal_res["future_symbols"]
                    | temporal_res["stale_symbols"]
                    | temporal_res["missing_date_symbols"]
                )
                for sym in temporal_invalid_syms:
                    processed_symbols.discard(sym)
                    failed_symbols.add(sym)
                    exclusions_map[sym] = {
                        "symbol": sym,
                        "stage": "TEMPORAL_VALIDATION",
                        "category": "TEMPORAL_INVALID",
                        "status": "FAILED",
                        "reason": f"[{sym}] Vi phạm tính toàn vẹn thời gian relative to VNINDEX data_as_of ({data_as_of})",
                        "latest_date": stock_dates_map.get(sym),
                        "expected_date": data_as_of,
                        "processed": False,
                        "recoverable": is_recoverable_category("TEMPORAL_INVALID"),
                    }
                    # Replace stock data with empty DataFrame and tag as EXPLICITLY_INVALID so downstream calculations exclude it
                    stock_data_map[sym] = (
                        pd.DataFrame(),
                        "EXPLICITLY_INVALID",
                        [
                            f"[{sym}] Vi phạm tính toàn vẹn thời gian relative to VNINDEX data_as_of ({data_as_of})"
                        ],
                    )

        missing_symbols = expected_symbols - (
            processed_symbols | invalid_symbols | insufficient_history_symbols | failed_symbols
        )
        for sym in missing_symbols:
            exclusions_map[sym] = {
                "symbol": sym,
                "stage": "UNIVERSE_DISCOVERY",
                "category": "UNIVERSE_INCOMPLETE",
                "status": "MISSING",
                "reason": f"Symbol {sym} missing from scan results",
                "latest_date": None,
                "expected_date": data_as_of,
                "processed": False,
                "recoverable": is_recoverable_category("UNIVERSE_INCOMPLETE"),
            }

        universe_audit = build_universe_audit(
            expected_symbols=expected_symbols,
            processed_symbols=processed_symbols,
            invalid_symbols=invalid_symbols,
            insufficient_history_symbols=insufficient_history_symbols,
            failed_symbols=failed_symbols,
            missing_symbols=missing_symbols,
            exclusions_map=exclusions_map,
            update_data=update_data,
        )

        failed_stage = universe_audit["failed_stage"]
        pipeline_status = universe_audit["status"]
        diagnostics_list = universe_audit["diagnostics"]

        if update_data and (
            expected_symbols != (processed_symbols | invalid_symbols)
            or failed_symbols
            or insufficient_history_symbols
            or missing_symbols
            or not temporal_res["is_valid"]
        ):
            err_msg = (
                f"Incomplete universe scan in update mode: stage={failed_stage}, "
                f"status={pipeline_status}. "
                f"Expected: {len(expected_symbols)}, Processed: {len(processed_symbols)}, "
                f"Invalid: {len(invalid_symbols)}, Insufficient History: {len(insufficient_history_symbols)}, "
                f"Failed: {len(failed_symbols)}, Missing: {len(missing_symbols)}. "
                f"Temporal issues: {temporal_res['issues']}. "
                f"Processed symbols: {sorted(processed_symbols)}. "
                f"Invalid symbols: {sorted(invalid_symbols)}. "
                f"Insufficient history symbols: {sorted(insufficient_history_symbols)}. "
                f"Failed symbols: {sorted(failed_symbols)}. "
                f"Missing symbols: {sorted(missing_symbols)}."
            )
            logger.error(err_msg)
            logger.error("Per-symbol failure diagnostics (%d):", len(diagnostics_list))
            for diag in diagnostics_list:
                logger.error(
                    "  - [%s] stage=%s category=%s status=%s reason=%s",
                    diag["symbol"],
                    diag["stage"],
                    diag["category"],
                    diag["status"],
                    diag["reason"],
                )
            exc = RuntimeError(err_msg)
            exc.universe_audit = universe_audit
            raise exc

        logger.info("Step 2: Calculating Market Breadth...")
        with tracker.measure_stage("market_calculation"):
            bullish_count = 0
            valid_breadth_denom = 0
            for sym in candidate_stocks:
                s_name = sym["symbol"]
                if s_name in processed_symbols:
                    df_st, _, _ = stock_data_map[s_name]
                    df_c_st, st_val = get_clean_ohlcv_data(df_st, s_name)
                    if (
                        st_val["status"] == "SUFFICIENT"
                        and not df_c_st.empty
                        and len(df_c_st) >= 20
                    ):
                        valid_breadth_denom += 1
                        c = df_c_st["close"].iloc[-1]
                        ma20 = df_c_st["close"].tail(20).mean()
                        if c > ma20:
                            bullish_count += 1

            breadth_ratio = (
                round(bullish_count / valid_breadth_denom, 2) if valid_breadth_denom > 0 else 0.50
            )

        logger.info("Step 3: Calculating Final Market Regime...")
        with tracker.measure_stage("regime_calculation"):
            final_market_regime = detect_market_regime(
                df_vnindex=df_vnindex_clean,
                df_vn30=df_vn30_clean if vn30_val["status"] != "INSUFFICIENT" else None,
                breadth_ratio=breadth_ratio,
            )

        logger.info("Step 4: Generating Stock Recommendations using Final Market Regime...")
        with tracker.measure_stage("recommendation_calculation"):
            scanned_recs = []
            for item in candidate_stocks:
                sym = item["symbol"]
                comp = item["companyName"]
                sec = item["sector"]
                ex = item.get("exchange", "HOSE")

                df_stock, tag, _ = stock_data_map[sym]
                if sym in processed_symbols:
                    df_clean_stock, _ = get_clean_ohlcv_data(df_stock, sym)
                    df_stock_input = df_clean_stock
                else:
                    df_stock_input = pd.DataFrame()

                rec = generate_recommendation(
                    symbol=sym,
                    company_name=comp,
                    sector=sec,
                    exchange=ex,
                    df_stock=df_stock_input,
                    market_regime_info=final_market_regime,
                    df_vnindex=df_vnindex_clean,
                    data_as_of=data_as_of,
                    data_source=tag if not df_stock_input.empty else None,
                )
                scanned_recs.append(rec)

        logger.info("Step 5: Computing Universe Percentile Liquidity Scores...")
        with tracker.measure_stage("risk_calculation"):
            scanned_recs = normalize_universe_liquidity_scores(
                scanned_recs, market_regime=final_market_regime
            )

        buy_cnt = sum(1 for r in scanned_recs if r["action"] == "BUY")
        watch_cnt = sum(1 for r in scanned_recs if r["action"] == "WATCH")
        hold_cnt = sum(1 for r in scanned_recs if r["action"] == "HOLD")
        sell_cnt = sum(1 for r in scanned_recs if r["action"] == "SELL")
        avoid_cnt = sum(1 for r in scanned_recs if r["action"] == "AVOID")

        summary = {
            "total_scanned": len(scanned_recs),
            "buy_count": buy_cnt,
            "watch_count": watch_cnt,
            "hold_count": hold_cnt,
            "sell_count": sell_cnt,
            "avoid_count": avoid_cnt,
        }

        recommendations_payload = {
            "schema_version": "2.0",
            "signal_model_version": SIGNAL_MODEL_VERSION,
            "generated_at": generated_at,
            "data_as_of": data_as_of,
            "source_date": source_date,
            "data_source": data_source,
            "universe_info": universe_info,
            "market": final_market_regime,
            "summary": summary,
            "recommendations": scanned_recs,
        }

        market_payload = {
            "data_as_of": data_as_of,
            "source_date": source_date,
            "generated_at": generated_at,
            "data_source": data_source,
            "universe_info": universe_info,
            "market": final_market_regime,
            "summary": summary,
        }

        history_payload = recommendations_payload

        pipeline_elapsed = time.perf_counter() - t_pipeline_start
        performance_data = tracker.get_performance_payload(
            pipeline_elapsed=pipeline_elapsed,
            pipeline_status=pipeline_status,
        )

        universe_audit["performance"] = performance_data

        return PipelineResult(
            recommendations_payload,
            market_payload,
            history_payload,
            df_vnindex=df_vnindex_clean,
            df_vn30=df_vn30_clean if vn30_val["status"] != "INSUFFICIENT" else None,
            universe_audit=universe_audit,
        )
    except Exception as exc:
        pipeline_status = "FAILED"
        pipeline_elapsed = time.perf_counter() - t_pipeline_start
        performance_data = tracker.get_performance_payload(
            pipeline_elapsed=pipeline_elapsed,
            pipeline_status=pipeline_status,
        )
        if hasattr(exc, "universe_audit") and isinstance(exc.universe_audit, dict):
            exc.universe_audit["performance"] = performance_data
        else:
            if "expected_symbols" in locals():
                audit_partial = build_universe_audit(
                    expected_symbols=expected_symbols,
                    processed_symbols=locals().get("processed_symbols", set()),
                    invalid_symbols=locals().get("invalid_symbols", set()),
                    insufficient_history_symbols=locals().get(
                        "insufficient_history_symbols", set()
                    ),
                    failed_symbols=locals().get("failed_symbols", set()),
                    missing_symbols=locals().get("missing_symbols", set()),
                    exclusions_map=locals().get("exclusions_map", {}),
                    update_data=update_data,
                    performance_data=performance_data,
                )
                exc.universe_audit = audit_partial
            else:
                exc.universe_audit = {"performance": performance_data}
        raise


def generate_historical_report(
    data_as_of: str,
    universe_stock_map: dict[str, pd.DataFrame],
    df_vnindex: pd.DataFrame,
    df_vn30: pd.DataFrame | None = None,
    candidate_metadata: list[dict] | None = None,
    data_source: str = "explicit_historical_input",
    reference_date: str | None = None,
    tracker: PerformanceTracker | None = None,
) -> PipelineResult:
    """Generate a point-in-time historical report for explicit target date T.

    Fail-Closed Principles:
    - data_as_of must be explicit canonical YYYY-MM-DD.
    - Historical datasets are strictly sliced <= T via get_as_of_dataset.
    - Future rows (> T), unsorted dates, duplicate dates, or malformed OHLCV cause immediate failure.
    - The target evaluation date T must exist in df_vnindex (raises ValueError if absent).
    - Reuses production quantitative scoring, market regime detection, risk, and trade plan functions.
    """
    if tracker is None:
        tracker = PerformanceTracker()

    t_pipeline_start = time.perf_counter()
    pipeline_status = "SUCCESS"

    canonical_as_of = _parse_canonical_date(data_as_of)
    generated_at = reference_date if reference_date is not None else datetime.now(UTC).isoformat()

    if candidate_metadata is None or not isinstance(candidate_metadata, list):
        raise TypeError("candidate_metadata must be a list of candidate stock dicts")
    if not candidate_metadata:
        raise ValueError("candidate_metadata cannot be empty")

    if not isinstance(universe_stock_map, dict):
        raise TypeError("universe_stock_map must be a dictionary mapping symbols to DataFrames")

    with tracker.measure_stage("benchmark_fetch"):
        tracker.record_request("VNINDEX")
        df_vnindex_as_of = get_as_of_dataset(df_vnindex, canonical_as_of)
        df_vnindex_clean, vnindex_val = get_clean_ohlcv_data(df_vnindex_as_of, "VNINDEX")

        if df_vnindex_clean.empty or vnindex_val.get("latest_date") != canonical_as_of:
            raise ValueError(
                f"Requested historical evaluation date '{canonical_as_of}' is absent from benchmark VNINDEX historical data"
            )

        df_vn30_clean = None
        vn30_val = {"status": "INSUFFICIENT"}
        if df_vn30 is not None:
            tracker.record_request("VN30")
            df_vn30_as_of = get_as_of_dataset(df_vn30, canonical_as_of)
            df_vn30_clean, vn30_val = get_clean_ohlcv_data(df_vn30_as_of, "VN30")

    clean_stock_as_of_map = {}
    seen_candidate_symbols = set()

    with tracker.measure_stage("stock_fetch"):
        for idx, item in enumerate(candidate_metadata):
            if not isinstance(item, dict):
                raise TypeError(f"Candidate metadata item at index {idx} must be a dict")
            sym = item.get("symbol")
            if not sym or not isinstance(sym, str):
                raise ValueError(
                    f"Candidate metadata item at index {idx} missing valid symbol string"
                )

            sym_upper = sym.upper()
            tracker.record_request(sym_upper)
            if sym_upper in seen_candidate_symbols:
                raise ValueError(
                    f"Duplicate candidate stock symbol '{sym_upper}' in candidate_metadata"
                )
            seen_candidate_symbols.add(sym_upper)

            if sym_upper not in universe_stock_map:
                raise ValueError(
                    f"Candidate stock symbol '{sym_upper}' is missing from universe_stock_map"
                )

            df_stock_raw = universe_stock_map[sym_upper]
            if df_stock_raw is not None and not df_stock_raw.empty:
                df_stock_as_of = get_as_of_dataset(df_stock_raw, canonical_as_of)
                df_stock_clean, _stock_val = get_clean_ohlcv_data(df_stock_as_of, sym_upper)
            else:
                df_stock_clean = pd.DataFrame()

            clean_stock_as_of_map[sym_upper] = df_stock_clean

    with tracker.measure_stage("temporal_validation"):
        pass

    with tracker.measure_stage("market_calculation"):
        bullish_count = 0
        valid_breadth_denom = 0
        for sym_upper, df_stock_clean in clean_stock_as_of_map.items():
            if not df_stock_clean.empty and len(df_stock_clean) >= 20:
                valid_breadth_denom += 1
                c = df_stock_clean["close"].iloc[-1]
                ma20 = df_stock_clean["close"].tail(20).mean()
                if c > ma20:
                    bullish_count += 1

        breadth_ratio = (
            round(bullish_count / valid_breadth_denom, 2) if valid_breadth_denom > 0 else 0.50
        )

    with tracker.measure_stage("regime_calculation"):
        final_market_regime = detect_market_regime(
            df_vnindex=df_vnindex_clean,
            df_vn30=df_vn30_clean if vn30_val["status"] != "INSUFFICIENT" else None,
            breadth_ratio=breadth_ratio,
        )

    with tracker.measure_stage("recommendation_calculation"):
        scanned_recs = []
        for item in candidate_metadata:
            sym = item["symbol"].upper()
            comp = item["companyName"]
            sec = item["sector"]
            ex = item.get("exchange", "HOSE")

            df_stock_clean = clean_stock_as_of_map[sym]

            rec = generate_recommendation(
                symbol=sym,
                company_name=comp,
                sector=sec,
                exchange=ex,
                df_stock=df_stock_clean,
                market_regime_info=final_market_regime,
                df_vnindex=df_vnindex_clean,
                data_as_of=canonical_as_of,
                data_source=data_source,
            )
            scanned_recs.append(rec)

    with tracker.measure_stage("risk_calculation"):
        scanned_recs = normalize_universe_liquidity_scores(
            scanned_recs, market_regime=final_market_regime
        )

    buy_cnt = sum(1 for r in scanned_recs if r["action"] == "BUY")
    watch_cnt = sum(1 for r in scanned_recs if r["action"] == "WATCH")
    hold_cnt = sum(1 for r in scanned_recs if r["action"] == "HOLD")
    sell_cnt = sum(1 for r in scanned_recs if r["action"] == "SELL")
    avoid_cnt = sum(1 for r in scanned_recs if r["action"] == "AVOID")

    summary = {
        "total_scanned": len(scanned_recs),
        "buy_count": buy_cnt,
        "watch_count": watch_cnt,
        "hold_count": hold_cnt,
        "sell_count": sell_cnt,
        "avoid_count": avoid_cnt,
    }

    universe_info = {
        "universe_type": "HISTORICAL_SNAPSHOT",
        "universe_size": len(candidate_metadata),
    }

    recommendations_payload = {
        "schema_version": "2.0",
        "signal_model_version": SIGNAL_MODEL_VERSION,
        "generated_at": generated_at,
        "data_as_of": canonical_as_of,
        "source_date": canonical_as_of,
        "data_source": data_source,
        "universe_info": universe_info,
        "market": final_market_regime,
        "summary": summary,
        "recommendations": scanned_recs,
    }

    market_payload = {
        "data_as_of": canonical_as_of,
        "source_date": canonical_as_of,
        "generated_at": generated_at,
        "data_source": data_source,
        "universe_info": universe_info,
        "market": final_market_regime,
        "summary": summary,
    }

    history_payload = recommendations_payload

    with tracker.measure_stage("payload_validation"):
        validate_final_payload_integrity(recommendations_payload, schema=None)
        validate_final_payload_integrity(market_payload, schema=None)

    expected_symbols = {"VNINDEX", "VN30"} | {item["symbol"].upper() for item in candidate_metadata}
    processed_symbols = set()
    invalid_symbols = set()
    insufficient_history_symbols = set()
    failed_symbols = set()
    exclusions_map = {}

    if not df_vnindex_clean.empty and vnindex_val.get("latest_date") == canonical_as_of:
        processed_symbols.add("VNINDEX")
    else:
        failed_symbols.add("VNINDEX")
        exclusions_map["VNINDEX"] = {
            "symbol": "VNINDEX",
            "stage": "BENCHMARK_FETCH",
            "category": "INSUFFICIENT_HISTORICAL_DATA",
            "status": "FAILED",
            "reason": f"Benchmark VNINDEX data missing for canonical_as_of {canonical_as_of}",
            "latest_date": vnindex_val.get("latest_date"),
            "expected_date": canonical_as_of,
            "processed": False,
            "recoverable": False,
        }

    if (
        df_vn30_clean is not None
        and not df_vn30_clean.empty
        and vn30_val.get("status") != "INSUFFICIENT"
    ):
        processed_symbols.add("VN30")
    else:
        failed_symbols.add("VN30")
        exclusions_map["VN30"] = {
            "symbol": "VN30",
            "stage": "BENCHMARK_FETCH",
            "category": "INSUFFICIENT_HISTORICAL_DATA",
            "status": "FAILED",
            "reason": f"Benchmark VN30 data missing or insufficient for canonical_as_of {canonical_as_of}",
            "latest_date": vn30_val.get("latest_date") if df_vn30 is not None else None,
            "expected_date": canonical_as_of,
            "processed": False,
            "recoverable": False,
        }

    for item in candidate_metadata:
        sym_upper = item["symbol"].upper()
        df_st = clean_stock_as_of_map.get(sym_upper)
        if df_st is not None and not df_st.empty:
            processed_symbols.add(sym_upper)
        else:
            insufficient_history_symbols.add(sym_upper)
            exclusions_map[sym_upper] = {
                "symbol": sym_upper,
                "stage": "STOCK_FETCH",
                "category": "INSUFFICIENT_HISTORICAL_DATA",
                "status": "INSUFFICIENT",
                "reason": f"Historical data missing or insufficient for candidate {sym_upper} at {canonical_as_of}",
                "latest_date": None,
                "expected_date": canonical_as_of,
                "processed": False,
                "recoverable": False,
            }

    missing_symbols = expected_symbols - (
        processed_symbols | invalid_symbols | insufficient_history_symbols | failed_symbols
    )
    for sym in missing_symbols:
        exclusions_map[sym] = {
            "symbol": sym,
            "stage": "UNIVERSE_DISCOVERY",
            "category": "UNIVERSE_INCOMPLETE",
            "status": "MISSING",
            "reason": f"Symbol {sym} missing from historical snapshot",
            "latest_date": None,
            "expected_date": canonical_as_of,
            "processed": False,
            "recoverable": False,
        }

    pipeline_elapsed = time.perf_counter() - t_pipeline_start
    performance_data = tracker.get_performance_payload(
        pipeline_elapsed=pipeline_elapsed,
        pipeline_status=pipeline_status,
    )

    universe_audit = build_universe_audit(
        expected_symbols=expected_symbols,
        processed_symbols=processed_symbols,
        invalid_symbols=invalid_symbols,
        insufficient_history_symbols=insufficient_history_symbols,
        failed_symbols=failed_symbols,
        missing_symbols=missing_symbols,
        exclusions_map=exclusions_map,
        update_data=False,
        performance_data=performance_data,
    )

    return PipelineResult(
        recommendations_payload,
        market_payload,
        history_payload,
        df_vnindex=df_vnindex_clean,
        df_vn30=df_vn30_clean if vn30_val["status"] != "INSUFFICIENT" else None,
        universe_audit=universe_audit,
    )


def canonicalize_report_for_reproducibility(report_payload: dict) -> dict:
    """Return a canonical copy of report payload with runtime metadata excluded/normalized.

    Runtime metadata excluded for quantitative reproducibility comparison:
    - generated_at
    - universe_info.scanned_at (if present)
    """
    if not isinstance(report_payload, dict):
        raise TypeError("report_payload must be a dictionary")

    report_copy = copy.deepcopy(report_payload)
    report_copy.pop("generated_at", None)

    if "universe_info" in report_copy and isinstance(report_copy["universe_info"], dict):
        report_copy["universe_info"].pop("scanned_at", None)

    return report_copy


def load_universe_snapshot(snapshot_path: str) -> list[dict]:
    """Load and validate an explicit historical candidate universe snapshot JSON file."""
    if not snapshot_path or not isinstance(snapshot_path, str):
        raise TypeError("universe_snapshot path must be a non-empty string")

    try:
        with open(snapshot_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as err:
        raise ValueError(
            f"Explicit historical universe snapshot file not found at '{snapshot_path}'"
        ) from err
    except json.JSONDecodeError as err:
        raise ValueError(
            f"Failed to decode historical universe snapshot JSON file at '{snapshot_path}': {err}"
        ) from err
    except (PermissionError, OSError) as err:
        raise OSError(
            f"I/O error reading historical universe snapshot file at '{snapshot_path}': {err}"
        ) from err

    if isinstance(data, dict):
        raw_list = data.get("candidates") or data.get("universe") or data.get("recommendations")
        if not isinstance(raw_list, list):
            raise TypeError(
                f"Historical universe snapshot object at '{snapshot_path}' missing required 'candidates', 'universe', or 'recommendations' array"
            )
    elif isinstance(data, list):
        raw_list = data
    else:
        raise TypeError(
            f"Historical universe snapshot at '{snapshot_path}' must be a list or dict root"
        )

    if not raw_list:
        raise ValueError(
            f"Historical universe snapshot at '{snapshot_path}' contains an empty candidate list"
        )

    candidate_stocks = []
    seen_symbols = set()

    for idx, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise TypeError(
                f"Historical candidate item at index {idx} in '{snapshot_path}' must be a dict"
            )

        sym = item.get("symbol")
        comp = item.get("companyName") or item.get("company_name")
        sec = item.get("sector")
        ex = item.get("exchange", "HOSE")

        if not sym or not isinstance(sym, str) or not sym.strip():
            raise ValueError(
                f"Historical candidate item at index {idx} in '{snapshot_path}' missing valid 'symbol' string"
            )
        if not comp or not isinstance(comp, str) or not comp.strip():
            raise ValueError(
                f"Historical candidate item at index {idx} in '{snapshot_path}' missing valid 'companyName' string"
            )
        if not sec or not isinstance(sec, str) or not sec.strip():
            raise ValueError(
                f"Historical candidate item at index {idx} in '{snapshot_path}' missing valid 'sector' string"
            )

        sym_upper = sym.strip().upper()
        if sym_upper in seen_symbols:
            raise ValueError(f"Duplicate symbol '{sym_upper}' in '{snapshot_path}'")
        seen_symbols.add(sym_upper)

        candidate_stocks.append(
            {
                "symbol": sym_upper,
                "companyName": comp.strip(),
                "sector": sec.strip(),
                "exchange": ex.strip().upper() if isinstance(ex, str) else "HOSE",
            }
        )

    return candidate_stocks


def load_historical_ohlcv(
    ohlcv_path_or_dir: str, required_symbols: list[str]
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame | None]:
    """Load explicit historical OHLCV data for stock universe and benchmark indices."""
    if not ohlcv_path_or_dir or not isinstance(ohlcv_path_or_dir, str):
        raise TypeError("historical_ohlcv path must be a non-empty string")

    if not os.path.exists(ohlcv_path_or_dir):
        raise ValueError(f"Explicit historical OHLCV path not found at '{ohlcv_path_or_dir}'")

    raw_ohlcv_map: dict[str, Any] = {}

    if os.path.isdir(ohlcv_path_or_dir):
        all_symbols = set(required_symbols) | {"VNINDEX", "VN30"}
        for sym in all_symbols:
            json_file = os.path.join(ohlcv_path_or_dir, f"{sym}.json")
            csv_file = os.path.join(ohlcv_path_or_dir, f"{sym}.csv")

            if os.path.exists(json_file):
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        raw_ohlcv_map[sym] = json.load(f)
                except json.JSONDecodeError as err:
                    raise ValueError(
                        f"Failed to decode historical OHLCV JSON file for '{sym}' at '{json_file}': {err}"
                    ) from err
                except (PermissionError, OSError) as err:
                    raise OSError(
                        f"I/O error reading historical OHLCV file for '{sym}' at '{json_file}': {err}"
                    ) from err
            elif os.path.exists(csv_file):
                try:
                    raw_ohlcv_map[sym] = pd.read_csv(csv_file)
                except (PermissionError, OSError) as err:
                    raise OSError(
                        f"I/O error reading historical OHLCV CSV file for '{sym}' at '{csv_file}': {err}"
                    ) from err
    else:
        try:
            with open(ohlcv_path_or_dir, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as err:
            raise ValueError(
                f"Failed to decode historical OHLCV JSON map file at '{ohlcv_path_or_dir}': {err}"
            ) from err
        except (PermissionError, OSError) as err:
            raise OSError(
                f"I/O error reading historical OHLCV file at '{ohlcv_path_or_dir}': {err}"
            ) from err

        if not isinstance(data, dict):
            raise TypeError(
                f"Historical OHLCV map file at '{ohlcv_path_or_dir}' must contain a JSON object mapping symbol to OHLCV data"
            )
        raw_ohlcv_map = {str(k).upper(): v for k, v in data.items()}

    parsed_map: dict[str, pd.DataFrame] = {}
    for sym, val in raw_ohlcv_map.items():
        sym_upper = sym.upper()
        if isinstance(val, pd.DataFrame):
            parsed_map[sym_upper] = val.copy()
        elif isinstance(val, list):
            parsed_map[sym_upper] = pd.DataFrame(val)
        elif isinstance(val, dict):
            if "data" in val and isinstance(val["data"], list):
                parsed_map[sym_upper] = pd.DataFrame(val["data"])
            elif "records" in val and isinstance(val["records"], list):
                parsed_map[sym_upper] = pd.DataFrame(val["records"])
            else:
                parsed_map[sym_upper] = pd.DataFrame(val)
        else:
            raise TypeError(
                f"Unsupported OHLCV data type for symbol '{sym_upper}' in '{ohlcv_path_or_dir}'"
            )

    if "VNINDEX" not in parsed_map or parsed_map["VNINDEX"].empty:
        raise ValueError(
            f"Missing required benchmark 'VNINDEX' OHLCV dataset in historical OHLCV input '{ohlcv_path_or_dir}'"
        )

    df_vnindex = parsed_map["VNINDEX"]
    df_vn30 = parsed_map.get("VN30")

    universe_stock_map: dict[str, pd.DataFrame] = {}
    missing_stock_symbols = []

    for sym in required_symbols:
        sym_upper = sym.upper()
        if sym_upper not in parsed_map or parsed_map[sym_upper].empty:
            missing_stock_symbols.append(sym_upper)
        else:
            universe_stock_map[sym_upper] = parsed_map[sym_upper]

    if missing_stock_symbols:
        raise ValueError(
            f"Missing required historical stock OHLCV datasets for symbols {sorted(missing_stock_symbols)} "
            f"in historical OHLCV input '{ohlcv_path_or_dir}'"
        )

    return universe_stock_map, df_vnindex, df_vn30


def load_history_index(index_path: str | None = None) -> dict:
    """Load and validate history index file (history/index.json)."""
    if index_path is None:
        index_path = os.path.join(GENERATED_DIR, "history", "index.json")

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"dates": []}
    except json.JSONDecodeError as err:
        raise ValueError(f"Failed to load history index '{index_path}': invalid JSON") from err
    except (PermissionError, OSError) as err:
        raise OSError(f"Failed to read history index '{index_path}': {err}") from err

    if not isinstance(data, dict):
        raise TypeError(
            f"Invalid history index structure in '{index_path}': expected object root, got {type(data).__name__}"
        )

    if "dates" not in data:
        raise ValueError(
            f"Invalid history index structure in '{index_path}': missing required 'dates' field"
        )

    dates = data["dates"]
    if not isinstance(dates, list):
        raise TypeError(
            f"Invalid history index structure in '{index_path}': 'dates' field must be a list"
        )

    if not all(isinstance(d, str) for d in dates):
        raise TypeError(
            f"Invalid history index structure in '{index_path}': all items in 'dates' must be strings"
        )

    return data


def update_history_index(data_date: str | None, index_path: str | None = None):
    """Maintain history/index.json with list of available historical dates."""
    if not data_date:
        return

    if index_path is None:
        index_path = os.path.join(GENERATED_DIR, "history", "index.json")

    index_data = load_history_index(index_path)
    history_dates = index_data.get("dates", [])

    if data_date not in history_dates:
        history_dates = list(history_dates)
        history_dates.append(data_date)
        history_dates.sort(reverse=True)

    index_payload = {
        "last_updated": datetime.now(UTC).isoformat(),
        "total_reports": len(history_dates),
        "dates": history_dates,
    }

    relative_path = (
        os.path.relpath(index_path, GENERATED_DIR)
        if index_path.startswith(GENERATED_DIR)
        else os.path.join("history", "index.json")
    )
    save_json_files(relative_path, index_payload)


def main():
    parser = argparse.ArgumentParser(description="VN Invest Report Generator v2")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Run data fetch pipeline before report generation",
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="Explicit historical evaluation date (YYYY-MM-DD) for reproducible report generation",
    )
    parser.add_argument(
        "--universe-snapshot",
        type=str,
        default=None,
        help="Path to explicit historical universe snapshot JSON file for --as-of report generation",
    )
    parser.add_argument(
        "--historical-ohlcv",
        type=str,
        default=None,
        help="Path to explicit historical OHLCV JSON map file or directory for --as-of report generation",
    )
    args = parser.parse_args()

    schema = load_schema()

    if args.as_of:
        if not args.universe_snapshot or not args.historical_ohlcv:
            missing_args = []
            if not args.universe_snapshot:
                missing_args.append("--universe-snapshot <filepath>")
            if not args.historical_ohlcv:
                missing_args.append("--historical-ohlcv <filepath_or_dir>")
            raise ValueError(
                "Historical report generation via CLI '--as-of' requires explicit historical inputs: "
                f"missing {', '.join(missing_args)}. Do NOT rely on current UniverseProvider or live provider data."
            )

        target_date = _parse_canonical_date(args.as_of)
        logger.info("Starting historical report generation for as-of date: %s...", target_date)

        candidate_stocks = load_universe_snapshot(args.universe_snapshot)
        required_symbols = [item["symbol"] for item in candidate_stocks]

        stock_data_map, df_vnindex_raw, df_vn30_raw = load_historical_ohlcv(
            args.historical_ohlcv, required_symbols=required_symbols
        )

        pipeline_res = generate_historical_report(
            data_as_of=target_date,
            universe_stock_map=stock_data_map,
            df_vnindex=df_vnindex_raw,
            df_vn30=df_vn30_raw,
            candidate_metadata=candidate_stocks,
            data_source="explicit_historical_input",
        )

        recs_data, _, history_data = pipeline_res

        logger.info("Validating historical recommendations payload & integrity...")
        try:
            validate_final_payload_integrity(recs_data, schema=schema)
            if history_data is not recs_data:
                validate_final_payload_integrity(history_data, schema=schema)
        except ValueError as exc:
            logger.error("Historical report payload integrity validation failed: %s", exc)
            logger.error("Existing generated report files have been preserved and not overwritten.")
            raise SystemExit(1) from exc

        logger.info("JSON Schema & output integrity validation passed successfully!")

        index_path = os.path.join(GENERATED_DIR, "history", "index.json")
        index_data = load_history_index(index_path)
        history_dates = index_data.get("dates", [])
        if target_date not in history_dates:
            history_dates = list(history_dates)
            history_dates.append(target_date)
            history_dates.sort(reverse=True)
        index_payload = {
            "last_updated": datetime.now(UTC).isoformat(),
            "total_reports": len(history_dates),
            "dates": history_dates,
        }

        historical_artifacts = {
            os.path.join("history", f"{target_date}.json"): history_data,
            os.path.join("history", "index.json"): index_payload,
        }
        publish_artifacts_atomically(historical_artifacts)

        logger.info("Historical report generation complete!")
        logger.info("Outputs written to generated/history:")
        logger.info(
            "  - history/%s.json (%d items)", target_date, len(recs_data["recommendations"])
        )
        logger.info("  - history/index.json")
    else:
        logger.info("Starting VN Invest Report Generator v2 (update=%s)...", args.update)
        tracker = PerformanceTracker()
        try:
            pipeline_res = run_pipeline(update_data=args.update, tracker=tracker)
        except (ProviderRateLimitError, RuntimeError) as exc:
            logger.error("Data pipeline halted: %s", exc)
            logger.error("Existing generated report files have been preserved and not overwritten.")
            raise SystemExit(1) from exc

        recs_data, market_data, history_data = pipeline_res
        df_vnindex_clean = pipeline_res.df_vnindex
        df_vn30_clean = pipeline_res.df_vn30

        logger.info("Executing production pipeline monitoring...")
        try:
            with tracker.measure_stage("monitoring"):
                monitoring_result = evaluate_production_monitoring(
                    generated_dir=GENERATED_DIR,
                    recommendations_payload=recs_data,
                    market_payload=market_data,
                    df_vnindex=df_vnindex_clean,
                    df_vn30=df_vn30_clean,
                    universe_audit=getattr(pipeline_res, "universe_audit", None),
                )
        except Exception:
            perf_payload = tracker.get_performance_payload(
                pipeline_elapsed=time.perf_counter() - tracker.t_pipeline_start,
                pipeline_status="FAILED",
            )
            if hasattr(pipeline_res, "universe_audit") and isinstance(
                pipeline_res.universe_audit, dict
            ):
                pipeline_res.universe_audit["performance"] = perf_payload
            raise

        monitoring_dict = monitoring_result.to_dict()

        logger.info("Validating ALL report payloads & output integrity...")
        try:
            with tracker.measure_stage("payload_validation"):
                validate_final_payload_integrity(recs_data, schema=schema)
                validate_final_payload_integrity(market_data, schema=None)
                if history_data is not recs_data:
                    validate_final_payload_integrity(history_data, schema=schema)
                validate_final_payload_integrity(monitoring_dict, schema=None)
        except ValueError as exc:
            logger.error("Report payload integrity validation failed: %s", exc)
            logger.error("Existing generated report files have been preserved and not overwritten.")
            raise SystemExit(1) from exc

        logger.info("JSON Schema & output integrity validation passed for all payloads!")

        performance_data = tracker.get_performance_payload(
            pipeline_elapsed=time.perf_counter() - tracker.t_pipeline_start,
            pipeline_status="SUCCESS",
        )
        if "metrics" not in monitoring_dict or not isinstance(monitoring_dict["metrics"], dict):
            monitoring_dict["metrics"] = {}

        if hasattr(pipeline_res, "universe_audit") and isinstance(
            pipeline_res.universe_audit, dict
        ):
            pipeline_res.universe_audit["performance"] = performance_data
            monitoring_dict["metrics"]["universe_audit"] = pipeline_res.universe_audit

        monitoring_dict["metrics"]["performance"] = performance_data

        data_as_of = recs_data.get("data_as_of")

        # Evaluate monitoring status BEFORE publishing any artifacts
        logger.info("Production monitoring status: %s", monitoring_result.overall_status)
        if monitoring_result.overall_status == "FAIL":
            logger.error(
                "Production update rejected due to monitoring failure. All artifacts preserved byte-for-byte."
            )
            raise SystemExit(1)

        # Build full payload dictionary for atomic publication
        artifacts_to_publish = {
            "recommendations.json": recs_data,
            "market.json": market_data,
            "monitoring.json": monitoring_dict,
        }

        if data_as_of:
            artifacts_to_publish[os.path.join("history", f"{data_as_of}.json")] = history_data
            # Calculate updated history index payload in memory
            index_path = os.path.join(GENERATED_DIR, "history", "index.json")
            index_data = load_history_index(index_path)
            history_dates = index_data.get("dates", [])
            if data_as_of not in history_dates:
                history_dates = list(history_dates)
                history_dates.append(data_as_of)
                history_dates.sort(reverse=True)
            index_payload = {
                "last_updated": datetime.now(UTC).isoformat(),
                "total_reports": len(history_dates),
                "dates": history_dates,
            }
            artifacts_to_publish[os.path.join("history", "index.json")] = index_payload
        else:
            logger.warning(
                "data_as_of is None. Skipping creation of historical date JSON artifact and history index update."
            )

        publish_artifacts_atomically(artifacts_to_publish)

        logger.info("Report generation complete!")
        logger.info("Outputs written to generated/:")
        logger.info("  - recommendations.json (%d items)", len(recs_data["recommendations"]))
        logger.info("  - market.json (Regime: %s)", recs_data["market"]["regime"])
        logger.info("  - monitoring.json (Status: %s)", monitoring_result.overall_status)
        if data_as_of:
            logger.info("  - history/%s.json", data_as_of)
            logger.info("  - history/index.json")

        logger.info("Production monitoring status: %s", monitoring_result.overall_status)
        if monitoring_result.overall_status == "FAIL":
            logger.error("Production update rejected due to monitoring failure.")
            raise SystemExit(1)
        elif monitoring_result.overall_status in ("WARN", "WARNING"):
            logger.warning("Production monitoring produced a warning.")


if __name__ == "__main__":
    main()
