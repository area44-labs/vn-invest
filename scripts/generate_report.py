"""Generate Report Script for VN Invest v2.

Command line usage:
    python scripts/generate_report.py
    python scripts/generate_report.py --update

Outputs:
    generated/recommendations.json
    generated/market.json
    generated/history/index.json
    generated/history/YYYY-MM-DD.json
"""

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

import jsonschema

# Add repository root to path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.lib.backtest import _parse_canonical_date, get_as_of_dataset
from scripts.lib.monitoring import evaluate_production_monitoring
from scripts.lib.recommendation import SIGNAL_MODEL_VERSION, generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.risk import normalize_universe_liquidity_scores
from scripts.lib.vietnam_market import (
    UniverseProvider,
    get_clean_ohlcv_data,
    get_historical_data,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "recommendations.schema.json")
GENERATED_DIR = os.path.join(ROOT_DIR, "generated")


def canonicalize_report_for_reproducibility(report_payload: dict) -> dict:
    """Canonicalize a report payload for deterministic comparison by normalizing runtime metadata.

    Replaces runtime-dependent metadata (such as 'generated_at') with a fixed placeholder
    while leaving all quantitative fields (signals, market regime, confidence, trade plans, etc.) unchanged.
    """
    if not isinstance(report_payload, dict):
        raise TypeError(f"report_payload must be a dict, got {type(report_payload).__name__}")

    cloned = json.loads(json.dumps(report_payload))
    cloned["generated_at"] = "2000-01-01T00:00:00+00:00"
    return cloned


def save_json_files(relative_path: str, data: dict):
    """Save JSON data atomically to generated/."""
    p = os.path.join(GENERATED_DIR, relative_path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp_p = f"{p}.tmp"
    with open(tmp_p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_p, p)


def load_schema():
    """Load JSON Schema Draft 2020-12 from schemas/recommendations.schema.json."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class PipelineResult(tuple):
    """Pipeline result tuple preserving 3-element unpacking backward compatibility."""

    def __new__(
        cls,
        recs_data: dict,
        market_data: dict,
        history_data: dict,
        df_vnindex: Any = None,
        df_vn30: Any = None,
    ):
        obj = super().__new__(cls, (recs_data, market_data, history_data))
        obj.df_vnindex = df_vnindex
        obj.df_vn30 = df_vn30
        return obj


def run_pipeline(update_data: bool = False) -> tuple[dict, dict, dict]:
    """Execute market data pipeline following strict dependency order:

    1. Fetch VN-Index benchmark & stock universe EOD history
    2. Calculate Market Breadth across universe
    3. Calculate Final Market Regime
    4. Generate Stock Recommendations using the Final Market Regime
    5. Compute Universe Percentile Liquidity Scores
    """
    generated_at = datetime.now(UTC).isoformat()
    use_cache = not update_data

    provider = UniverseProvider()
    candidate_stocks = provider.candidates
    universe_info = provider.get_info()

    logger.info("Step 1: Fetching VN-Index benchmark & stock universe EOD history...")
    df_vnindex_raw, vn_source, _vn_warns = get_historical_data(
        "VNINDEX", max_retries=2 if update_data else 1, use_cache_only=use_cache
    )
    df_vn30_raw, _, _ = get_historical_data(
        "VN30", max_retries=2 if update_data else 1, use_cache_only=use_cache
    )

    # All quantitative consumers must receive clean OHLCV data.
    # Raw provider data may be retained for diagnostics only.
    df_vnindex_clean, vnindex_val = get_clean_ohlcv_data(df_vnindex_raw, "VNINDEX")
    df_vn30_clean, vn30_val = get_clean_ohlcv_data(df_vn30_raw, "VN30")

    stock_data_map = {}
    bullish_count = 0

    for idx, item in enumerate(candidate_stocks):
        sym = item["symbol"]
        df_stock, tag, warns = get_historical_data(sym, max_retries=1, use_cache_only=use_cache)
        stock_data_map[sym] = (df_stock, tag, warns)

        # Pre-breadth check: price above MA20 using clean OHLCV data
        df_clean_stock, _ = get_clean_ohlcv_data(df_stock, sym)
        if not df_clean_stock.empty and len(df_clean_stock) >= 20:
            c = df_clean_stock["close"].iloc[-1]
            ma20 = df_clean_stock["close"].tail(20).mean()
            if c > ma20:
                bullish_count += 1

    # Market-level data_as_of is derived strictly from validated VN-Index benchmark OHLCV dataset.
    # Invariant: data_as_of == latest usable VNINDEX trading date
    data_as_of = vnindex_val.get("latest_date")
    source_date = data_as_of  # Backward compatibility alias
    data_source = vn_source if not df_vnindex_clean.empty else None

    logger.info("Step 2: Calculating Market Breadth...")
    breadth_ratio = round(bullish_count / len(candidate_stocks), 2) if candidate_stocks else 0.50

    logger.info("Step 3: Calculating Final Market Regime...")
    final_market_regime = detect_market_regime(
        df_vnindex=df_vnindex_clean,
        df_vn30=df_vn30_clean if vn30_val["status"] != "INSUFFICIENT" else None,
        breadth_ratio=breadth_ratio,
    )

    logger.info("Step 4: Generating Stock Recommendations using Final Market Regime...")
    scanned_recs = []
    for item in candidate_stocks:
        sym = item["symbol"]
        comp = item["companyName"]
        sec = item["sector"]
        ex = item.get("exchange", "HOSE")

        df_stock, tag, _ = stock_data_map[sym]

        rec = generate_recommendation(
            symbol=sym,
            company_name=comp,
            sector=sec,
            exchange=ex,
            df_stock=df_stock,
            market_regime_info=final_market_regime,
            df_vnindex=df_vnindex_clean,
            data_source=tag if not df_stock.empty else None,
        )
        scanned_recs.append(rec)

    logger.info("Step 5: Computing Universe Percentile Liquidity Scores...")
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

    return PipelineResult(
        recommendations_payload,
        market_payload,
        history_payload,
        df_vnindex=df_vnindex_clean,
        df_vn30=df_vn30_clean if vn30_val["status"] != "INSUFFICIENT" else None,
    )


def generate_historical_report(
    data_as_of: str,
    universe_stock_map: dict[str, Any],
    df_vnindex: Any,
    candidate_metadata: list[dict],
    df_vn30: Any | None = None,
    generated_at: str | None = None,
    data_source: str | None = "historical_reproduction",
) -> PipelineResult:
    """Generate a historical quantitative report timestamped strictly as of evaluation date T.

    Point-In-Time & Anti-Lookahead Guarantees:
    - Explicit canonical YYYY-MM-DD date required.
    - All quantitative inputs (VNINDEX, VN30, stock history, breadth) are sliced <= data_as_of
      using get_as_of_dataset(), failing closed if data_as_of is missing, or if dates are duplicate,
      unsorted, or physically contain future observations prior to T.
    - Historical universe and candidate metadata must be provided explicitly (no silent fallbacks).
    - Reuses production market regime detection, recommendation engine, and universe liquidity normalization.
    """
    target_date_str = _parse_canonical_date(data_as_of)

    if generated_at is None:
        generated_at = datetime.now(UTC).isoformat()

    if not universe_stock_map or not isinstance(universe_stock_map, dict):
        raise ValueError("universe_stock_map cannot be empty or None")

    if df_vnindex is None or df_vnindex.empty:
        raise ValueError("df_vnindex cannot be empty or None")

    # Validate candidate_metadata strictly fail-closed
    if (
        candidate_metadata is None
        or not isinstance(candidate_metadata, list)
        or len(candidate_metadata) == 0
    ):
        raise ValueError(
            "candidate_metadata must be a non-empty list of historical candidate metadata objects"
        )

    seen_symbols = set()
    for idx, item in enumerate(candidate_metadata):
        if not isinstance(item, dict):
            raise TypeError(
                f"candidate_metadata item at index {idx} must be a dict, got {type(item).__name__}"
            )

        sym = item.get("symbol")
        comp = item.get("companyName")
        sec = item.get("sector")

        if not sym or not isinstance(sym, str) or not sym.strip():
            raise ValueError(
                f"candidate_metadata item at index {idx} missing valid 'symbol' string"
            )
        if not comp or not isinstance(comp, str) or not comp.strip():
            raise ValueError(
                f"candidate_metadata item at index {idx} missing valid 'companyName' string"
            )
        if not sec or not isinstance(sec, str) or not sec.strip():
            raise ValueError(
                f"candidate_metadata item at index {idx} missing valid 'sector' string"
            )

        sym_upper = sym.strip().upper()
        if sym_upper in seen_symbols:
            raise ValueError(f"Duplicate symbol '{sym_upper}' in candidate_metadata")
        seen_symbols.add(sym_upper)

    universe_symbols = {str(k).strip().upper() for k in universe_stock_map}
    if seen_symbols != universe_symbols:
        missing_in_universe = seen_symbols - universe_symbols
        missing_in_metadata = universe_symbols - seen_symbols
        errs = []
        if missing_in_universe:
            errs.append(
                f"symbols in metadata but missing in universe_stock_map: {sorted(missing_in_universe)}"
            )
        if missing_in_metadata:
            errs.append(
                f"symbols in universe_stock_map but missing in metadata: {sorted(missing_in_metadata)}"
            )
        raise ValueError(
            f"Symbol mismatch between candidate_metadata and universe_stock_map: {'; '.join(errs)}"
        )

    # 1. Slice VNINDEX benchmark data <= target_date_str
    df_vnindex_as_of = get_as_of_dataset(df_vnindex, target_date_str)
    df_vnindex_clean, vnindex_val = get_clean_ohlcv_data(df_vnindex_as_of, "VNINDEX")
    if df_vnindex_clean.empty or vnindex_val["status"] == "INSUFFICIENT":
        raise ValueError(
            f"Insufficient or invalid benchmark clean OHLCV data for VNINDEX at '{target_date_str}'"
        )

    # 2. Slice VN30 benchmark data <= target_date_str (if provided)
    df_vn30_clean = None
    if df_vn30 is not None:
        if df_vn30.empty:
            raise ValueError("Supplied df_vn30 DataFrame is empty")
        df_vn30_as_of = get_as_of_dataset(df_vn30, target_date_str)
        df_vn30_clean, vn30_val = get_clean_ohlcv_data(df_vn30_as_of, "VN30")
        if vn30_val["status"] == "INSUFFICIENT":
            df_vn30_clean = None

    candidates = candidate_metadata
    universe_info = {
        "universe_type": "HISTORICAL_REPRODUCTION",
        "universe_size": len(candidates),
    }

    # 3. Slice stock data and calculate point-in-time Market Breadth
    stock_as_of_map = {}
    bullish_count = 0

    for item in candidates:
        sym = item["symbol"]
        df_stock = universe_stock_map.get(sym)
        if df_stock is None or df_stock.empty:
            raise ValueError(
                f"Historical OHLCV data for symbol '{sym}' is missing from universe_stock_map"
            )

        df_stock_as_of = get_as_of_dataset(df_stock, target_date_str)
        df_clean_stock, _ = get_clean_ohlcv_data(df_stock_as_of, sym)
        stock_as_of_map[sym] = df_stock_as_of

        if not df_clean_stock.empty and len(df_clean_stock) >= 20:
            c = df_clean_stock["close"].iloc[-1]
            ma20 = df_clean_stock["close"].tail(20).mean()
            if c > ma20:
                bullish_count += 1

    breadth_ratio = round(bullish_count / len(candidates), 2) if candidates else 0.50

    # 4. Calculate Final Market Regime
    final_market_regime = detect_market_regime(
        df_vnindex=df_vnindex_clean,
        df_vn30=df_vn30_clean,
        breadth_ratio=breadth_ratio,
    )

    # 5. Generate Stock Recommendations using Final Market Regime
    scanned_recs = []
    for item in candidates:
        sym = item["symbol"]
        comp = item["companyName"]
        sec = item["sector"]
        ex = item.get("exchange", "HOSE")

        df_stock_as_of = stock_as_of_map[sym]

        rec = generate_recommendation(
            symbol=sym,
            company_name=comp,
            sector=sec,
            exchange=ex,
            df_stock=df_stock_as_of,
            market_regime_info=final_market_regime,
            df_vnindex=df_vnindex_clean,
            data_as_of=target_date_str,
            data_source=data_source,
        )
        scanned_recs.append(rec)

    # 6. Compute Universe Percentile Liquidity Scores
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
        "data_as_of": target_date_str,
        "source_date": target_date_str,
        "data_source": data_source,
        "universe_info": universe_info,
        "market": final_market_regime,
        "summary": summary,
        "recommendations": scanned_recs,
    }

    market_payload = {
        "data_as_of": target_date_str,
        "source_date": target_date_str,
        "generated_at": generated_at,
        "data_source": data_source,
        "universe_info": universe_info,
        "market": final_market_regime,
        "summary": summary,
    }

    history_payload = recommendations_payload

    return PipelineResult(
        recommendations_payload,
        market_payload,
        history_payload,
        df_vnindex=df_vnindex_clean,
        df_vn30=df_vn30_clean,
    )


def load_history_index(index_path: str | None = None) -> dict:
    """Load and validate history index file (history/index.json).

    Fail-Closed Semantics:
    - Missing file (FileNotFoundError): returns empty initialized index {"dates": []}.
    - Malformed JSON (JSONDecodeError): raises ValueError with file context.
    - Valid JSON but invalid structure (non-dict root, missing or non-list 'dates', or non-string items): raises ValueError.
    - Filesystem/read errors (PermissionError, OSError): propagates/wraps with context.
    """
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
    args = parser.parse_args()

    schema = load_schema()

    if args.as_of:
        target_date = _parse_canonical_date(args.as_of)
        logger.info("Starting historical report generation for as-of date: %s...", target_date)

        hist_file = os.path.join(GENERATED_DIR, "history", f"{target_date}.json")
        if not os.path.exists(hist_file):
            raise ValueError(
                f"No legitimate historical universe snapshot found for date '{target_date}' at '{hist_file}'. "
                "Cannot generate historical report without an explicit historical candidate universe snapshot."
            )

        try:
            with open(hist_file, "r", encoding="utf-8") as f:
                hist_payload = json.load(f)
        except Exception as err:
            raise ValueError(
                f"Failed to read historical universe snapshot '{hist_file}': {err}"
            ) from err

        hist_recs = hist_payload.get("recommendations")
        if not isinstance(hist_recs, list) or not hist_recs:
            raise ValueError(
                f"Historical snapshot '{hist_file}' contains no valid recommendations list for universe metadata."
            )

        candidate_stocks = []
        for idx, r in enumerate(hist_recs):
            if not isinstance(r, dict):
                raise TypeError(
                    f"Historical recommendation item at index {idx} in '{hist_file}' must be a dict"
                )
            sym = r.get("symbol")
            comp = r.get("company_name")
            sec = r.get("sector")
            ex = r.get("exchange", "HOSE")
            if not sym or not comp or not sec:
                raise ValueError(
                    f"Historical recommendation item at index {idx} in '{hist_file}' missing required symbol, company_name, or sector"
                )
            candidate_stocks.append(
                {
                    "symbol": sym,
                    "companyName": comp,
                    "sector": sec,
                    "exchange": ex,
                }
            )

        use_cache = not args.update

        df_vnindex_raw, vn_source, _ = get_historical_data(
            "VNINDEX", max_retries=2 if args.update else 1, use_cache_only=use_cache
        )
        df_vn30_raw, _, _ = get_historical_data(
            "VN30", max_retries=2 if args.update else 1, use_cache_only=use_cache
        )

        stock_data_map = {}
        for item in candidate_stocks:
            sym = item["symbol"]
            df_stock, _, _ = get_historical_data(sym, max_retries=1, use_cache_only=use_cache)
            stock_data_map[sym] = df_stock

        pipeline_res = generate_historical_report(
            data_as_of=target_date,
            universe_stock_map=stock_data_map,
            df_vnindex=df_vnindex_raw,
            df_vn30=df_vn30_raw,
            candidate_metadata=candidate_stocks,
            data_source=vn_source if not df_vnindex_raw.empty else None,
        )

        recs_data, _, history_data = pipeline_res

        logger.info("Validating historical recommendations payload against JSON Schema...")
        jsonschema.validate(instance=recs_data, schema=schema)
        logger.info("JSON Schema validation passed successfully!")

        save_json_files(os.path.join("history", f"{target_date}.json"), history_data)
        update_history_index(target_date)

        logger.info("Historical report generation complete!")
        logger.info("Outputs written to generated/history:")
        logger.info(
            "  - history/%s.json (%d items)", target_date, len(recs_data["recommendations"])
        )
        logger.info("  - history/index.json")
    else:
        logger.info("Starting VN Invest Report Generator v2 (update=%s)...", args.update)
        pipeline_res = run_pipeline(update_data=args.update)
        recs_data, market_data, history_data = pipeline_res
        df_vnindex_clean = pipeline_res.df_vnindex
        df_vn30_clean = pipeline_res.df_vn30

        logger.info("Validating recommendations payload against JSON Schema Draft 2020-12...")
        jsonschema.validate(instance=recs_data, schema=schema)
        logger.info("JSON Schema validation passed successfully!")

        data_as_of = recs_data.get("data_as_of")

        save_json_files("recommendations.json", recs_data)
        save_json_files("market.json", market_data)

        if data_as_of:
            save_json_files(os.path.join("history", f"{data_as_of}.json"), history_data)
            update_history_index(data_as_of)
        else:
            logger.warning(
                "data_as_of is None. Skipping creation of historical date JSON artifact and history index update."
            )

        logger.info("Report generation complete!")
        logger.info("Outputs written to generated/:")
        logger.info("  - recommendations.json (%d items)", len(recs_data["recommendations"]))
        logger.info("  - market.json (Regime: %s)", recs_data["market"]["regime"])
        if data_as_of:
            logger.info("  - history/%s.json", data_as_of)
            logger.info("  - history/index.json")

        logger.info("Executing production pipeline monitoring...")
        monitoring_result = evaluate_production_monitoring(
            generated_dir=GENERATED_DIR,
            recommendations_payload=recs_data,
            market_payload=market_data,
            df_vnindex=df_vnindex_clean,
            df_vn30=df_vn30_clean,
        )
        save_json_files("monitoring.json", monitoring_result.to_dict())
        logger.info(
            "Production monitoring complete! Overall status: %s", monitoring_result.overall_status
        )
        logger.info("  - monitoring.json")


if __name__ == "__main__":
    main()
