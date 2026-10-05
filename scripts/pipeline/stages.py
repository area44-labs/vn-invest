"""Pipeline Stages for VN Invest production orchestration."""

import abc
import logging
import os
import time

import pandas as pd

from scripts.data.acquisition import MarketDataAcquirer, RawMarketDataPayload
from scripts.data.models import CanonicalMarketData
from scripts.data.normalization import normalize_raw_market_data
from scripts.data.providers import VnstockMarketProvider
from scripts.data.validation import validate_canonical_market_data
from scripts.data_provider import ProviderRateLimitError
from scripts.lib.backtest import _parse_canonical_date, get_as_of_dataset
from scripts.lib.config import DEFAULT_UPDATE_THROTTLE_DELAY
from scripts.lib.monitoring import evaluate_production_monitoring
from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.risk import normalize_universe_liquidity_scores
from scripts.domain.universe import Universe
from scripts.lib.vietnam_market import (
    UniverseProvider,
    validate_temporal_integrity,
)
from scripts.pipeline.context import PipelineContext
from scripts.pipeline.publishing import load_history_index, publish_artifacts_atomically
from scripts.pipeline.validation import load_schema, validate_final_payload_integrity

logger = logging.getLogger(__name__)


class PipelineStage(abc.ABC):
    """Abstract base class for all pipeline stages."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Name of the pipeline stage."""

    @abc.abstractmethod
    def execute(self, context: PipelineContext) -> None:
        """Execute stage logic against the provided PipelineContext."""


class DataAcquisitionStage(PipelineStage):
    """Stage 1: Acquire raw market data for benchmarks and candidate stock universe via MarketDataAcquirer."""

    @property
    def name(self) -> str:
        return "data_acquisition"

    def execute(self, context: PipelineContext) -> None:
        if context.is_historical:
            return

        VnstockMarketProvider.reset_global_call_history()
        context.provider = UniverseProvider()
        u = context.provider.get_universe() if hasattr(context.provider, "get_universe") else None
        if isinstance(u, Universe):
            universe = u
        else:
            cands = context.provider.candidates if hasattr(context.provider, "candidates") else []
            if not isinstance(cands, (list, tuple, set)):
                cands = []
            universe = Universe.from_candidates(candidates=cands)

        if universe.universe_size == 0:
            raise RuntimeError(
                "Candidate universe is empty. Cannot generate report on empty universe."
            )

        context.set_universe(universe)
        context.throttle = DEFAULT_UPDATE_THROTTLE_DELAY if context.update_data else 0.0

        acquirer = MarketDataAcquirer(
            provider=context.market_data_provider or VnstockMarketProvider()
        )

        # Fetch VNINDEX benchmark payload
        with context.tracker.measure_stage("benchmark_fetch"):
            context.tracker.record_request("VNINDEX")
            try:
                payload_vnindex = acquirer.acquire(
                    "VNINDEX",
                    max_retries=2 if context.update_data else 1,
                    throttle_delay=context.throttle,
                )
                context.raw_vnindex_payload = payload_vnindex
                context.df_vnindex_raw = payload_vnindex.raw_df
                context.vn_source = payload_vnindex.source_tag
            except ProviderRateLimitError:
                context.add_exclusion(
                    symbol="VNINDEX",
                    stage="BENCHMARK_FETCH",
                    category="RATE_LIMIT",
                    status="FAILED",
                    reason="Provider rate limit encountered fetching VNINDEX",
                )
                raise
            except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as exc:
                logger.error("Exception fetching VNINDEX: %s", exc)
                context.add_exclusion(
                    symbol="VNINDEX",
                    stage="BENCHMARK_FETCH",
                    category="PROVIDER_FAILURE",
                    status="FAILED",
                    reason=f"Exception fetching VNINDEX: {type(exc).__name__}",
                )
                context.raw_vnindex_payload = RawMarketDataPayload(
                    symbol="VNINDEX",
                    raw_df=pd.DataFrame(),
                    provider_name=acquirer._get_provider().provider_name,
                    source_tag="PROVIDER_FAILURE",
                    error=str(exc),
                )
                context.df_vnindex_raw = pd.DataFrame()
                context.vn_source = "PROVIDER_FAILURE"

            # Fetch VN30 benchmark payload
            context.tracker.record_request("VN30")
            try:
                payload_vn30 = acquirer.acquire(
                    "VN30",
                    max_retries=2 if context.update_data else 1,
                    throttle_delay=context.throttle,
                )
                context.raw_vn30_payload = payload_vn30
                context.df_vn30_raw = payload_vn30.raw_df
                context.vn30_source = payload_vn30.source_tag
            except ProviderRateLimitError:
                context.add_exclusion(
                    symbol="VN30",
                    stage="BENCHMARK_FETCH",
                    category="RATE_LIMIT",
                    status="FAILED",
                    reason="Provider rate limit encountered fetching VN30",
                    expected_date=context.data_as_of,
                )
                raise
            except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as exc:
                logger.error("Exception fetching VN30: %s", exc)
                context.add_exclusion(
                    symbol="VN30",
                    stage="BENCHMARK_FETCH",
                    category="PROVIDER_FAILURE",
                    status="FAILED",
                    reason=f"Exception fetching VN30: {type(exc).__name__}",
                    expected_date=context.data_as_of,
                )
                context.raw_vn30_payload = RawMarketDataPayload(
                    symbol="VN30",
                    raw_df=pd.DataFrame(),
                    provider_name=acquirer._get_provider().provider_name,
                    source_tag="PROVIDER_FAILURE",
                    error=str(exc),
                )
                context.df_vn30_raw = pd.DataFrame()
                context.vn30_source = "PROVIDER_FAILURE"

        # Fetch candidate stocks raw payloads
        with context.tracker.measure_stage("stock_fetch"):
            for item in context.candidate_stocks:
                sym = item["symbol"].upper()
                context.tracker.record_request(sym)
                try:
                    payload_stock = acquirer.acquire(
                        sym,
                        max_retries=1,
                        throttle_delay=context.throttle,
                        target_date=context.data_as_of if context.update_data else None,
                    )
                    context.raw_stock_payloads[sym] = payload_stock
                    context.stock_data_map[sym] = (
                        payload_stock.raw_df,
                        payload_stock.source_tag,
                        list(payload_stock.warnings),
                    )
                except ProviderRateLimitError:
                    context.add_exclusion(
                        symbol=sym,
                        stage="STOCK_FETCH",
                        category="RATE_LIMIT",
                        status="FAILED",
                        reason=f"Provider rate limit encountered fetching {sym}",
                        expected_date=context.data_as_of,
                    )
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
                    context.add_exclusion(
                        symbol=sym,
                        stage="STOCK_FETCH",
                        category="PROVIDER_FAILURE",
                        status="FAILED",
                        reason=f"Exception fetching {sym}: {type(exc).__name__}",
                        expected_date=context.data_as_of,
                    )
                    err_payload = RawMarketDataPayload(
                        symbol=sym,
                        raw_df=pd.DataFrame(),
                        provider_name="vnstock",
                        source_tag="PROVIDER_FAILURE",
                        error=str(exc),
                    )
                    context.raw_stock_payloads[sym] = err_payload
                    context.stock_data_map[sym] = (pd.DataFrame(), "PROVIDER_FAILURE", [str(exc)])


class DataValidationStage(PipelineStage):
    """Stage 2: Clean and validate canonical OHLCV structure and temporal integrity via validate_canonical_market_data."""

    @property
    def name(self) -> str:
        return "data_validation"

    def execute(self, context: PipelineContext) -> None:
        if context.is_historical:
            self._execute_historical(context)
            return

        # 1. Normalize and Validate VNINDEX via canonical boundary
        raw_vn_payload = context.raw_vnindex_payload or RawMarketDataPayload(
            symbol="VNINDEX",
            raw_df=context.df_vnindex_raw,
            source_tag=context.vn_source or "REAL_DATA",
        )
        cmd_vn = normalize_raw_market_data(raw_vn_payload)
        v_vn = validate_canonical_market_data(cmd_vn, reference_date=context.generated_at)

        context.canonical_vnindex = v_vn
        df_clean_vn = v_vn.to_df()
        vn_val = v_vn.data_quality.to_dict() if v_vn.data_quality else {}
        context.df_vnindex_clean = df_clean_vn
        context.vnindex_val = vn_val
        context.vn_source = v_vn.source_tag

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
            cat = (
                "INSUFFICIENT_HISTORICAL_DATA"
                if (
                    context.vn_source == "INSUFFICIENT_HISTORICAL_DATA"
                    or vn_val.get("status") == "INSUFFICIENT"
                )
                else "PROVIDER_FAILURE"
            )
            context.add_exclusion(
                symbol="VNINDEX",
                stage="BENCHMARK_FETCH",
                category=cat,
                status="FAILED",
                reason=f"Benchmark VNINDEX check failed (source={context.vn_source}, status={vn_val.get('status')})",
                latest_date=vn_val.get("latest_date"),
            )
        else:
            context.processed_symbols.add("VNINDEX")

        context.data_as_of = vn_val.get("latest_date") or v_vn.data_as_of
        context.source_date = context.data_as_of
        context.data_source = context.vn_source if not df_clean_vn.empty else None

        # 2. Normalize and Validate VN30 via canonical boundary
        raw_vn30_payload = context.raw_vn30_payload or RawMarketDataPayload(
            symbol="VN30",
            raw_df=context.df_vn30_raw,
            source_tag=context.vn30_source or "REAL_DATA",
        )
        cmd_vn30 = normalize_raw_market_data(raw_vn30_payload)
        v_vn30 = validate_canonical_market_data(cmd_vn30, reference_date=context.generated_at)

        context.canonical_vn30 = v_vn30
        df_clean_vn30 = v_vn30.to_df()
        vn30_val = v_vn30.data_quality.to_dict() if v_vn30.data_quality else {}
        context.df_vn30_clean = df_clean_vn30
        context.vn30_val = vn30_val
        context.vn30_source = v_vn30.source_tag

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
            cat = (
                "INSUFFICIENT_HISTORICAL_DATA"
                if (
                    context.vn30_source == "INSUFFICIENT_HISTORICAL_DATA"
                    or vn30_val.get("status") == "INSUFFICIENT"
                )
                else "PROVIDER_FAILURE"
            )
            context.add_exclusion(
                symbol="VN30",
                stage="BENCHMARK_FETCH",
                category=cat,
                status="FAILED",
                reason=f"Benchmark VN30 check failed (source={context.vn30_source}, status={vn30_val.get('status')})",
                latest_date=vn30_val.get("latest_date"),
                expected_date=context.data_as_of,
            )
        else:
            context.processed_symbols.add("VN30")

        # 3. Normalize and Validate Candidate Stock Universe via canonical boundary
        for item in context.candidate_stocks:
            sym = item["symbol"].upper()
            raw_st_payload = context.raw_stock_payloads.get(sym) or RawMarketDataPayload(
                symbol=sym,
                raw_df=context.stock_data_map.get(sym, (pd.DataFrame(), None, []))[0],
                source_tag=context.stock_data_map.get(sym, (pd.DataFrame(), "REAL_DATA", []))[1]
                or "REAL_DATA",
            )
            cmd_st = normalize_raw_market_data(
                raw_st_payload, explicit_data_as_of=context.data_as_of
            )
            v_st = validate_canonical_market_data(cmd_st, reference_date=context.generated_at)

            context.canonical_stock_map[sym] = v_st
            df_clean_stock = v_st.to_df()
            stock_val = v_st.data_quality.to_dict() if v_st.data_quality else {}
            tag = v_st.source_tag

            context.stock_dates_map[sym] = stock_val.get("latest_date") or v_st.data_as_of
            context.stock_data_map[sym] = (
                df_clean_stock,
                tag,
                list(v_st.data_quality.issues) if v_st.data_quality else [],
            )

            if tag in ("PROVIDER_FAILURE", "PROVIDER_ERROR", "EXPLICITLY_INVALID"):
                cat = "EXPLICITLY_INVALID" if tag == "EXPLICITLY_INVALID" else "PROVIDER_FAILURE"
                context.add_exclusion(
                    symbol=sym,
                    stage="STOCK_FETCH",
                    category=cat,
                    status="FAILED",
                    reason=f"Provider tag {tag} for symbol {sym}",
                    latest_date=context.stock_dates_map.get(sym),
                    expected_date=context.data_as_of,
                )
            elif tag == "INVALID_SYMBOL":
                context.add_exclusion(
                    symbol=sym,
                    stage="STOCK_FETCH",
                    category="INVALID_SYMBOL",
                    status="INVALID",
                    reason=f"Invalid stock symbol {sym}",
                    latest_date=context.stock_dates_map.get(sym),
                    expected_date=context.data_as_of,
                )
            elif df_clean_stock.empty:
                context.add_exclusion(
                    symbol=sym,
                    stage="STOCK_FETCH",
                    category="OTHER_VALIDATION_FAILURE",
                    status="FAILED",
                    reason=f"Empty OHLCV dataset for {sym}",
                    latest_date=context.stock_dates_map.get(sym),
                    expected_date=context.data_as_of,
                )
            elif tag == "INSUFFICIENT_HISTORICAL_DATA" or stock_val.get("status") == "INSUFFICIENT":
                context.add_exclusion(
                    symbol=sym,
                    stage="STOCK_FETCH",
                    category="INSUFFICIENT_HISTORICAL_DATA",
                    status="INSUFFICIENT",
                    reason=f"Insufficient historical sessions for {sym}",
                    latest_date=context.stock_dates_map.get(sym),
                    expected_date=context.data_as_of,
                )
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
                    context.add_exclusion(
                        symbol=sym,
                        stage="TEMPORAL_VALIDATION",
                        category="TEMPORAL_INVALID",
                        status="FAILED",
                        reason=f"[{sym}] Vi phạm tính toàn vẹn thời gian relative to VNINDEX data_as_of ({context.data_as_of})",
                        latest_date=context.stock_dates_map.get(sym),
                        expected_date=context.data_as_of,
                    )
                    context.canonical_stock_map[sym] = CanonicalMarketData(
                        symbol=sym,
                        records=(),
                        data_as_of=context.data_as_of,
                        source_tag="EXPLICITLY_INVALID",
                    )
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

        if context.universe is None and context.candidate_metadata:
            u_hist = Universe.from_candidates(
                candidates=context.candidate_metadata,
                universe_type="HISTORICAL_SNAPSHOT",
                benchmarks=("VNINDEX", "VN30"),
            )
            context.set_universe(u_hist)

        with context.tracker.measure_stage("benchmark_fetch"):
            context.tracker.record_request("VNINDEX")
            df_vnindex_raw = (
                context.universe_stock_map.get("VNINDEX") if context.universe_stock_map else None
            )
            df_vnindex_as_of = get_as_of_dataset(df_vnindex_raw, canonical_as_of)
            payload_vnindex = RawMarketDataPayload(
                symbol="VNINDEX", raw_df=df_vnindex_as_of, source_tag="REAL_DATA"
            )
            v_vnindex = validate_canonical_market_data(normalize_raw_market_data(payload_vnindex))
            context.canonical_vnindex = v_vnindex
            df_vnindex_clean = v_vnindex.to_df()
            vnindex_val = v_vnindex.data_quality.to_dict() if v_vnindex.data_quality else {}

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
                payload_vn30 = RawMarketDataPayload(
                    symbol="VN30", raw_df=df_vn30_as_of, source_tag="REAL_DATA"
                )
                v_vn30 = validate_canonical_market_data(normalize_raw_market_data(payload_vn30))
                context.canonical_vn30 = v_vn30
                df_vn30_clean = v_vn30.to_df()
                vn30_val = v_vn30.data_quality.to_dict() if v_vn30.data_quality else {}

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
                    payload_st = RawMarketDataPayload(
                        symbol=sym_upper, raw_df=df_stock_as_of, source_tag="REAL_DATA"
                    )
                    v_st = validate_canonical_market_data(
                        normalize_raw_market_data(payload_st, explicit_data_as_of=canonical_as_of)
                    )
                    context.canonical_stock_map[sym_upper] = v_st
                    df_stock_clean = v_st.to_df()
                else:
                    v_st = CanonicalMarketData(
                        symbol=sym_upper,
                        records=(),
                        data_as_of=canonical_as_of,
                        source_tag="PROVIDER_FAILURE",
                    )
                    context.canonical_stock_map[sym_upper] = v_st
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
        if context.is_historical:
            canonical_as_of = context.data_as_of
            if context.universe is None:
                u_hist = Universe.from_candidates(
                    candidates=context.candidate_metadata or [],
                    universe_type="HISTORICAL_SNAPSHOT",
                    benchmarks=("VNINDEX", "VN30"),
                )
                context.set_universe(u_hist)

            if (
                context.df_vnindex_clean is not None
                and not context.df_vnindex_clean.empty
                and context.vnindex_val.get("latest_date") == canonical_as_of
            ):
                context.processed_symbols.add("VNINDEX")
            else:
                context.add_exclusion(
                    symbol="VNINDEX",
                    stage="BENCHMARK_FETCH",
                    category="INSUFFICIENT_HISTORICAL_DATA",
                    status="FAILED",
                    reason=f"Benchmark VNINDEX data missing for canonical_as_of {canonical_as_of}",
                    latest_date=context.vnindex_val.get("latest_date"),
                    expected_date=canonical_as_of,
                )

            if (
                context.df_vn30_clean is not None
                and not context.df_vn30_clean.empty
                and context.vn30_val.get("status") != "INSUFFICIENT"
            ):
                context.processed_symbols.add("VN30")
            else:
                context.add_exclusion(
                    symbol="VN30",
                    stage="BENCHMARK_FETCH",
                    category="INSUFFICIENT_HISTORICAL_DATA",
                    status="FAILED",
                    reason=f"Benchmark VN30 data missing or insufficient for canonical_as_of {canonical_as_of}",
                    latest_date=context.vn30_val.get("latest_date")
                    if context.df_vn30_raw is not None
                    else None,
                    expected_date=canonical_as_of,
                )

            for item in context.candidate_stocks:
                sym_upper = item["symbol"].upper()
                df_st = context.stock_data_map.get(sym_upper, (pd.DataFrame(), None, None))[0]
                if df_st is not None and not df_st.empty:
                    context.processed_symbols.add(sym_upper)
                else:
                    context.add_exclusion(
                        symbol=sym_upper,
                        stage="STOCK_FETCH",
                        category="INSUFFICIENT_HISTORICAL_DATA",
                        status="INSUFFICIENT",
                        reason=f"Historical data missing or insufficient for candidate {sym_upper} at {canonical_as_of}",
                        expected_date=canonical_as_of,
                    )

            context.missing_symbols = context.expected_symbols - (
                context.processed_symbols
                | context.invalid_symbols
                | context.insufficient_history_symbols
                | context.failed_symbols
            )
            for sym in context.missing_symbols:
                context.add_exclusion(
                    symbol=sym,
                    stage="UNIVERSE_DISCOVERY",
                    category="UNIVERSE_INCOMPLETE",
                    status="MISSING",
                    reason=f"Symbol {sym} missing from historical snapshot",
                    expected_date=canonical_as_of,
                )

            context.update_universe_audit()
            return

        context.missing_symbols = context.expected_symbols - (
            context.processed_symbols
            | context.invalid_symbols
            | context.insufficient_history_symbols
            | context.failed_symbols
        )
        for sym in context.missing_symbols:
            context.add_exclusion(
                symbol=sym,
                stage="UNIVERSE_DISCOVERY",
                category="UNIVERSE_INCOMPLETE",
                status="MISSING",
                reason=f"Symbol {sym} missing from scan results",
                expected_date=context.data_as_of,
            )

        context.update_universe_audit()

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
        if context.is_historical:
            with context.tracker.measure_stage("market_calculation"):
                bullish_count = 0
                valid_breadth_denom = 0
                for df_st, _, _ in context.stock_data_map.values():
                    if df_st is not None and not df_st.empty and len(df_st) >= 20:
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
                context.final_market_regime = detect_market_regime(
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
                    cmd_st = context.canonical_stock_map.get(s_name)
                    if (
                        cmd_st
                        and cmd_st.data_quality
                        and cmd_st.data_quality.status == "SUFFICIENT"
                    ):
                        df_c_st = cmd_st.to_df()
                        if not df_c_st.empty and len(df_c_st) >= 20:
                            valid_breadth_denom += 1
                            c = df_c_st["close"].iloc[-1]
                            ma20 = df_c_st["close"].tail(20).mean()
                            if c > ma20:
                                bullish_count += 1

            context.breadth_ratio = (
                round(bullish_count / valid_breadth_denom, 2) if valid_breadth_denom > 0 else 0.50
            )

        with context.tracker.measure_stage("regime_calculation"):
            context.final_market_regime = detect_market_regime(
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
        if context.is_historical:
            with context.tracker.measure_stage("recommendation_calculation"):
                scanned_recs = []
                for item in context.candidate_stocks:
                    sym = item["symbol"].upper()
                    comp = item["companyName"]
                    sec = item["sector"]
                    ex = item.get("exchange", "HOSE")

                    df_stock_clean = context.stock_data_map.get(sym, (pd.DataFrame(), None, None))[
                        0
                    ]

                    rec = generate_recommendation(
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

                cmd_st = context.canonical_stock_map.get(sym)
                tag = cmd_st.source_tag if cmd_st else "PROVIDER_FAILURE"

                if (
                    sym in context.processed_symbols
                    and cmd_st
                    and cmd_st.data_quality
                    and cmd_st.data_quality.status == "SUFFICIENT"
                ):
                    df_stock_input = cmd_st.to_df()
                else:
                    df_stock_input = pd.DataFrame()

                rec = generate_recommendation(
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
        with context.tracker.measure_stage("risk_calculation"):
            context.scanned_recs = normalize_universe_liquidity_scores(
                context.scanned_recs, market_regime=context.final_market_regime
            )

        context.build_payloads()


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
        schema = load_schema()

        if context.is_historical:
            with context.tracker.measure_stage("payload_validation"):
                validate_final_payload_integrity(context.recommendations_payload, schema=schema)
                validate_final_payload_integrity(context.market_payload, schema=None)

            context.pipeline_elapsed = time.perf_counter() - context.tracker.t_pipeline_start
            context.performance_data = context.tracker.get_performance_payload(
                pipeline_elapsed=context.pipeline_elapsed,
                pipeline_status=context.universe_audit.get("status", "SUCCESS"),
            )
            context.universe_audit["performance"] = context.performance_data
            return

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
                    idx_data = load_history_index(index_path)
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

            context.monitoring_result = evaluate_production_monitoring(
                generated_dir=context.generated_dir,
                recommendations_payload=context.recommendations_payload,
                market_payload=context.market_payload,
                reference_date=context.reference_date,
                df_vnindex=context.df_vnindex_clean,
                df_vn30=context.df_vn30_clean,
                universe_audit=context.universe_audit,
                in_memory_artifacts=in_mem_artifacts,
            )

        context.monitoring_dict = context.monitoring_result.to_dict()

        with context.tracker.measure_stage("payload_validation"):
            validate_final_payload_integrity(context.recommendations_payload, schema=schema)
            validate_final_payload_integrity(context.market_payload, schema=None)
            if context.history_payload is not context.recommendations_payload:
                validate_final_payload_integrity(context.history_payload, schema=schema)
            validate_final_payload_integrity(context.monitoring_dict, schema=None)

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
            logger.error("Production update rejected due to monitoring failure.")
            failed_checks = [c for c in context.monitoring_result.checks if c.status == "FAIL"]
            logger.error("Failed monitoring check count: %d", len(failed_checks))
            for c in failed_checks:
                logger.error(
                    "  - Failed check: %s | status=%s | measured_value=%s | expected_condition=%s | reason=%s",
                    c.check_name,
                    c.status,
                    c.measured_value,
                    c.expected_condition,
                    c.message,
                )
            logger.error("All artifacts preserved byte-for-byte.")
            raise SystemExit(1)

        data_as_of = context.data_as_of

        if context.is_historical:
            index_path = os.path.join(context.generated_dir, "history", "index.json")
            index_data = load_history_index(index_path)
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
            if context.publish_artifacts:
                publish_artifacts_atomically(historical_artifacts, target_dir=context.generated_dir)
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
            index_data = load_history_index(index_path)
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
        else:
            logger.warning(
                "data_as_of is None. Skipping creation of historical date JSON artifact and history index update."
            )

        if context.publish_artifacts:
            publish_artifacts_atomically(
                context.artifacts_to_publish, target_dir=context.generated_dir
            )


__all__ = [
    "ArtifactPublishingStage",
    "DataAcquisitionStage",
    "DataValidationStage",
    "MarketAnalysisStage",
    "MonitoringStage",
    "PerformanceStage",
    "PipelineStage",
    "RiskTradePlanStage",
    "SignalRecommendationGenerationStage",
    "UniverseValidationStage",
]
