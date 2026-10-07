"""CLI entry point for VN Invest v2 report generator."""

import argparse
import logging
import os
from typing import Any

import pandas as pd

from scripts.data_provider import ProviderRateLimitError
from scripts.domain import PipelineResult
from scripts.lib.backtest import _parse_canonical_date
from scripts.lib.recommendation import SIGNAL_MODEL_VERSION, generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.risk import normalize_universe_liquidity_scores
from scripts.lib.vietnam_market import (
    UniverseProvider,
    get_clean_ohlcv_data,
    get_historical_data,
    validate_temporal_integrity,
)
from scripts.monitoring import (
    evaluate_performance_regression,
    evaluate_production_monitoring,
    evaluate_provider_budget,
    load_performance_schema,
    validate_performance_payload,
)
from scripts.monitoring.models import is_recoverable_category
from scripts.pipeline import (
    GENERATED_DIR,
    PERFORMANCE_SCHEMA_PATH,
    ROOT_DIR,
    SCHEMA_PATH,
    ArtifactLock,
    ArtifactLockError,
    ArtifactTransaction,
    ArtifactTransactionError,
    PerformanceTracker,
    ProductionPipeline,
    build_universe_audit,
    find_payload_integrity_issues,
    generate_historical_report,
    load_history_index,
    load_schema,
    publish_artifacts_atomically,
    recover_interrupted_publish,
    recover_transaction_state,
    run_pipeline,
    save_json_files,
    update_history_index,
    validate_final_payload_integrity,
    validate_journal_metadata,
)
from scripts.pipeline.constants import DEFAULT_UPDATE_THROTTLE_DELAY

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_UPDATE_THROTTLE_DELAY",
    "GENERATED_DIR",
    "PERFORMANCE_SCHEMA_PATH",
    "ROOT_DIR",
    "SCHEMA_PATH",
    "SIGNAL_MODEL_VERSION",
    "ArtifactLock",
    "ArtifactLockError",
    "ArtifactTransaction",
    "ArtifactTransactionError",
    "PerformanceTracker",
    "PipelineResult",
    "ProductionPipeline",
    "UniverseProvider",
    "build_universe_audit",
    "canonicalize_report_for_reproducibility",
    "detect_market_regime",
    "evaluate_performance_regression",
    "evaluate_production_monitoring",
    "evaluate_provider_budget",
    "find_payload_integrity_issues",
    "generate_historical_report",
    "generate_recommendation",
    "get_clean_ohlcv_data",
    "get_historical_data",
    "is_recoverable_category",
    "load_historical_ohlcv",
    "load_history_index",
    "load_performance_schema",
    "load_schema",
    "load_universe_snapshot",
    "main",
    "normalize_universe_liquidity_scores",
    "publish_artifacts_atomically",
    "recover_interrupted_publish",
    "recover_transaction_state",
    "run_pipeline",
    "save_json_files",
    "update_history_index",
    "validate_final_payload_integrity",
    "validate_journal_metadata",
    "validate_performance_payload",
    "validate_temporal_integrity",
]


def canonicalize_report_for_reproducibility(report_payload: dict) -> dict:
    """Return a canonical copy of report payload with runtime metadata excluded/normalized."""
    if not isinstance(report_payload, dict):
        raise TypeError("report_payload must be a dictionary")

    import copy

    report_copy = copy.deepcopy(report_payload)
    report_copy.pop("generated_at", None)

    if "universe_info" in report_copy and isinstance(report_copy["universe_info"], dict):
        report_copy["universe_info"].pop("scanned_at", None)

    return report_copy


def load_universe_snapshot(snapshot_path: str) -> list[dict]:
    """Load and validate an explicit historical candidate universe snapshot JSON file."""
    import json

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
    import json

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


def main():
    recover_interrupted_publish(GENERATED_DIR)
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

        try:
            pipeline_res = generate_historical_report(
                data_as_of=target_date,
                universe_stock_map=stock_data_map,
                df_vnindex=df_vnindex_raw,
                df_vn30=df_vn30_raw,
                candidate_metadata=candidate_stocks,
                data_source="explicit_historical_input",
                generated_dir=GENERATED_DIR,
                publish_artifacts=True,
            )
        except ValueError as exc:
            logger.error("Historical report payload integrity validation failed: %s", exc)
            logger.error("Existing generated report files have been preserved and not overwritten.")
            raise SystemExit(1) from exc

        recs_data = pipeline_res[0]

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
            pipeline_res = run_pipeline(
                update_data=args.update,
                tracker=tracker,
                generated_dir=GENERATED_DIR,
                publish_artifacts=True,
            )
        except (ProviderRateLimitError, RuntimeError) as exc:
            logger.error("Data pipeline halted: %s", exc)
            logger.error("Existing generated report files have been preserved and not overwritten.")
            raise SystemExit(1) from exc
        except ValueError as exc:
            logger.error("Report payload integrity validation failed: %s", exc)
            logger.error("Existing generated report files have been preserved and not overwritten.")
            raise SystemExit(1) from exc

        recs_data = pipeline_res[0]

        logger.info("Report generation complete!")
        logger.info("Outputs written to generated/:")
        logger.info("  - recommendations.json (%d items)", len(recs_data["recommendations"]))
        logger.info("  - market.json (Regime: %s)", recs_data["market"]["regime"])


if __name__ == "__main__":
    main()
