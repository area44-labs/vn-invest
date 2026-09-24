"""Vietnam Market Data Module for VN Invest v2.

Handles symbol normalization, universe provider abstraction, data quality validation,
price tick size limits, exchange mappings, and EOD historical market data fetching.
Explicitly tags data sources: REAL_DATA or INSUFFICIENT_HISTORICAL_DATA.
"""

import logging
import os
from datetime import UTC, datetime, timedelta

import pandas as pd

from scripts.data_provider import ProviderRateLimitError, VnstockDataProvider

logger = logging.getLogger(__name__)

# Explicit internal unit contract constants
PRICE_UNIT = "VND/share"
VOLUME_UNIT = "shares"
TRADING_VALUE_UNIT = "VND"
AVG_TRADING_VALUE_UNIT = "billion_VND"

# Source unit contracts for upstream data providers:
# - Stock data (via vnstock KBS/MSN quotes): Prices (open, high, low, close) are in `thousand_VND/share` (e.g. 128.40 = 128,400 VND/share). Volume is in `shares` (e.g. 3,172,800 shares).
# - Index data (VNINDEX, VN30, etc.): Values represent composite market index points (e.g. 1269.71 points), not equity stock prices, and are already in canonical benchmark units.
SOURCE_PRICE_UNIT_VNSTOCK = "thousand_VND/share"
SOURCE_VOLUME_UNIT_VNSTOCK = "shares"
VALID_PRICE_UNITS = {"VND/share", "thousand_VND/share"}
VALID_VOLUME_UNITS = {"shares", "thousand_shares"}
INDEX_SYMBOLS = {"VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX", "VN30INDEX"}

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RECOMMENDATIONS_JSON_PATH = os.path.join(ROOT_DIR, "generated", "recommendations.json")

TIMEZONE_POLICY = """
Timezone and Date Semantics Policy:
1. `generated_at`: ISO 8601 timestamp in UTC (e.g. '2026-09-13T18:00:00.000000+00:00') representing
   the exact system execution time when the report or analysis was generated.
2. `data_as_of`: Calendar date in 'YYYY-MM-DD' format representing the latest actual validated
   market-data EOD trading session present in the dataset.
3. Market-data date (`data_as_of`) must NEVER be substituted with current system date (`datetime.now()`).
   If OHLCV data is empty or unavailable, `data_as_of` must remain `None`.
"""


def extract_latest_trading_date(df: pd.DataFrame) -> str | None:
    """Extract the latest validated EOD trading session date (YYYY-MM-DD) from OHLCV DataFrame.

    Parses all dates in the date column, ignores invalid/null values, and returns the maximum date.
    Returns None if DataFrame is empty, None, or contains no valid date entries.
    """
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


class UniverseProvider:
    """Abstraction for stock universe selection in Vietnam equity markets."""

    def __init__(self, universe_type: str = "VN30_MIDCAP_LEADERS"):
        self.universe_type = universe_type
        self.candidates = self._get_candidates()

    def _get_candidates(self) -> list[dict]:
        return [
            # HOSE VN30
            {
                "symbol": "ACB",
                "companyName": "Ngân hàng TMCP Á Châu",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "BCM",
                "companyName": "Tổng Công ty Đầu tư và Phát triển Công nghiệp",
                "sector": "Bất động sản KCN",
                "exchange": "HOSE",
            },
            {
                "symbol": "BID",
                "companyName": "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "BVH",
                "companyName": "Tập đoàn Bảo Việt",
                "sector": "Bảo hiểm",
                "exchange": "HOSE",
            },
            {
                "symbol": "CTG",
                "companyName": "Ngân hàng TMCP Công Thương Việt Nam",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "FPT",
                "companyName": "Công ty Cổ phần FPT",
                "sector": "Công nghệ",
                "exchange": "HOSE",
            },
            {
                "symbol": "GAS",
                "companyName": "Tổng Công ty Khí Việt Nam - CTCP",
                "sector": "Dầu khí",
                "exchange": "HOSE",
            },
            {
                "symbol": "GVR",
                "companyName": "Tập đoàn Công nghiệp Cao su Việt Nam - CTCP",
                "sector": "Cao su & BĐS KCN",
                "exchange": "HOSE",
            },
            {
                "symbol": "HDB",
                "companyName": "Ngân hàng TMCP Phát triển TP. Hồ Chí Minh",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "HPG",
                "companyName": "Công ty Cổ phần Tập đoàn Hòa Phát",
                "sector": "Thép",
                "exchange": "HOSE",
            },
            {
                "symbol": "MBB",
                "companyName": "Ngân hàng TMCP Quân Đội",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "MSN",
                "companyName": "Công ty Cổ phần Tập đoàn Masan",
                "sector": "Tiêu dùng",
                "exchange": "HOSE",
            },
            {
                "symbol": "MWG",
                "companyName": "Công ty Cổ phần Đầu tư Thế giới Di Động",
                "sector": "Bán lẻ",
                "exchange": "HOSE",
            },
            {
                "symbol": "PLX",
                "companyName": "Tập đoàn Xăng dầu Việt Nam",
                "sector": "Năng lượng",
                "exchange": "HOSE",
            },
            {
                "symbol": "POW",
                "companyName": "Tổng Công ty Điện lực Dầu khí Việt Nam - CTCP",
                "sector": "Điện lực",
                "exchange": "HOSE",
            },
            {
                "symbol": "SAB",
                "companyName": "Tổng Công ty Cổ phần Bia - Rượu - Nước giải khát Sài Gòn",
                "sector": "Đồ uống",
                "exchange": "HOSE",
            },
            {
                "symbol": "SSB",
                "companyName": "Ngân hàng TMCP Đông Nam Á",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "SSI",
                "companyName": "Công ty Cổ phần Chứng khoán SSI",
                "sector": "Chứng khoán",
                "exchange": "HOSE",
            },
            {
                "symbol": "STB",
                "companyName": "Ngân hàng TMCP Sài Gòn Thương Tín",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "TCB",
                "companyName": "Ngân hàng TMCP Kỹ thương Việt Nam",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "TPB",
                "companyName": "Ngân hàng TMCP Tiên Phong",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "VCB",
                "companyName": "Ngân hàng TMCP Ngoại Thương Việt Nam",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "VHM",
                "companyName": "Công ty Cổ phần Vinhomes",
                "sector": "Bất động sản",
                "exchange": "HOSE",
            },
            {
                "symbol": "VIB",
                "companyName": "Ngân hàng TMCP Quốc tế Việt Nam",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "VIC",
                "companyName": "Tập đoàn Vingroup - CTCP",
                "sector": "Bất động sản",
                "exchange": "HOSE",
            },
            {
                "symbol": "VJC",
                "companyName": "Công ty Cổ phần Hàng không Vietjet",
                "sector": "Hàng không",
                "exchange": "HOSE",
            },
            {
                "symbol": "VNM",
                "companyName": "Công ty Cổ phần Sữa Việt Nam",
                "sector": "Thực phẩm",
                "exchange": "HOSE",
            },
            {
                "symbol": "VPB",
                "companyName": "Ngân hàng TMCP Việt Nam Thịnh Vượng",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            {
                "symbol": "VRE",
                "companyName": "Công ty Cổ phần Vincom Retail",
                "sector": "Bất động sản",
                "exchange": "HOSE",
            },
            {
                "symbol": "SHB",
                "companyName": "Ngân hàng TMCP Sài Gòn - Hà Nội",
                "sector": "Ngân hàng",
                "exchange": "HOSE",
            },
            # Midcaps / HNX / UPCOM Leaders
            {
                "symbol": "DGC",
                "companyName": "CTCP Tập đoàn Hóa chất Đức Giang",
                "sector": "Hóa chất",
                "exchange": "HOSE",
            },
            {
                "symbol": "FRT",
                "companyName": "CTCP Bán lẻ Kỹ thuật số FPT",
                "sector": "Bán lẻ",
                "exchange": "HOSE",
            },
            {
                "symbol": "PVD",
                "companyName": "Tổng CTCP Khoan và Dịch vụ Khoan Dầu khí",
                "sector": "Dầu khí",
                "exchange": "HOSE",
            },
            {
                "symbol": "VCI",
                "companyName": "CTCP Chứng khoán Vietcap",
                "sector": "Chứng khoán",
                "exchange": "HOSE",
            },
            {
                "symbol": "HCM",
                "companyName": "CTCP Chứng khoán TP.Hồ Chí Minh",
                "sector": "Chứng khoán",
                "exchange": "HOSE",
            },
            {
                "symbol": "VND",
                "companyName": "CTCP Chứng khoán VNDIRECT",
                "sector": "Chứng khoán",
                "exchange": "HOSE",
            },
            {
                "symbol": "HSG",
                "companyName": "CTCP Tập đoàn Hoa Sen",
                "sector": "Thép",
                "exchange": "HOSE",
            },
            {
                "symbol": "NKG",
                "companyName": "CTCP Thép Nam Kim",
                "sector": "Thép",
                "exchange": "HOSE",
            },
            {
                "symbol": "DXG",
                "companyName": "CTCP Tập đoàn Đất Xanh",
                "sector": "Bất động sản",
                "exchange": "HOSE",
            },
            {
                "symbol": "DIG",
                "companyName": "Tổng CTCP Đầu tư Phát triển Xây dựng",
                "sector": "Bất động sản",
                "exchange": "HOSE",
            },
            {
                "symbol": "PDR",
                "companyName": "CTCP Phát triển Bất động sản Phát Đạt",
                "sector": "Bất động sản",
                "exchange": "HOSE",
            },
            {
                "symbol": "GMD",
                "companyName": "CTCP Gemadept",
                "sector": "Logistics",
                "exchange": "HOSE",
            },
        ]

    def get_info(self) -> dict:
        return {
            "universe_type": self.universe_type,
            "universe_size": len(self.candidates),
        }


CANDIDATE_STOCKS = UniverseProvider().candidates


def normalize_symbol(symbol: str) -> str:
    """Normalize Vietnam stock symbol format (e.g. 'fpt' -> 'FPT')."""
    if not symbol:
        return ""
    return str(symbol).strip().upper()


def normalize_ohlcv_units(
    df: pd.DataFrame,
    source_price_unit: str = SOURCE_PRICE_UNIT_VNSTOCK,
    source_volume_unit: str = SOURCE_VOLUME_UNIT_VNSTOCK,
) -> pd.DataFrame:
    """Normalize OHLCV DataFrame from declared source units to canonical internal units.

    Canonical units:
    - price: VND/share
    - volume: shares

    Raises ValueError if an unsupported price or volume unit configuration is provided.
    Does NOT perform magnitude checks (e.g., if price > X) to infer units.
    """
    if source_price_unit not in VALID_PRICE_UNITS:
        raise ValueError(
            f"Unsupported price unit '{source_price_unit}'. Must be one of {sorted(VALID_PRICE_UNITS)}"
        )
    if source_volume_unit not in VALID_VOLUME_UNITS:
        raise ValueError(
            f"Unsupported volume unit '{source_volume_unit}'. Must be one of {sorted(VALID_VOLUME_UNITS)}"
        )

    if df is None or df.empty:
        return df

    df_norm = df.copy()

    if source_price_unit == "thousand_VND/share":
        price_cols = [c for c in ["open", "high", "low", "close", "vwap"] if c in df_norm.columns]
        for col in price_cols:
            df_norm[col] = df_norm[col] * 1000.0

    if source_volume_unit == "thousand_shares" and "volume" in df_norm.columns:
        df_norm["volume"] = df_norm["volume"] * 1000.0

    return df_norm


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
            "issues": issues,
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

    numeric_df = pd.DataFrame(index=df.index)
    has_non_numeric = False
    has_nans = False

    for field in required_fields:
        orig_col = col_map[field]
        converted = pd.to_numeric(df[orig_col], errors="coerce")
        numeric_df[field] = converted
        if converted.isna().any():
            has_nans = True
            non_null_orig = df[orig_col].dropna()
            if not non_null_orig.empty and converted.loc[non_null_orig.index].isna().any():
                has_non_numeric = True

    if has_non_numeric:
        issues.append("non_numeric_values")
    if has_nans:
        issues.append("nan_values")

    row_invalid_mask = invalid_date_mask | dup_date_mask
    for field in required_fields:
        row_invalid_mask |= numeric_df[field].isna()

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

    valid_mask = ~row_invalid_mask
    valid_row_count = int(valid_mask.sum())

    if valid_row_count < 20:
        issues.append("insufficient_history")

    # Build clean DataFrame without mutating raw df
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

    if (
        valid_row_count < 20
        or "missing_required_columns" in issues
        or "missing_date_column" in issues
    ):
        status = "INSUFFICIENT"
    elif len(issues) > 0:
        status = "PARTIAL"
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


def get_historical_data(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    max_retries: int = 2,
    use_cache_only: bool = False,
    allow_synthetic: bool = False,
    throttle_delay: float = 0.0,
):
    """Fetch real historical EOD OHLCV data for a given symbol via provider boundary."""
    sym = normalize_symbol(symbol)
    if not start_date or not end_date:
        now_dt = datetime.now(UTC)
        end_date = now_dt.strftime("%Y-%m-%d")
        start_date = (now_dt - timedelta(days=365)).strftime("%Y-%m-%d")

    if throttle_delay > 0:
        import time

        time.sleep(throttle_delay)

    try:
        provider = VnstockDataProvider()
        df_out = provider.fetch_ohlcv(
            symbol=sym,
            start_date=start_date,
            end_date=end_date,
            max_retries=max_retries,
        )
        val_res = validate_ohlcv_data(df_out, sym)
        return df_out, "REAL_DATA", val_res["issues"]
    except ProviderRateLimitError:
        logger.error(
            "Provider rate-limit error encountered while fetching '%s'. Re-raising loudly.", sym
        )
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("Data fetch failed for '%s' via provider boundary: %s", sym, e)
        return (
            pd.DataFrame(),
            "INSUFFICIENT_HISTORICAL_DATA",
            [f"[{sym}] Không thể lấy dữ liệu lịch sử thực tế từ vnstock."],
        )
