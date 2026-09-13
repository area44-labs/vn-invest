"""Generate Report Script for VN Invest v2.

Command line usage:
    python scripts/generate_report.py
    python scripts/generate_report.py --update

Outputs:
    generated/recommendations.json
    generated/market.json
    generated/history/index.json
    generated/history/YYYY-MM-DD.json
    (Synchronized under public/generated/ for static Vite frontend)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

import jsonschema

# Add repository root to path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.risk import normalize_universe_liquidity_scores
from scripts.lib.vietnam_market import UniverseProvider, get_historical_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "recommendations.schema.json")
GENERATED_DIR = os.path.join(ROOT_DIR, "generated")
PUBLIC_GENERATED_DIR = os.path.join(ROOT_DIR, "public", "generated")


def save_json_files(relative_path: str, data: dict):
    """Save JSON data atomically to both generated/ and public/generated/."""
    path1 = os.path.join(GENERATED_DIR, relative_path)
    path2 = os.path.join(PUBLIC_GENERATED_DIR, relative_path)

    for p in [path1, path2]:
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
    source_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    generated_at = datetime.now(timezone.utc).isoformat()
    use_cache = not update_data

    provider = UniverseProvider()
    candidate_stocks = provider.candidates
    universe_info = provider.get_info()

    logger.info("Step 1: Fetching VN-Index benchmark & stock universe EOD history...")
    df_vnindex, _vn_source, _vn_warns = get_historical_data(
        "VNINDEX", max_retries=2 if update_data else 1, use_cache_only=use_cache
    )
    df_vn30, _, _ = get_historical_data(
        "VN30", max_retries=2 if update_data else 1, use_cache_only=use_cache
    )

    stock_data_map = {}
    bullish_count = 0

    for idx, item in enumerate(candidate_stocks):
        sym = item["symbol"]
        df_stock, tag, warns = get_historical_data(sym, max_retries=1, use_cache_only=use_cache)
        stock_data_map[sym] = (df_stock, tag, warns)

        # Pre-breadth check: price above MA20
        if not df_stock.empty and len(df_stock) >= 20:
            c = df_stock["close"].iloc[-1]
            ma20 = df_stock["close"].tail(20).mean()
            if c > ma20:
                bullish_count += 1

    logger.info("Step 2: Calculating Market Breadth...")
    breadth_ratio = round(bullish_count / len(candidate_stocks), 2) if candidate_stocks else 0.50

    logger.info("Step 3: Calculating Final Market Regime...")
    final_market_regime = detect_market_regime(
        df_vnindex=df_vnindex, df_vn30=df_vn30, breadth_ratio=breadth_ratio
    )

    logger.info("Step 4: Generating Stock Recommendations using Final Market Regime...")
    scanned_recs = []
    for item in candidate_stocks:
        sym = item["symbol"]
        comp = item["companyName"]
        sec = item["sector"]
        ex = item.get("exchange", "HOSE")

        df_stock, _, _ = stock_data_map[sym]

        rec = generate_recommendation(
            symbol=sym,
            company_name=comp,
            sector=sec,
            exchange=ex,
            df_stock=df_stock,
            market_regime_info=final_market_regime,
            df_vnindex=df_vnindex,
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
        "generated_at": generated_at,
        "source_date": source_date,
        "universe_info": universe_info,
        "market": final_market_regime,
        "summary": summary,
        "recommendations": scanned_recs,
    }

    market_payload = {
        "source_date": source_date,
        "generated_at": generated_at,
        "universe_info": universe_info,
        "market": final_market_regime,
        "summary": summary,
    }

    history_payload = recommendations_payload

    return recommendations_payload, market_payload, history_payload


def update_history_index(source_date: str):
    """Maintain history/index.json with list of available historical dates."""
    index_path = os.path.join(GENERATED_DIR, "history", "index.json")
    history_dates = []

    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
                history_dates = index_data.get("dates", [])
        except Exception:  # noqa: BLE001
            history_dates = []

    if source_date not in history_dates:
        history_dates.append(source_date)
        history_dates.sort(reverse=True)

    index_payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_reports": len(history_dates),
        "dates": history_dates,
    }

    save_json_files(os.path.join("history", "index.json"), index_payload)


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

    source_date = recs_data["source_date"]

    # Save outputs
    save_json_files("recommendations.json", recs_data)
    save_json_files("market.json", market_data)
    save_json_files(os.path.join("history", f"{source_date}.json"), history_data)
    update_history_index(source_date)

    logger.info("Report generation complete!")
    logger.info("Outputs written to generated/ and public/generated/:")
    logger.info("  - recommendations.json (%d items)", len(recs_data["recommendations"]))
    logger.info("  - market.json (Regime: %s)", recs_data["market"]["regime"])
    logger.info("  - history/%s.json", source_date)
    logger.info("  - history/index.json")


if __name__ == "__main__":
    main()
