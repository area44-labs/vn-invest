"""Pipeline Stages for VN Invest production orchestration."""

import abc
import logging
import os
import time
from typing import Any

import pandas as pd

from scripts.data_provider import ProviderRateLimitError, VnstockDataProvider
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
from scripts.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


def _get_helper(name: str, fallback: Any = None) -> Any:
    """Resolve helper from scripts.generate_report if available, else fallback."""
    import sys

    mod = sys.modules.get("scripts.generate_report")
    if mod and hasattr(mod, name):
        return getattr(mod, name)
    if fallback is not None:
        return fallback
    globals_dict = globals()
    if name in globals_dict:
        return globals_dict[name]
    raise AttributeError(f"Helper '{name}' not found")


class PipelineStage(abc.ABC):
    """Abstract base class for all pipeline stages."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Name of the pipeline stage."""
        pass

    @abc.abstractmethod
    def execute(self, context: PipelineContext) -> None:
        """Execute stage logic against the provided PipelineContext."""
        pass


class DataAcquisitionStage(PipelineStage):
    """Stage 1: Acquire raw market data for benchmarks and candidate stock universe."""

    @property
    def name(self) -> str:
        return "data_acquisition"

    def execute(self, context: PipelineContext) -> None:
        if context.is_historical:
            return

        VnstockDataProvider.reset_global_call_history()
        provider_cls = _get_helper("UniverseProvider", fallback=UniverseProvider)
        context.provider = provider_cls()
        context.raw_candidate_stocks = context.provider.candidates
        context.universe_info = context.provider.get_info()

        if not context.raw_candidate_stocks:
            raise RuntimeError(
                "Candidate universe is empty. Cannot generate report on empty universe."
            )

        unique_candidate_stocks = []
        seen_candidate_syms = set()
        for item in context.raw_candidate_stocks:
            if isinstance(item, dict) and item.get("symbol"):
                sym_u = str(item["symbol"]).strip().upper()
                if sym_u and sym_u not in seen_candidate_syms:
                    seen_candidate_syms.add(sym_u)
                    item_copy = dict(item)
                    item_copy["symbol"] = sym_u
                    unique_candidate_stocks.append(item_copy)

        context.candidate_stocks = unique_candidate_stocks
        if not context.candidate_stocks:
            raise RuntimeError("Candidate universe contains no valid symbols.")

        if isinstance(context.universe_info, dict) and "universe_size" in context.universe_info:
            context.universe_info["universe_size"] = len(context.candidate_stocks)

        context.expected_symbols = {"VNINDEX", "VN30"} | {
            item["symbol"] for item in context.candidate_stocks
        }
        context.throttle = DEFAULT_UPDATE_THROTTLE_DELAY if context.update_data else 0.0

        get_hist_func = _get_helper("get_historical_data", fallback=get_historical_data)

        # Fetch VNINDEX benchmark
        with context.tracker.measure_stage("benchmark_fetch"):
            context.tracker.record_request("VNINDEX")
            try:
                raw_df, source, _ = get_hist_func(
                    "VNINDEX",
                    max_retries=2 if context.update_data else 1,
                    use_cache_only=context.use_cache,
                    throttle_delay=context.throttle,
                )
                context.df_vnindex_raw = raw_df
                context.vn_source = source

                df_clean_vn, vn_val = get_clean_ohlcv_data(raw_df, "VNINDEX")
                context.df_vnindex_clean = df_clean_vn
                context.vnindex_val = vn_val
                context.data_as_of = vn_val.get("latest_date")
                context.source_date = context.data_as_of
                context.data_source = source if not df_clean_vn.empty else None
            except ProviderRateLimitError:
                context.failed_symbols.add("VNINDEX")
                context.exclusions_map["VNINDEX"] = {
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
            except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as exc:
                logger.error("Exception fetching VNINDEX: %s", exc)
                context.failed_symbols.add("VNINDEX")
                context.exclusions_map["VNINDEX"] = {
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
                context.df_vnindex_raw = pd.DataFrame()
                context.vn_source = "PROVIDER_FAILURE"

            # Fetch VN30 benchmark
            context.tracker.record_request("VN30")
            try:
                raw_df, source, _ = get_hist_func(
                    "VN30",
                    max_retries=2 if context.update_data else 1,
                    use_cache_only=context.use_cache,
                    throttle_delay=context.throttle,
                )
                context.df_vn30_raw = raw_df
                context.vn30_source = source
            except ProviderRateLimitError:
                context.failed_symbols.add("VN30")
                context.exclusions_map["VN30"] = {
                    "symbol": "VN30",
                    "stage": "BENCHMARK_FETCH",
                    "category": "RATE_LIMIT",
                    "status": "FAILED",
                    "reason": "Provider rate limit encountered fetching VN30",
                    "latest_date": None,
                    "expected_date": context.data_as_of,
                    "processed": False,
                    "recoverable": is_recoverable_category("RATE_LIMIT"),
                }
                raise
            except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as exc:
                logger.error("Exception fetching VN30: %s", exc)
                context.failed_symbols.add("VN30")
                context.exclusions_map["VN30"] = {
                    "symbol": "VN30",
                    "stage": "BENCHMARK_FETCH",
                    "category": "PROVIDER_FAILURE",
                    "status": "FAILED",
                    "reason": f"Exception fetching VN30: {type(exc).__name__}",
                    "latest_date": None,
                    "expected_date": context.data_as_of,
                    "processed": False,
                    "recoverable": is_recoverable_category("PROVIDER_FAILURE"),
                }
                context.df_vn30_raw = pd.DataFrame()
                context.vn30_source = "PROVIDER_FAILURE"

        # Fetch candidate stocks
        with context.tracker.measure_stage("stock_fetch"):
            for item in context.candidate_stocks:
                sym = item["symbol"].upper()
                context.tracker.record_request(sym)
                try:
                    df_stock, tag, warns = get_hist_func(
                        sym,
                        max_retries=1,
                        use_cache_only=context.use_cache,
                        throttle_delay=context.throttle,
                        target_date=context.data_as_of if context.update_data else None,
                    )
                    context.stock_data_map[sym] = (df_stock, tag, warns)
                except ProviderRateLimitError:
                    context.failed_symbols.add(sym)
                    context.exclusions_map[sym] = {
                        "symbol": sym,
                        "stage": "STOCK_FETCH",
                        "category": "RATE_LIMIT",
                        "status": "FAILED",
                        "reason": f"Provider rate limit encountered fetching {sym}",
                        "latest_date": None,
                        "expected_date": context.data_as_of,
                        "processed": False,
                        "recoverable": is_recoverable_category("RATE_LIMIT"),
                    }
                    raise
                except (
                    RuntimeError,
                    ValueError,
                    TypeError,
                    OSError,
                    KeyError,
                    AttributeError,
                ) as exc:
                    logger.error("Exception fetching %s: %s", sym, exc)
                    context.failed_symbols.add(sym)
                    context.exclusions_map[sym] = {
                        "symbol": sym,
                        "stage": "STOCK_FETCH",
                        "category": "PROVIDER_FAILURE",
                        "status": "FAILED",
                        "reason": f"Exception fetching {sym}: {type(exc).__name__}",
                        "latest_date": None,
                        "expected_date": context.data_as_of,
                        "processed": False,
                        "recoverable": is_recoverable_category("PROVIDER_FAILURE"),
                    }
                    context.stock_data_map[sym] = (pd.DataFrame(), "PROVIDER_FAILURE", [str(exc)])


class DataValidationStage(PipelineStage):
    """Stage 2: Clean and validate OHLCV structure and temporal integrity."""

    @property
    def name(self) -> str:
        return "data_validation"

    def execute(self, context: PipelineContext) -> None:
        if context.is_historical:
            self._execute_historical(context)
            return

        # Validate VNINDEX
        df_clean_vn, vn_val = get_clean_ohlcv_data(context.df_vnindex_raw, "VNINDEX")
        context.df_vnindex_clean = df_clean_vn
        context.vnindex_val = vn_val

        if (
            context.vn_source
            in (
                "PROVIDER_FAILURE",
                "PROVIDER_ERROR",
                "EXPLICITLY_INVALID",
                "INVALID_SYMBOL",
                "INSUFFICIENT_HISTORICAL_DATA",
            )
            or df_clean_vn.empty
            or vn_val.get("status") == "INSUFFICIENT"
        ):
            context.failed_symbols.add("VNINDEX")
            cat = (
                "INSUFFICIENT_HISTORICAL_DATA"
                if (
                    context.vn_source == "INSUFFICIENT_HISTORICAL_DATA"
                    or vn_val.get("status") == "INSUFFICIENT"
                )
                else "PROVIDER_FAILURE"
            )
            context.exclusions_map["VNINDEX"] = {
                "symbol": "VNINDEX",
                "stage": "BENCHMARK_FETCH",
                "category": cat,
                "status": "FAILED",
                "reason": f"Benchmark VNINDEX check failed (source={context.vn_source}, status={vn_val.get('status')})",
                "latest_date": vn_val.get("latest_date"),
                "expected_date": None,
                "processed": False,
                "recoverable": is_recoverable_category(cat),
            }
        else:
            context.processed_symbols.add("VNINDEX")

        context.data_as_of = vn_val.get("latest_date")
        context.source_date = context.data_as_of
        context.data_source = context.vn_source if not df_clean_vn.empty else None

        # Validate VN30
        df_clean_vn30, vn30_val = get_clean_ohlcv_data(context.df_vn30_raw, "VN30")
        context.df_vn30_clean = df_clean_vn30
        context.vn30_val = vn30_val

        if (
            context.vn30_source
            in (
                "PROVIDER_FAILURE",
                "PROVIDER_ERROR",
                "EXPLICITLY_INVALID",
                "INVALID_SYMBOL",
                "INSUFFICIENT_HISTORICAL_DATA",
            )
            or df_clean_vn30.empty
            or vn30_val.get("status") == "INSUFFICIENT"
        ):
            context.failed_symbols.add("VN30")
            cat = (
                "INSUFFICIENT_HISTORICAL_DATA"
                if (
                    context.vn30_source == "INSUFFICIENT_HISTORICAL_DATA"
                    or vn30_val.get("status") == "INSUFFICIENT"
                )
                else "PROVIDER_FAILURE"
            )
            context.exclusions_map["VN30"] = {
                "symbol": "VN30",
                "stage": "BENCHMARK_FETCH",
                "category": cat,
                "status": "FAILED",
                "reason": f"Benchmark VN30 check failed (source={context.vn30_source}, status={vn30_val.get('status')})",
                "latest_date": vn30_val.get("latest_date"),
                "expected_date": context.data_as_of,
                "processed": False,
                "recoverable": is_recoverable_category(cat),
            }
        else:
            context.processed_symbols.add("VN30")

        # Validate candidate stocks
        for sym, (df_stock, tag, warns) in context.stock_data_map.items():
            df_clean_stock, stock_val = get_clean_ohlcv_data(df_stock, sym)
            context.stock_dates_map[sym] = stock_val.get("latest_date")

            if tag in ("PROVIDER_FAILURE", "PROVIDER_ERROR", "EXPLICITLY_INVALID"):
                context.failed_symbols.add(sym)
                cat = "EXPLICITLY_INVALID" if tag == "EXPLICITLY_INVALID" else "PROVIDER_FAILURE"
                context.exclusions_map[sym] = {
                    "symbol": sym,
                    "stage": "STOCK_FETCH",
                    "category": cat,
                    "status": "FAILED",
                    "reason": f"Provider tag {tag} for symbol {sym}",
                    "latest_date": context.stock_dates_map.get(sym),
                    "expected_date": context.data_as_of,
                    "processed": False,
                    "recoverable": is_recoverable_category(cat),
                }
            elif tag == "INVALID_SYMBOL":
                context.invalid_symbols.add(sym)
                context.exclusions_map[sym] = {
                    "symbol": sym,
                    "stage": "STOCK_FETCH",
                    "category": "INVALID_SYMBOL",
                    "status": "INVALID",
                    "reason": f"Invalid stock symbol {sym}",
                    "latest_date": context.stock_dates_map.get(sym),
                    "expected_date": context.data_as_of,
                    "processed": False,
                    "recoverable": is_recoverable_category("INVALID_SYMBOL"),
                }
            elif df_stock is None or df_stock.empty or df_clean_stock.empty:
                context.failed_symbols.add(sym)
                context.exclusions_map[sym] = {
                    "symbol": sym,
                    "stage": "STOCK_FETCH",
                    "category": "OTHER_VALIDATION_FAILURE",
                    "status": "FAILED",
                    "reason": f"Empty OHLCV dataset for {sym}",
                    "latest_date": context.stock_dates_map.get(sym),
                    "expected_date": context.data_as_of,
                    "processed": False,
                    "recoverable": is_recoverable_category("OTHER_VALIDATION_FAILURE"),
                }
            elif tag == "INSUFFICIENT_HISTORICAL_DATA" or stock_val.get("status") == "INSUFFICIENT":
                context.insufficient_history_symbols.add(sym)
                context.exclusions_map[sym] = {
                    "symbol": sym,
                    "stage": "STOCK_FETCH",
                    "category": "INSUFFICIENT_HISTORICAL_DATA",
                    "status": "INSUFFICIENT",
                    "reason": f"Insufficient historical sessions for {sym}",
                    "latest_date": context.stock_dates_map.get(sym),
                    "expected_date": context.data_as_of,
                    "processed": False,
                    "recoverable": is_recoverable_category("INSUFFICIENT_HISTORICAL_DATA"),
                }
            else:
                context.processed_symbols.add(sym)

        # Validate temporal integrity
        with context.tracker.measure_stage("temporal_validation"):
            temporal_res = validate_temporal_integrity(
                data_as_of=context.data_as_of,
                stock_dates_map={
                    s: context.stock_dates_map[s]
                    for s in context.processed_symbols
                    if s not in ("VNINDEX", "VN30")
                },
                reference_date=context.generated_at,
                strict_date_match=context.update_data,
            )
            context.temporal_res = temporal_res

            if not temporal_res["is_valid"]:
                logger.warning("Temporal integrity validation failure: %s", temporal_res["issues"])
                temporal_invalid_syms = (
                    temporal_res["future_symbols"]
                    | temporal_res["stale_symbols"]
                    | temporal_res["missing_date_symbols"]
                )
                for sym in temporal_invalid_syms:
                    context.processed_symbols.discard(sym)
                    context.failed_symbols.add(sym)
                    context.exclusions_map[sym] = {
                        "symbol": sym,
                        "stage": "TEMPORAL_VALIDATION",
                        "category": "TEMPORAL_INVALID",
                        "status": "FAILED",
                        "reason": f"[{sym}] Vi phạm tính toàn vẹn thời gian relative to VNINDEX data_as_of ({context.data_as_of})",
                        "latest_date": context.stock_dates_map.get(sym),
                        "expected_date": context.data_as_of,
                        "processed": False,
                        "recoverable": is_recoverable_category("TEMPORAL_INVALID"),
                    }
                    context.stock_data_map[sym] = (
                        pd.DataFrame(),
                        "EXPLICITLY_INVALID",
                        [
                            f"[{sym}] Vi phạm tính toàn vẹn thời gian relative to VNINDEX data_as_of ({context.data_as_of})"
                        ],
                    )

    def _execute_historical(self, context: PipelineContext) -> None:
        canonical_as_of = _parse_canonical_date(context.historical_data_as_of)
        context.data_as_of = canonical_as_of
        context.source_date = canonical_as_of

        with context.tracker.measure_stage("benchmark_fetch"):
            context.tracker.record_request("VNINDEX")
            df_vnindex_raw = (
                context.universe_stock_map.get("VNINDEX") if context.universe_stock_map else None
            )
            df_vnindex_as_of = get_as_of_dataset(df_vnindex_raw, canonical_as_of)
            df_vnindex_clean, vnindex_val = get_clean_ohlcv_data(df_vnindex_as_of, "VNINDEX")

            if df_vnindex_clean.empty or vnindex_val.get("latest_date") != canonical_as_of:
                raise ValueError(
                    f"Requested historical evaluation date '{canonical_as_of}' is absent from benchmark VNINDEX historical data"
                )

            context.df_vnindex_clean = df_vnindex_clean
            context.vnindex_val = vnindex_val

            df_vn30_raw = (
                context.universe_stock_map.get("VN30") if context.universe_stock_map else None
            )
            df_vn30_clean = None
            vn30_val = {"status": "INSUFFICIENT"}
            if df_vn30_raw is not None:
                context.tracker.record_request("VN30")
                df_vn30_as_of = get_as_of_dataset(df_vn30_raw, canonical_as_of)
                df_vn30_clean, vn30_val = get_clean_ohlcv_data(df_vn30_as_of, "VN30")

            context.df_vn30_clean = df_vn30_clean
            context.vn30_val = vn30_val

        clean_stock_as_of_map = {}
        seen_candidate_symbols = set()

        with context.tracker.measure_stage("stock_fetch"):
            for idx, item in enumerate(context.candidate_metadata or []):
                if not isinstance(item, dict):
                    raise TypeError(f"Candidate metadata item at index {idx} must be a dict")
                sym = item.get("symbol")
                if not sym or not isinstance(sym, str):
                    raise ValueError(
                        f"Candidate metadata item at index {idx} missing valid symbol string"
                    )

                sym_upper = sym.upper()
                context.tracker.record_request(sym_upper)
                if sym_upper in seen_candidate_symbols:
                    raise ValueError(
                        f"Duplicate candidate stock symbol '{sym_upper}' in candidate_metadata"
                    )
                seen_candidate_symbols.add(sym_upper)

                if (
                    context.universe_stock_map is None
                    or sym_upper not in context.universe_stock_map
                ):
                    raise ValueError(
                        f"Candidate stock symbol '{sym_upper}' is missing from universe_stock_map"
                    )

                df_stock_raw = context.universe_stock_map[sym_upper]
                if df_stock_raw is not None and not df_stock_raw.empty:
                    df_stock_as_of = get_as_of_dataset(df_stock_raw, canonical_as_of)
                    df_stock_clean, _stock_val = get_clean_ohlcv_data(df_stock_as_of, sym_upper)
                else:
                    df_stock_clean = pd.DataFrame()

                clean_stock_as_of_map[sym_upper] = df_stock_clean

            context.stock_data_map = {
                s: (df, "explicit_historical_input", []) for s, df in clean_stock_as_of_map.items()
            }

        with context.tracker.measure_stage("temporal_validation"):
            pass


class UniverseValidationStage(PipelineStage):
    """Stage 3: Validate completeness of universe scanning and construct universe audit."""

    @property
    def name(self) -> str:
        return "universe_validation"

    def execute(self, context: PipelineContext) -> None:
        from scripts.generate_report import build_universe_audit

        build_audit_func = _get_helper("build_universe_audit", fallback=build_universe_audit)

        if context.is_historical:
            canonical_as_of = context.data_as_of
            candidate_metadata = context.candidate_metadata or []
            context.expected_symbols = {"VNINDEX", "VN30"} | {
                item["symbol"].upper() for item in candidate_metadata
            }

            if (
                not context.df_vnindex_clean.empty
                and context.vnindex_val.get("latest_date") == canonical_as_of
            ):
                context.processed_symbols.add("VNINDEX")
            else:
                context.failed_symbols.add("VNINDEX")
                context.exclusions_map["VNINDEX"] = {
                    "symbol": "VNINDEX",
                    "stage": "BENCHMARK_FETCH",
                    "category": "INSUFFICIENT_HISTORICAL_DATA",
                    "status": "FAILED",
                    "reason": f"Benchmark VNINDEX data missing for canonical_as_of {canonical_as_of}",
                    "latest_date": context.vnindex_val.get("latest_date"),
                    "expected_date": canonical_as_of,
                    "processed": False,
                    "recoverable": False,
                }

            if (
                context.df_vn30_clean is not None
                and not context.df_vn30_clean.empty
                and context.vn30_val.get("status") != "INSUFFICIENT"
            ):
                context.processed_symbols.add("VN30")
            else:
                context.failed_symbols.add("VN30")
                context.exclusions_map["VN30"] = {
                    "symbol": "VN30",
                    "stage": "BENCHMARK_FETCH",
                    "category": "INSUFFICIENT_HISTORICAL_DATA",
                    "status": "FAILED",
                    "reason": f"Benchmark VN30 data missing or insufficient for canonical_as_of {canonical_as_of}",
                    "latest_date": context.vn30_val.get("latest_date")
                    if context.df_vn30_raw is not None
                    else None,
                    "expected_date": canonical_as_of,
                    "processed": False,
                    "recoverable": False,
                }

            for item in candidate_metadata:
                sym_upper = item["symbol"].upper()
                df_st = context.stock_data_map.get(sym_upper, (pd.DataFrame(), None, None))[0]
                if df_st is not None and not df_st.empty:
                    context.processed_symbols.add(sym_upper)
                else:
                    context.insufficient_history_symbols.add(sym_upper)
                    context.exclusions_map[sym_upper] = {
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

            context.missing_symbols = context.expected_symbols - (
                context.processed_symbols
                | context.invalid_symbols
                | context.insufficient_history_symbols
                | context.failed_symbols
            )
            for sym in context.missing_symbols:
                context.exclusions_map[sym] = {
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

            context.universe_audit = build_audit_func(
                expected_symbols=context.expected_symbols,
                processed_symbols=context.processed_symbols,
                invalid_symbols=context.invalid_symbols,
                insufficient_history_symbols=context.insufficient_history_symbols,
                failed_symbols=context.failed_symbols,
                missing_symbols=context.missing_symbols,
                exclusions_map=context.exclusions_map,
                update_data=False,
            )
            return

        context.missing_symbols = context.expected_symbols - (
            context.processed_symbols
            | context.invalid_symbols
            | context.insufficient_history_symbols
            | context.failed_symbols
        )
        for sym in context.missing_symbols:
            context.exclusions_map[sym] = {
                "symbol": sym,
                "stage": "UNIVERSE_DISCOVERY",
                "category": "UNIVERSE_INCOMPLETE",
                "status": "MISSING",
                "reason": f"Symbol {sym} missing from scan results",
                "latest_date": None,
                "expected_date": context.data_as_of,
                "processed": False,
                "recoverable": is_recoverable_category("UNIVERSE_INCOMPLETE"),
            }

        context.universe_audit = build_audit_func(
            expected_symbols=context.expected_symbols,
            processed_symbols=context.processed_symbols,
            invalid_symbols=context.invalid_symbols,
            insufficient_history_symbols=context.insufficient_history_symbols,
            failed_symbols=context.failed_symbols,
            missing_symbols=context.missing_symbols,
            exclusions_map=context.exclusions_map,
            update_data=context.update_data,
        )

        failed_stage = context.universe_audit["failed_stage"]
        pipeline_status = context.universe_audit["status"]
        diagnostics_list = context.universe_audit["diagnostics"]

        if context.update_data and (
            context.expected_symbols != (context.processed_symbols | context.invalid_symbols)
            or context.failed_symbols
            or context.insufficient_history_symbols
            or context.missing_symbols
            or not context.temporal_res.get("is_valid", True)
        ):
            err_msg = (
                f"Incomplete universe scan in update mode: stage={failed_stage}, "
                f"status={pipeline_status}. "
                f"Expected: {len(context.expected_symbols)}, Processed: {len(context.processed_symbols)}, "
                f"Invalid: {len(context.invalid_symbols)}, Insufficient History: {len(context.insufficient_history_symbols)}, "
                f"Failed: {len(context.failed_symbols)}, Missing: {len(context.missing_symbols)}. "
                f"Temporal issues: {context.temporal_res.get('issues', [])}. "
                f"Processed symbols: {sorted(context.processed_symbols)}. "
                f"Invalid symbols: {sorted(context.invalid_symbols)}. "
                f"Insufficient history symbols: {sorted(context.insufficient_history_symbols)}. "
                f"Failed symbols: {sorted(context.failed_symbols)}. "
                f"Missing symbols: {sorted(context.missing_symbols)}."
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
            exc.universe_audit = context.universe_audit
            raise exc


class MarketAnalysisStage(PipelineStage):
    """Stage 4: Compute market breadth and detect overall market regime."""

    @property
    def name(self) -> str:
        return "market_analysis"

    def execute(self, context: PipelineContext) -> None:
        detect_regime_func = _get_helper("detect_market_regime", fallback=detect_market_regime)

        if context.is_historical:
            with context.tracker.measure_stage("market_calculation"):
                bullish_count = 0
                valid_breadth_denom = 0
                for df_st, _, _ in context.stock_data_map.values():
                    if not df_st.empty and len(df_st) >= 20:
                        valid_breadth_denom += 1
                        c = df_st["close"].iloc[-1]
                        ma20 = df_st["close"].tail(20).mean()
                        if c > ma20:
                            bullish_count += 1

                context.breadth_ratio = (
                    round(bullish_count / valid_breadth_denom, 2)
                    if valid_breadth_denom > 0
                    else 0.50
                )

            with context.tracker.measure_stage("regime_calculation"):
                context.final_market_regime = detect_regime_func(
                    df_vnindex=context.df_vnindex_clean,
                    df_vn30=context.df_vn30_clean
                    if context.vn30_val.get("status") != "INSUFFICIENT"
                    else None,
                    breadth_ratio=context.breadth_ratio,
                )
            return

        with context.tracker.measure_stage("market_calculation"):
            bullish_count = 0
            valid_breadth_denom = 0
            for sym_dict in context.candidate_stocks:
                s_name = sym_dict["symbol"]
                if s_name in context.processed_symbols:
                    df_st, _, _ = context.stock_data_map[s_name]
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

            context.breadth_ratio = (
                round(bullish_count / valid_breadth_denom, 2) if valid_breadth_denom > 0 else 0.50
            )

        with context.tracker.measure_stage("regime_calculation"):
            context.final_market_regime = detect_regime_func(
                df_vnindex=context.df_vnindex_clean,
                df_vn30=context.df_vn30_clean
                if context.vn30_val.get("status") != "INSUFFICIENT"
                else None,
                breadth_ratio=context.breadth_ratio,
            )


class SignalRecommendationGenerationStage(PipelineStage):
    """Stage 5: Generate quantitative stock recommendations and signals."""

    @property
    def name(self) -> str:
        return "signal_recommendation_generation"

    def execute(self, context: PipelineContext) -> None:
        generate_rec_func = _get_helper("generate_recommendation", fallback=generate_recommendation)

        if context.is_historical:
            with context.tracker.measure_stage("recommendation_calculation"):
                scanned_recs = []
                for item in context.candidate_metadata or []:
                    sym = item["symbol"].upper()
                    comp = item["companyName"]
                    sec = item["sector"]
                    ex = item.get("exchange", "HOSE")

                    df_stock_clean = context.stock_data_map.get(sym, (pd.DataFrame(), None, None))[
                        0
                    ]

                    rec = generate_rec_func(
                        symbol=sym,
                        company_name=comp,
                        sector=sec,
                        exchange=ex,
                        df_stock=df_stock_clean,
                        market_regime_info=context.final_market_regime,
                        df_vnindex=context.df_vnindex_clean,
                        data_as_of=context.data_as_of,
                        data_source=context.data_source,
                    )
                    scanned_recs.append(rec)
                context.scanned_recs = scanned_recs
            return

        with context.tracker.measure_stage("recommendation_calculation"):
            scanned_recs = []
            for item in context.candidate_stocks:
                sym = item["symbol"]
                comp = item["companyName"]
                sec = item["sector"]
                ex = item.get("exchange", "HOSE")

                df_stock, tag, _ = context.stock_data_map[sym]
                if sym in context.processed_symbols:
                    df_clean_stock, _ = get_clean_ohlcv_data(df_stock, sym)
                    df_stock_input = df_clean_stock
                else:
                    df_stock_input = pd.DataFrame()

                rec = generate_rec_func(
                    symbol=sym,
                    company_name=comp,
                    sector=sec,
                    exchange=ex,
                    df_stock=df_stock_input,
                    market_regime_info=context.final_market_regime,
                    df_vnindex=context.df_vnindex_clean,
                    data_as_of=context.data_as_of,
                    data_source=tag if not df_stock_input.empty else None,
                )
                scanned_recs.append(rec)
            context.scanned_recs = scanned_recs


class RiskTradePlanStage(PipelineStage):
    """Stage 6: Normalize risk/liquidity scores and assemble summary payloads."""

    @property
    def name(self) -> str:
        return "risk_trade_plan"

    def execute(self, context: PipelineContext) -> None:
        normalize_liq_func = _get_helper(
            "normalize_universe_liquidity_scores", fallback=normalize_universe_liquidity_scores
        )

        with context.tracker.measure_stage("risk_calculation"):
            context.scanned_recs = normalize_liq_func(
                context.scanned_recs, market_regime=context.final_market_regime
            )

        context.scanned_recs_dicts = [
            r.to_dict() if hasattr(r, "to_dict") else r for r in context.scanned_recs
        ]

        buy_cnt = sum(1 for r in context.scanned_recs if r["action"] == "BUY")
        watch_cnt = sum(1 for r in context.scanned_recs if r["action"] == "WATCH")
        hold_cnt = sum(1 for r in context.scanned_recs if r["action"] == "HOLD")
        sell_cnt = sum(1 for r in context.scanned_recs if r["action"] == "SELL")
        avoid_cnt = sum(1 for r in context.scanned_recs if r["action"] == "AVOID")

        context.summary = {
            "total_scanned": len(context.scanned_recs),
            "buy_count": buy_cnt,
            "watch_count": watch_cnt,
            "hold_count": hold_cnt,
            "sell_count": sell_cnt,
            "avoid_count": avoid_cnt,
        }

        if context.is_historical:
            u_info = {
                "universe_type": "HISTORICAL_SNAPSHOT",
                "universe_size": len(context.candidate_metadata or []),
            }
        else:
            u_info = context.universe_info

        context.recommendations_payload = {
            "schema_version": "2.0",
            "signal_model_version": SIGNAL_MODEL_VERSION,
            "generated_at": context.generated_at,
            "data_as_of": context.data_as_of,
            "source_date": context.source_date,
            "data_source": context.data_source,
            "universe_info": u_info,
            "market": context.final_market_regime,
            "summary": context.summary,
            "recommendations": context.scanned_recs_dicts,
        }

        context.market_payload = {
            "data_as_of": context.data_as_of,
            "source_date": context.source_date,
            "generated_at": context.generated_at,
            "data_source": context.data_source,
            "universe_info": u_info,
            "market": context.final_market_regime,
            "summary": context.summary,
        }

        context.history_payload = context.recommendations_payload


class PerformanceStage(PipelineStage):
    """Stage 7: Collect performance metrics and audit timing diagnostics."""

    @property
    def name(self) -> str:
        return "performance"

    def execute(self, context: PipelineContext) -> None:
        context.pipeline_elapsed = time.perf_counter() - context.tracker.t_pipeline_start
        pipeline_status = context.universe_audit.get("status", "SUCCESS")

        context.performance_data = context.tracker.get_performance_payload(
            pipeline_elapsed=context.pipeline_elapsed,
            pipeline_status=pipeline_status,
        )

        context.universe_audit["performance"] = context.performance_data


class MonitoringStage(PipelineStage):
    """Stage 8: Evaluate production monitoring and check final payload integrity."""

    @property
    def name(self) -> str:
        return "monitoring"

    def execute(self, context: PipelineContext) -> None:
        from scripts.generate_report import (
            load_history_index,
            validate_final_payload_integrity,
        )

        val_integrity_func = _get_helper(
            "validate_final_payload_integrity", fallback=validate_final_payload_integrity
        )

        if context.is_historical:
            with context.tracker.measure_stage("payload_validation"):
                val_integrity_func(context.recommendations_payload, schema=None)
                val_integrity_func(context.market_payload, schema=None)

            context.pipeline_elapsed = time.perf_counter() - context.tracker.t_pipeline_start
            context.performance_data = context.tracker.get_performance_payload(
                pipeline_elapsed=context.pipeline_elapsed,
                pipeline_status=context.universe_audit.get("status", "SUCCESS"),
            )
            context.universe_audit["performance"] = context.performance_data
            return

        eval_monitoring_func = _get_helper(
            "evaluate_production_monitoring", fallback=evaluate_production_monitoring
        )

        with context.tracker.measure_stage("monitoring"):
            in_mem_artifacts = {
                "recommendations.json": context.recommendations_payload,
                "market.json": context.market_payload,
            }
            data_as_of_peek = context.recommendations_payload.get("data_as_of")
            if data_as_of_peek:
                in_mem_artifacts[f"history/{data_as_of_peek}.json"] = context.history_payload
                index_path = os.path.join(context.generated_dir, "history", "index.json")
                try:
                    load_index_func = _get_helper("load_history_index", fallback=load_history_index)
                    idx_data = load_index_func(index_path)
                    dates = idx_data.get("dates", []) if isinstance(idx_data, dict) else []
                except ValueError, TypeError, OSError, AttributeError:
                    dates = []
                if data_as_of_peek not in dates:
                    dates = list(dates) + [data_as_of_peek]
                    dates.sort(reverse=True)
                in_mem_artifacts["history/index.json"] = {
                    "last_updated": context.generated_at,
                    "total_reports": len(dates),
                    "dates": dates,
                }

            context.monitoring_result = eval_monitoring_func(
                generated_dir=context.generated_dir,
                recommendations_payload=context.recommendations_payload,
                market_payload=context.market_payload,
                df_vnindex=context.df_vnindex_clean,
                df_vn30=context.df_vn30_clean,
                universe_audit=context.universe_audit,
                in_memory_artifacts=in_mem_artifacts,
            )

        context.monitoring_dict = context.monitoring_result.to_dict()

        with context.tracker.measure_stage("payload_validation"):
            val_integrity_func(context.recommendations_payload, schema=None)
            val_integrity_func(context.market_payload, schema=None)
            if context.history_payload is not context.recommendations_payload:
                val_integrity_func(context.history_payload, schema=None)
            val_integrity_func(context.monitoring_dict, schema=None)

        context.pipeline_elapsed = time.perf_counter() - context.tracker.t_pipeline_start
        context.performance_data = context.tracker.get_performance_payload(
            pipeline_elapsed=context.pipeline_elapsed,
            pipeline_status=context.universe_audit.get("status", "SUCCESS"),
        )

        if "metrics" not in context.monitoring_dict or not isinstance(
            context.monitoring_dict["metrics"], dict
        ):
            context.monitoring_dict["metrics"] = {}

        context.monitoring_dict["metrics"]["universe_audit"] = context.universe_audit
        context.monitoring_dict["metrics"]["performance"] = context.performance_data
        context.universe_audit["performance"] = context.performance_data


class ArtifactPublishingStage(PipelineStage):
    """Stage 9: Build artifact set and atomically publish to generated directory."""

    @property
    def name(self) -> str:
        return "artifact_publishing"

    def execute(self, context: PipelineContext) -> None:
        if (
            context.publish_artifacts
            and context.monitoring_result is not None
            and context.monitoring_result.overall_status == "FAIL"
        ):
            logger.error(
                "Production update rejected due to monitoring failure. All artifacts preserved byte-for-byte."
            )
            raise SystemExit(1)

        from scripts.generate_report import (
            load_history_index,
            publish_artifacts_atomically,
        )

        load_index_func = _get_helper("load_history_index", fallback=load_history_index)
        publish_func = _get_helper(
            "publish_artifacts_atomically", fallback=publish_artifacts_atomically
        )

        data_as_of = context.data_as_of

        if context.is_historical:
            if not context.publish_artifacts:
                return

            index_path = os.path.join(context.generated_dir, "history", "index.json")
            index_data = load_index_func(index_path)
            history_dates = index_data.get("dates", [])
            if data_as_of and data_as_of not in history_dates:
                history_dates = list(history_dates)
                history_dates.append(data_as_of)
                history_dates.sort(reverse=True)
            index_payload = {
                "last_updated": context.generated_at,
                "total_reports": len(history_dates),
                "dates": history_dates,
            }

            historical_artifacts = {
                os.path.join("history", f"{data_as_of}.json"): context.history_payload,
                os.path.join("history", "index.json"): index_payload,
            }
            context.artifacts_to_publish = historical_artifacts
            publish_func(historical_artifacts, target_dir=context.generated_dir)
            return

        if not context.publish_artifacts:
            return

        context.artifacts_to_publish = {
            "recommendations.json": context.recommendations_payload,
            "market.json": context.market_payload,
            "monitoring.json": context.monitoring_dict,
        }

        if data_as_of:
            context.artifacts_to_publish[os.path.join("history", f"{data_as_of}.json")] = (
                context.history_payload
            )
            index_path = os.path.join(context.generated_dir, "history", "index.json")
            index_data = load_index_func(index_path)
            history_dates = index_data.get("dates", [])
            if data_as_of not in history_dates:
                history_dates = list(history_dates)
                history_dates.append(data_as_of)
                history_dates.sort(reverse=True)
            index_payload = {
                "last_updated": context.generated_at,
                "total_reports": len(history_dates),
                "dates": history_dates,
            }
            context.artifacts_to_publish[os.path.join("history", "index.json")] = index_payload

        publish_func(context.artifacts_to_publish, target_dir=context.generated_dir)


__all__ = [
    "PipelineStage",
    "DataAcquisitionStage",
    "DataValidationStage",
    "UniverseValidationStage",
    "MarketAnalysisStage",
    "SignalRecommendationGenerationStage",
    "RiskTradePlanStage",
    "PerformanceStage",
    "MonitoringStage",
    "ArtifactPublishingStage",
]
