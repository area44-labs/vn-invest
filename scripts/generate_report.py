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
import os
from datetime import UTC, datetime
from typing import Any

import jsonschema
import pandas as pd

from scripts.data_provider import ProviderRateLimitError
from scripts.lib.backtest import _parse_canonical_date, get_as_of_dataset
from scripts.lib.monitoring import evaluate_production_monitoring
from scripts.lib.recommendation import SIGNAL_MODEL_VERSION, generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.risk import normalize_universe_liquidity_scores
from scripts.lib.vietnam_market import (
    DEFAULT_UPDATE_THROTTLE_DELAY,
    UniverseProvider,
    get_clean_ohlcv_data,
    get_historical_data,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

    throttle = DEFAULT_UPDATE_THROTTLE_DELAY if update_data else 0.0

    expected_symbols = {"VNINDEX", "VN30"} | {
        item["symbol"].upper()
        for item in candidate_stocks
        if isinstance(item, dict) and item.get("symbol")
    }
    processed_symbols = set()
    invalid_symbols = set()
    insufficient_history_symbols = set()
    failed_symbols = set()

    logger.info("Step 1: Fetching VN-Index benchmark & stock universe EOD history...")

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
        else:
            processed_symbols.add("VNINDEX")
    except ProviderRateLimitError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Exception fetching VNINDEX: %s", exc)
        failed_symbols.add("VNINDEX")
        df_vnindex_raw = pd.DataFrame()
        df_vnindex_clean, vnindex_val = get_clean_ohlcv_data(df_vnindex_raw, "VNINDEX")

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
        else:
            processed_symbols.add("VN30")
    except ProviderRateLimitError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Exception fetching VN30: %s", exc)
        failed_symbols.add("VN30")
        df_vn30_raw = pd.DataFrame()
        df_vn30_clean, vn30_val = get_clean_ohlcv_data(df_vn30_raw, "VN30")

    stock_data_map = {}
    bullish_count = 0

    for idx, item in enumerate(candidate_stocks):
        sym = item["symbol"].upper()
        try:
            df_stock, tag, warns = get_historical_data(
                sym, max_retries=1, use_cache_only=use_cache, throttle_delay=throttle
            )
            stock_data_map[sym] = (df_stock, tag, warns)

            df_clean_stock, _ = get_clean_ohlcv_data(df_stock, sym)

            if tag in ("PROVIDER_FAILURE", "PROVIDER_ERROR"):
                failed_symbols.add(sym)
            elif tag in ("EXPLICITLY_INVALID", "INVALID_SYMBOL"):
                invalid_symbols.add(sym)
            elif tag == "INSUFFICIENT_HISTORICAL_DATA":
                insufficient_history_symbols.add(sym)
            elif df_stock is None or df_stock.empty or df_clean_stock.empty:
                failed_symbols.add(sym)
            else:
                processed_symbols.add(sym)

            # Pre-breadth check: price above MA20 using clean OHLCV data
            if not df_clean_stock.empty and len(df_clean_stock) >= 20:
                c = df_clean_stock["close"].iloc[-1]
                ma20 = df_clean_stock["close"].tail(20).mean()
                if c > ma20:
                    bullish_count += 1
        except ProviderRateLimitError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Exception fetching %s: %s", sym, exc)
            failed_symbols.add(sym)
            stock_data_map[sym] = (pd.DataFrame(), "PROVIDER_FAILURE", [str(exc)])

    missing_symbols = expected_symbols - (
        processed_symbols | invalid_symbols | insufficient_history_symbols | failed_symbols
    )

    if update_data and (
        expected_symbols != (processed_symbols | invalid_symbols)
        or failed_symbols
        or insufficient_history_symbols
        or missing_symbols
    ):
        raise RuntimeError(
            f"Incomplete universe scan in update mode: validation failed. "
            f"Expected: {len(expected_symbols)}, Processed: {len(processed_symbols)}, "
            f"Invalid: {len(invalid_symbols)}, Insufficient History: {len(insufficient_history_symbols)}, "
            f"Failed: {len(failed_symbols)}, Missing: {len(missing_symbols)}. "
            f"Processed symbols: {sorted(processed_symbols)}. "
            f"Invalid symbols: {sorted(invalid_symbols)}. "
            f"Insufficient history symbols: {sorted(insufficient_history_symbols)}. "
            f"Failed symbols: {sorted(failed_symbols)}. "
            f"Missing symbols: {sorted(missing_symbols)}."
        )

    # Market-level data_as_of is derived strictly from validated VN-Index benchmark OHLCV dataset.
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
    universe_stock_map: dict[str, pd.DataFrame],
    df_vnindex: pd.DataFrame,
    df_vn30: pd.DataFrame | None = None,
    candidate_metadata: list[dict] | None = None,
    data_source: str = "explicit_historical_input",
    reference_date: str | None = None,
) -> PipelineResult:
    """Generate a point-in-time historical report for explicit target date T.

    Fail-Closed Principles:
    - data_as_of must be explicit canonical YYYY-MM-DD.
    - Historical datasets are strictly sliced <= T via get_as_of_dataset.
    - Future rows (> T), unsorted dates, duplicate dates, or malformed OHLCV cause immediate failure.
    - The target evaluation date T must exist in df_vnindex (raises ValueError if absent).
    - Reuses production quantitative scoring, market regime detection, risk, and trade plan functions.
    """
    canonical_as_of = _parse_canonical_date(data_as_of)
    generated_at = reference_date if reference_date is not None else datetime.now(UTC).isoformat()

    if candidate_metadata is None or not isinstance(candidate_metadata, list):
        raise TypeError("candidate_metadata must be a list of candidate stock dicts")
    if not candidate_metadata:
        raise ValueError("candidate_metadata cannot be empty")

    if not isinstance(universe_stock_map, dict):
        raise TypeError("universe_stock_map must be a dictionary mapping symbols to DataFrames")

    # Slice benchmark datasets strictly <= T (anti-lookahead)
    df_vnindex_as_of = get_as_of_dataset(df_vnindex, canonical_as_of)
    df_vnindex_clean, vnindex_val = get_clean_ohlcv_data(df_vnindex_as_of, "VNINDEX")

    if df_vnindex_clean.empty or vnindex_val.get("latest_date") != canonical_as_of:
        raise ValueError(
            f"Requested historical evaluation date '{canonical_as_of}' is absent from benchmark VNINDEX historical data"
        )

    df_vn30_clean = None
    vn30_val = {"status": "INSUFFICIENT"}
    if df_vn30 is not None:
        df_vn30_as_of = get_as_of_dataset(df_vn30, canonical_as_of)
        df_vn30_clean, vn30_val = get_clean_ohlcv_data(df_vn30_as_of, "VN30")

    bullish_count = 0
    clean_stock_as_of_map = {}

    for idx, item in enumerate(candidate_metadata):
        if not isinstance(item, dict):
            raise TypeError(f"Candidate metadata item at index {idx} must be a dict")
        sym = item.get("symbol")
        if not sym or not isinstance(sym, str):
            raise ValueError(f"Candidate metadata item at index {idx} missing valid symbol string")

        sym_upper = sym.upper()
        if sym_upper not in universe_stock_map:
            raise ValueError(
                f"Candidate stock symbol '{sym_upper}' is missing from universe_stock_map"
            )

        df_stock_raw = universe_stock_map[sym_upper]
        df_stock_as_of = get_as_of_dataset(df_stock_raw, canonical_as_of)
        df_stock_clean, _ = get_clean_ohlcv_data(df_stock_as_of, sym_upper)

        clean_stock_as_of_map[sym_upper] = df_stock_clean

        if not df_stock_clean.empty and len(df_stock_clean) >= 20:
            c = df_stock_clean["close"].iloc[-1]
            ma20 = df_stock_clean["close"].tail(20).mean()
            if c > ma20:
                bullish_count += 1

    breadth_ratio = (
        round(bullish_count / len(candidate_metadata), 2) if candidate_metadata else 0.50
    )

    final_market_regime = detect_market_regime(
        df_vnindex=df_vnindex_clean,
        df_vn30=df_vn30_clean if vn30_val["status"] != "INSUFFICIENT" else None,
        breadth_ratio=breadth_ratio,
    )

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
            data_source=data_source,
        )
        scanned_recs.append(rec)

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
        "total_candidates": len(candidate_metadata),
        "scanned_at": generated_at,
        "historical_report": True,
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

    return PipelineResult(
        recommendations_payload,
        market_payload,
        history_payload,
        df_vnindex=df_vnindex_clean,
        df_vn30=df_vn30_clean if vn30_val["status"] != "INSUFFICIENT" else None,
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
        try:
            pipeline_res = run_pipeline(update_data=args.update)
        except (ProviderRateLimitError, RuntimeError) as exc:
            logger.error("Data pipeline halted: %s", exc)
            logger.error("Existing generated report files have been preserved and not overwritten.")
            raise SystemExit(1) from exc

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
