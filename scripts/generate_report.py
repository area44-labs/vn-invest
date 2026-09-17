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

import jsonschema

# Add repository root to path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

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

    return recommendations_payload, market_payload, history_payload


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
    args = parser.parse_args()

    logger.info("Starting VN Invest Report Generator v2 (update=%s)...", args.update)

    recs_data, market_data, history_data = run_pipeline(update_data=args.update)

    # Validate against Schema
    schema = load_schema()
    logger.info("Validating recommendations payload against JSON Schema Draft 2020-12...")
    jsonschema.validate(instance=recs_data, schema=schema)
    logger.info("JSON Schema validation passed successfully!")

    data_as_of = recs_data.get("data_as_of")

    # Save outputs
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

    # Run production monitoring and save monitoring.json artifact
    logger.info("Executing production pipeline monitoring...")
    monitoring_result = evaluate_production_monitoring(
        generated_dir=GENERATED_DIR,
        recommendations_payload=recs_data,
        market_payload=market_data,
        reference_date=data_as_of,
    )
    save_json_files("monitoring.json", monitoring_result.to_dict())
    logger.info(
        "Production monitoring complete! Overall status: %s", monitoring_result.overall_status
    )
    logger.info("  - monitoring.json")


if __name__ == "__main__":
    main()
