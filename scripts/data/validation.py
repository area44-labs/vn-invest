"""Market data validation boundary for VN Invest data layer.

Validates canonical market data against required field schemas, price/volume OHLCV invariants,
and temporal consistency contracts. Invalid canonical market data fails closed.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import numpy as np
import pandas as pd

from scripts.data.models import CanonicalMarketData
from scripts.domain.data_quality import DataQuality

logger = logging.getLogger(__name__)


class CanonicalDataValidationError(ValueError):
    """Exception raised when canonical market data fails validation."""


REQUIRED_OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]

# Temporal Data Consistency & Staleness Threshold Parameters
MAX_STOCK_STALENESS_DAYS = 7
MAX_BENCHMARK_FUTURE_DAYS = 0

DATA_CORRUPTION_ISSUES = {
    "invalid_dates",
    "duplicate_dates",
    "non_monotonic_dates",
    "non_numeric_values",
    "nan_values",
    "infinite_values",
    "non_positive_prices",
    "negative_volume",
    "invalid_ohlc_relationship",
}


def round_tick_size(price: float, exchange: str = "HOSE") -> float:
    """Round price according to Vietnam exchange tick size rules (in VND/share)."""
    if price <= 0:
        return 0.0
    exchange_upper = exchange.upper() if exchange else "HOSE"
    if exchange_upper == "HOSE":
        if price < 10000.0:
            step = 10.0
        elif price <= 50000.0:
            step = 50.0
        else:
            step = 100.0
    else:  # HNX / UPCOM
        step = 100.0
    return round(round(price / step) * step, 2)


def get_exchange_price_limits(
    ref_price: float, exchange: str = "HOSE"
) -> tuple[float, float, float]:
    """Calculate exchange daily price reference, ceiling and floor bounds."""
    try:
        ref_p = float(ref_price) if ref_price is not None else 10000.0
    except ValueError, TypeError:
        ref_p = 10000.0

    if ref_p <= 0:
        ref_p = 10000.0

    ex_upper = str(exchange).upper() if exchange else "HOSE"
    pct = 0.07 if ex_upper == "HOSE" else (0.10 if ex_upper == "HNX" else 0.15)

    floor_p = round_tick_size(ref_p * (1.0 - pct), ex_upper)
    ceiling_p = round_tick_size(ref_p * (1.0 + pct), ex_upper)

    return ref_p, ceiling_p, floor_p


def clamp_price_limits(price: float, ref_price: float = 0.0, exchange: str = "HOSE") -> float:
    """Enforce exchange daily price floor and ceiling bounds."""
    try:
        p = float(price) if price is not None else 0.0
    except ValueError, TypeError:
        p = 0.0

    _ref_p, ceiling_p, floor_p = get_exchange_price_limits(ref_price, exchange)
    ex_upper = str(exchange).upper() if exchange else "HOSE"
    return round_tick_size(max(floor_p, min(ceiling_p, p)), ex_upper)


def validate_ohlcv_data(df: pd.DataFrame, symbol: str | None = None) -> dict:
    """Validate data quality for an OHLCV DataFrame without modifying raw data.

    Returns a dict containing:
      - status: "SUFFICIENT" | "PARTIAL" | "INSUFFICIENT"
      - issues: sorted list of issue codes
      - row_count: total raw rows
      - valid_row_count: number of clean valid rows
      - latest_date: YYYY-MM-DD string of latest usable valid row or None
      - clean_df: pd.DataFrame containing only valid rows
    """
    if df is None or df.empty:
        return {
            "status": "INSUFFICIENT",
            "issues": ["empty_dataframe"],
            "row_count": 0,
            "valid_row_count": 0,
            "latest_date": None,
            "clean_df": pd.DataFrame(),
        }

    row_count = len(df)
    df_cols_lower = [str(c).lower() for c in df.columns]
    col_map = {str(c).lower(): c for c in df.columns}

    required_fields = ["open", "high", "low", "close", "volume"]
    missing_fields = [f for f in required_fields if f not in df_cols_lower]

    date_col_name = None
    for candidate in ["time", "date"]:
        if candidate in df_cols_lower:
            date_col_name = col_map[candidate]
            break

    issues = []
    if missing_fields or not date_col_name:
        if missing_fields:
            issues.append("missing_required_columns")
        if not date_col_name:
            issues.append("missing_date_column")
        return {
            "status": "INSUFFICIENT",
            "issues": sorted(set(issues)),
            "row_count": row_count,
            "valid_row_count": 0,
            "latest_date": None,
            "clean_df": pd.DataFrame(),
        }

    raw_dates = df[date_col_name]
    parsed_dates = pd.to_datetime(raw_dates, errors="coerce")
    invalid_date_mask = parsed_dates.isna()
    if invalid_date_mask.any():
        issues.append("invalid_dates")

    # Detect duplicate trading dates (exclude all duplicate date occurrences from clean dataset)
    dup_date_mask = pd.Series(False, index=df.index)
    valid_parsed_dates = parsed_dates.dropna()
    if not valid_parsed_dates.empty:
        duplicated_date_values = set(valid_parsed_dates[valid_parsed_dates.duplicated()].values)
        if duplicated_date_values:
            issues.append("duplicate_dates")
            dup_date_mask = parsed_dates.isin(duplicated_date_values)

        if not valid_parsed_dates.is_monotonic_increasing:
            issues.append("non_monotonic_dates")

    numeric_df = pd.DataFrame(index=df.index)
    has_non_numeric = False
    has_nans = False
    has_inf = False

    for field in required_fields:
        orig_col = col_map[field]
        converted = pd.to_numeric(df[orig_col], errors="coerce")
        numeric_df[field] = converted
        if converted.isna().any():
            has_nans = True
            non_null_orig = df[orig_col].dropna()
            if not non_null_orig.empty and converted.loc[non_null_orig.index].isna().any():
                has_non_numeric = True
        arr = converted.to_numpy()
        if np.isinf(arr).any():
            has_inf = True

    if has_non_numeric:
        issues.append("non_numeric_values")
    if has_nans:
        issues.append("nan_values")
    if has_inf:
        issues.append("infinite_values")

    row_invalid_mask = invalid_date_mask | dup_date_mask
    for field in required_fields:
        row_invalid_mask |= numeric_df[field].isna() | np.isinf(numeric_df[field].to_numpy())

    price_cols = ["open", "high", "low", "close"]
    non_pos_price_mask = (numeric_df[price_cols] <= 0).any(axis=1)
    if non_pos_price_mask.any():
        issues.append("non_positive_prices")
        row_invalid_mask |= non_pos_price_mask

    neg_vol_mask = numeric_df["volume"] < 0
    if neg_vol_mask.any():
        issues.append("negative_volume")
        row_invalid_mask |= neg_vol_mask

    o, h, low_s, c = numeric_df["open"], numeric_df["high"], numeric_df["low"], numeric_df["close"]
    ohlc_conflict_mask = (h < low_s) | (h < o) | (h < c) | (low_s > o) | (low_s > c)
    if ohlc_conflict_mask.any():
        issues.append("invalid_ohlc_relationship")
        row_invalid_mask |= ohlc_conflict_mask

    has_corruption = any(iss in DATA_CORRUPTION_ISSUES for iss in issues)

    if has_corruption:
        valid_row_count = 0
        clean_df = pd.DataFrame()
        latest_date = None
        status = "INSUFFICIENT"
    else:
        valid_mask = ~row_invalid_mask
        valid_row_count = int(valid_mask.sum())

        if valid_row_count > 0:
            clean_df = pd.DataFrame(index=df.index[valid_mask])
            clean_df["time"] = parsed_dates[valid_mask].dt.strftime("%Y-%m-%d")
            for field in required_fields:
                clean_df[field] = numeric_df.loc[valid_mask, field]
            clean_df = clean_df.sort_values("time").reset_index(drop=True)
            latest_date = clean_df["time"].max()
        else:
            clean_df = pd.DataFrame()
            latest_date = None

        if valid_row_count < 20:
            issues.append("insufficient_history")
            status = "INSUFFICIENT"
        else:
            status = "SUFFICIENT"

    return {
        "status": status,
        "issues": sorted(set(issues)),
        "row_count": row_count,
        "valid_row_count": valid_row_count,
        "latest_date": latest_date,
        "clean_df": clean_df,
    }


def get_clean_ohlcv_data(df: pd.DataFrame, symbol: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Extract downstream-safe cleaned OHLCV DataFrame and validation result."""
    val_res = validate_ohlcv_data(df, symbol)
    return val_res["clean_df"], val_res


def extract_latest_trading_date(df: pd.DataFrame) -> str | None:
    """Extract the latest validated EOD trading session date (YYYY-MM-DD) from OHLCV DataFrame."""
    if df is None or df.empty:
        return None

    df_cols = [c.lower() for c in df.columns]
    date_col = None
    for candidate in ["time", "date"]:
        if candidate in df_cols:
            date_col = df.columns[df_cols.index(candidate)]
            break

    if not date_col:
        return None

    series = df[date_col].dropna()
    if series.empty:
        return None

    parsed_series = pd.to_datetime(series, errors="coerce")
    valid_dates = parsed_series.dropna()
    if valid_dates.empty:
        return None

    max_date = valid_dates.max()
    return max_date.strftime("%Y-%m-%d")


def validate_temporal_integrity(
    data_as_of: str | None,
    stock_dates_map: dict[str, str | None],
    reference_date: str | None = None,
    max_staleness_days: int = MAX_STOCK_STALENESS_DAYS,
    strict_date_match: bool = False,
) -> dict:
    """Validate temporal consistency across VNINDEX benchmark data_as_of and processed stock dates."""
    issues = []
    future_symbols = set()
    stale_symbols = set()
    missing_date_symbols = set()

    if not data_as_of or not isinstance(data_as_of, str):
        return {
            "is_valid": False,
            "issues": ["Missing or invalid VNINDEX benchmark data_as_of date"],
            "future_symbols": future_symbols,
            "stale_symbols": stale_symbols,
            "missing_date_symbols": missing_date_symbols,
        }

    try:
        benchmark_dt = datetime.strptime(data_as_of.strip(), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return {
            "is_valid": False,
            "issues": [f"Malformed VNINDEX data_as_of date string: '{data_as_of}'"],
            "future_symbols": future_symbols,
            "stale_symbols": stale_symbols,
            "missing_date_symbols": missing_date_symbols,
        }

    if reference_date:
        try:
            if "T" in reference_date or "+" in reference_date or "Z" in reference_date:
                ref_dt = datetime.fromisoformat(reference_date)
                if ref_dt.tzinfo is None:
                    ref_dt = ref_dt.replace(tzinfo=UTC)
            else:
                ref_dt = datetime.strptime(reference_date.strip(), "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            ref_dt = datetime.now(UTC)
    else:
        ref_dt = datetime.now(UTC)

    ref_date_only = ref_dt.date()
    benchmark_date_only = benchmark_dt.date()

    if benchmark_date_only > ref_date_only + timedelta(days=MAX_BENCHMARK_FUTURE_DAYS):
        issues.append(
            f"VNINDEX benchmark data_as_of '{data_as_of}' is in the future relative to reference/execution date '{ref_date_only.strftime('%Y-%m-%d')}'"
        )

    for sym, stock_date_str in stock_dates_map.items():
        if not stock_date_str or not isinstance(stock_date_str, str):
            missing_date_symbols.add(sym)
            continue

        try:
            stock_dt = datetime.strptime(stock_date_str.strip(), "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            missing_date_symbols.add(sym)
            continue

        stock_date_only = stock_dt.date()

        if stock_date_only > benchmark_date_only:
            future_symbols.add(sym)
        else:
            lag_days = (benchmark_date_only - stock_date_only).days
            if strict_date_match:
                if lag_days > 0:
                    stale_symbols.add(sym)
            elif lag_days > max_staleness_days:
                stale_symbols.add(sym)

    if future_symbols:
        issues.append(
            f"Detected stock symbols dated after VNINDEX data_as_of ({data_as_of}): {sorted(future_symbols)}"
        )
    if stale_symbols:
        if strict_date_match:
            issues.append(
                f"Detected stock symbols whose latest trading date does not match VNINDEX data_as_of ({data_as_of}): {sorted(stale_symbols)}"
            )
        else:
            issues.append(
                f"Detected stock symbols excessively stale relative to VNINDEX data_as_of ({data_as_of}, >{max_staleness_days} days lag): {sorted(stale_symbols)}"
            )
    if missing_date_symbols:
        issues.append(
            f"Detected processed stock symbols with missing or invalid latest dates: {sorted(missing_date_symbols)}"
        )

    is_valid = len(issues) == 0

    return {
        "is_valid": is_valid,
        "issues": sorted(issues),
        "future_symbols": future_symbols,
        "stale_symbols": stale_symbols,
        "missing_date_symbols": missing_date_symbols,
    }


class CanonicalMarketValidator:
    """Validator inspecting CanonicalMarketData for invariant & temporal compliance."""

    REQUIRED_COLUMNS: ClassVar[list[str]] = REQUIRED_OHLCV_COLUMNS

    def validate(
        self,
        canonical_data: CanonicalMarketData,
        reference_date: str | None = None,
        max_staleness_days: int = MAX_STOCK_STALENESS_DAYS,
    ) -> CanonicalMarketData:
        """Validate canonical market data. Returns validated CanonicalMarketData with DataQuality attached.

        Fails closed on corrupt, malformed, or temporally inconsistent data.
        """
        sym = canonical_data.symbol
        issues: list[str] = []

        df = canonical_data.to_df()

        if df is None or df.empty:
            issues.append("empty_dataset")
            src_tag = (
                canonical_data.source_tag
                if canonical_data.source_tag in ("INVALID_SYMBOL", "EXPLICITLY_INVALID")
                else "PROVIDER_FAILURE"
            )
            dq = DataQuality(
                status="INSUFFICIENT",
                issues=tuple(issues),
                valid_row_count=0,
                latest_date=canonical_data.data_as_of,
                data_as_of=canonical_data.data_as_of,
                data_source=src_tag,
            )
            return CanonicalMarketData(
                symbol=sym,
                records=(),
                data_as_of=canonical_data.data_as_of,
                source_tag=src_tag,
                data_quality=dq,
            )

        cols_lower = [str(c).lower() for c in df.columns]

        missing_cols = [c for c in self.REQUIRED_COLUMNS if c not in cols_lower]
        if missing_cols:
            issues.append("missing_required_columns")

        date_col = "date" if "date" in df.columns else ("time" if "time" in df.columns else None)
        if not date_col:
            issues.append("missing_date_column")
            dates_parsed = pd.Series(dtype="datetime64[ns]")
        else:
            dates_parsed = pd.to_datetime(df[date_col], errors="coerce")
            if dates_parsed.isna().any():
                issues.append("invalid_date_values")

            if dates_parsed.duplicated().any():
                issues.append("duplicate_dates")

            if not dates_parsed.is_monotonic_increasing:
                issues.append("unsorted_dates")

        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                series = pd.to_numeric(df[col], errors="coerce")
                if series.isna().any():
                    issues.append(f"nan_values_in_{col}")
                arr = series.dropna().to_numpy()
                if np.isinf(arr).any():
                    issues.append(f"inf_values_in_{col}")

        if all(col in df.columns for col in ["open", "high", "low", "close", "volume"]):
            open_s = pd.to_numeric(df["open"], errors="coerce")
            high_s = pd.to_numeric(df["high"], errors="coerce")
            low_s = pd.to_numeric(df["low"], errors="coerce")
            close_s = pd.to_numeric(df["close"], errors="coerce")
            vol_s = pd.to_numeric(df["volume"], errors="coerce")

            if (
                (open_s <= 0).any()
                or (high_s <= 0).any()
                or (low_s <= 0).any()
                or (close_s <= 0).any()
            ):
                issues.append("non_positive_prices")

            if (vol_s < 0).any():
                issues.append("negative_volume")

            invalid_ohlc = (
                (high_s < low_s)
                | (open_s > high_s)
                | (open_s < low_s)
                | (close_s > high_s)
                | (close_s < low_s)
            )
            if invalid_ohlc.any():
                issues.append("invalid_ohlc_relationship")

        latest_record_date = (
            dates_parsed.max().strftime("%Y-%m-%d")
            if not dates_parsed.empty and not dates_parsed.isna().all()
            else None
        )

        if reference_date and latest_record_date:
            try:
                ref_dt = datetime.strptime(reference_date, "%Y-%m-%d").replace(tzinfo=UTC)
                lat_dt = datetime.strptime(latest_record_date, "%Y-%m-%d").replace(tzinfo=UTC)
                if lat_dt > ref_dt:
                    issues.append(f"future_dated_record: {latest_record_date} > {reference_date}")
                elif (ref_dt - lat_dt).days > max_staleness_days:
                    issues.append(f"stale_data: {latest_record_date} vs {reference_date}")
            except ValueError:
                issues.append("unparseable_reference_date")

        provider_failure_issues = {
            "empty_dataset",
            "missing_required_columns",
            "missing_date_column",
        }
        corruption_issues = {
            "invalid_date_values",
            "duplicate_dates",
            "unsorted_dates",
            "non_positive_prices",
            "negative_volume",
            "invalid_ohlc_relationship",
        }

        has_provider_failure = any(iss in provider_failure_issues for iss in issues)
        has_corruption = any(iss in corruption_issues for iss in issues) or any(
            "future_dated" in iss or "nan_values" in iss or "inf_values" in iss for iss in issues
        )

        if canonical_data.source_tag == "INVALID_SYMBOL":
            source_tag = "INVALID_SYMBOL"
            dq_status = "INSUFFICIENT"
        elif has_provider_failure or canonical_data.source_tag == "PROVIDER_FAILURE":
            source_tag = "PROVIDER_FAILURE"
            dq_status = "INSUFFICIENT"
        elif has_corruption or canonical_data.source_tag == "EXPLICITLY_INVALID":
            source_tag = "EXPLICITLY_INVALID"
            dq_status = "INSUFFICIENT"
        elif len(df) < 20:
            source_tag = "INSUFFICIENT_HISTORICAL_DATA"
            dq_status = "INSUFFICIENT"
            issues.append("insufficient_history")
        else:
            source_tag = canonical_data.source_tag or "REAL_DATA"
            dq_status = "SUFFICIENT"

        dq = DataQuality(
            status=dq_status,
            issues=tuple(issues),
            valid_row_count=len(df)
            if dq_status == "SUFFICIENT" or source_tag == "INSUFFICIENT_HISTORICAL_DATA"
            else 0,
            latest_date=latest_record_date,
            data_as_of=canonical_data.data_as_of or latest_record_date,
            data_source=source_tag,
        )

        is_valid = dq_status == "SUFFICIENT" or source_tag == "INSUFFICIENT_HISTORICAL_DATA"

        return CanonicalMarketData(
            symbol=sym,
            records=canonical_data.records if is_valid else (),
            data_as_of=canonical_data.data_as_of or latest_record_date,
            source_tag=source_tag,
            data_quality=dq,
        )


def validate_canonical_market_data(
    canonical_data: CanonicalMarketData,
    reference_date: str | None = None,
    max_staleness_days: int = MAX_STOCK_STALENESS_DAYS,
) -> CanonicalMarketData:
    """Convenience entry point for canonical market data validation."""
    validator = CanonicalMarketValidator()
    return validator.validate(
        canonical_data=canonical_data,
        reference_date=reference_date,
        max_staleness_days=max_staleness_days,
    )


__all__ = [
    "DATA_CORRUPTION_ISSUES",
    "MAX_BENCHMARK_FUTURE_DAYS",
    "MAX_STOCK_STALENESS_DAYS",
    "REQUIRED_OHLCV_COLUMNS",
    "CanonicalDataValidationError",
    "CanonicalMarketValidator",
    "clamp_price_limits",
    "extract_latest_trading_date",
    "get_clean_ohlcv_data",
    "get_exchange_price_limits",
    "round_tick_size",
    "validate_canonical_market_data",
    "validate_ohlcv_data",
    "validate_temporal_integrity",
]
