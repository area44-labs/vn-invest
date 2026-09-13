"""Vietnam Market Data Module for VN Invest v2.

Handles symbol normalization, universe provider abstraction, data quality validation,
price tick size limits, exchange mappings, and EOD historical market data fetching.
Explicitly tags data sources: REAL_DATA or INSUFFICIENT_HISTORICAL_DATA.
"""

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

logger = logging.getLogger(__name__)

try:
    from vnstock.api.quote import Quote as VnQuote

    VNSTOCK_AVAILABLE = True
except ImportError:
    VNSTOCK_AVAILABLE = False

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

    Returns None if DataFrame is empty, None, or lacks date information.
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

    latest_val = series.iloc[-1]
    if isinstance(latest_val, (pd.Timestamp, datetime)):
        return latest_val.strftime("%Y-%m-%d")

    val_str = str(latest_val).strip()
    if not val_str:
        return None

    match = re.search(r"\d{4}-\d{2}-\d{2}", val_str)
    if match:
        return match.group(0)

    try:
        parsed = pd.to_datetime(val_str)
        if pd.notna(parsed):
            return parsed.strftime("%Y-%m-%d")
    except (ValueError, TypeError, Exception) as e:
        logger.debug("Date string parsing failed for '%s': %s", val_str, e)

    return None


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


def parse_wait_seconds(err_str: str) -> int:
    """Extract wait seconds from vnstock rate limit notice."""
    match = re.search(r"chờ\s+(\d+)\s+giây", err_str, re.IGNORECASE)
    if match:
        return int(match.group(1)) + 2
    match_sec = re.search(r"wait\s+(\d+)\s+sec", err_str, re.IGNORECASE)
    if match_sec:
        return int(match_sec.group(1)) + 2
    match_sec2 = re.search(r"(\d+)\s+second", err_str, re.IGNORECASE)
    if match_sec2:
        return int(match_sec2.group(1)) + 2
    return 15


def round_tick_size(price: float, exchange: str = "HOSE") -> float:
    """Round price according to Vietnam exchange tick size rules."""
    if price <= 0:
        return 0.0
    exchange_upper = exchange.upper() if exchange else "HOSE"
    if exchange_upper == "HOSE":
        if price < 10.0:
            step = 0.01
        elif price <= 50.0:
            step = 0.05
        else:
            step = 0.1
    else:  # HNX / UPCOM
        step = 0.1
    return round(round(price / step) * step, 2)


def get_exchange_price_limits(
    ref_price: float, exchange: str = "HOSE"
) -> tuple[float, float, float]:
    """Calculate exchange daily price reference, ceiling and floor bounds."""
    try:
        ref_p = float(ref_price) if ref_price is not None else 10.0
    except (ValueError, TypeError):
        ref_p = 10.0

    if ref_p <= 0:
        ref_p = 10.0

    ex_upper = str(exchange).upper() if exchange else "HOSE"
    pct = 0.07 if ex_upper == "HOSE" else (0.10 if ex_upper == "HNX" else 0.15)

    floor_p = round_tick_size(ref_p * (1.0 - pct), ex_upper)
    ceiling_p = round_tick_size(ref_p * (1.0 + pct), ex_upper)

    return ref_p, ceiling_p, floor_p


def clamp_price_limits(price: float, ref_price: float = 0.0, exchange: str = "HOSE") -> float:
    """Enforce exchange daily price floor and ceiling bounds."""
    try:
        p = float(price) if price is not None else 0.0
    except (ValueError, TypeError):
        p = 0.0

    _ref_p, ceiling_p, floor_p = get_exchange_price_limits(ref_price, exchange)
    ex_upper = str(exchange).upper() if exchange else "HOSE"
    return round_tick_size(max(floor_p, min(ceiling_p, p)), ex_upper)


def validate_ohlcv_data(df: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, list[str]]:
    """Validate data quality for OHLCV DataFrame."""
    warnings = []
    if df is None or df.empty:
        return pd.DataFrame(), [f"[{symbol}] Dữ liệu OHLCV rỗng."]

    df_valid = df.copy()
    df_valid.columns = [c.lower() for c in df_valid.columns]

    required_cols = ["open", "high", "low", "close", "volume"]
    for col in required_cols:
        if col not in df_valid.columns:
            return pd.DataFrame(), [f"[{symbol}] Thiếu cột bắt buộc {col}."]
        df_valid[col] = pd.to_numeric(df_valid[col], errors="coerce")

    date_col = (
        "time" if "time" in df_valid.columns else ("date" if "date" in df_valid.columns else None)
    )
    if date_col:
        initial_count = len(df_valid)
        df_valid = df_valid.drop_duplicates(subset=[date_col], keep="last")
        if len(df_valid) < initial_count:
            warnings.append(
                f"[{symbol}] Loại bỏ {initial_count - len(df_valid)} phiên trùng lặp ngày."
            )

    invalid_price = (df_valid["close"] <= 0) | (df_valid["volume"] < 0)
    if invalid_price.any():
        warnings.append(
            f"[{symbol}] Loại bỏ {invalid_price.sum()} dòng có giá đóng cửa <= 0 hoặc volume < 0."
        )
        df_valid = df_valid[~invalid_price]

    max_oc = df_valid[["open", "close"]].max(axis=1)
    min_oc = df_valid[["open", "close"]].min(axis=1)
    ohlc_conflict = (df_valid["high"] < max_oc) | (df_valid["low"] > min_oc)
    if ohlc_conflict.any():
        warnings.append(
            f"[{symbol}] Phát hiện {ohlc_conflict.sum()} dòng vi phạm quy tắc High >= Max(O,C) hoặc Low <= Min(O,C)."
        )
        df_valid.loc[df_valid["high"] < max_oc, "high"] = max_oc
        df_valid.loc[df_valid["low"] > min_oc, "low"] = min_oc

    returns = df_valid["close"].pct_change().abs()
    spikes = returns > 0.35
    if spikes.any():
        warnings.append(
            f"[{symbol}] Báo động: {spikes.sum()} phiên biến động giá bất thường (> 35%)."
        )

    return df_valid.reset_index(drop=True), warnings


def get_historical_data(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    max_retries: int = 2,
    use_cache_only: bool = False,
    allow_synthetic: bool = False,
):
    """Fetch real historical EOD OHLCV data for a given symbol from vnstock."""
    sym = normalize_symbol(symbol)
    if not start_date or not end_date:
        now_dt = datetime.now(timezone.utc)
        end_date = now_dt.strftime("%Y-%m-%d")
        start_date = (now_dt - timedelta(days=365)).strftime("%Y-%m-%d")

    INDEX_SYMBOLS = {"VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX", "VN30INDEX"}

    if VNSTOCK_AVAILABLE:
        sources = ["kbs", "msn"]
        for attempt in range(max_retries):
            for source in sources:
                try:
                    q = VnQuote(symbol=sym, source=source)
                    df = q.history(start=start_date, end=end_date)
                    if df is not None and not df.empty and "close" in df.columns:
                        df_val, warnings = validate_ohlcv_data(df, sym)
                        if not df_val.empty and len(df_val) >= 15:
                            if sym not in INDEX_SYMBOLS and df_val["close"].iloc[-1] > 1000.0:
                                for col in ["open", "high", "low", "close"]:
                                    if col in df_val.columns:
                                        df_val[col] = df_val[col] / 1000.0
                            return df_val, "REAL_DATA", warnings
                except (Exception, SystemExit, BaseException) as e:  # noqa: BLE001
                    err_str = str(e).lower()
                    if any(
                        x in err_str
                        for x in [
                            "rate limit",
                            "giới hạn",
                            "wait",
                            "systemexit",
                            "quota",
                            "429",
                        ]
                    ):
                        wait_sec = parse_wait_seconds(str(e))
                        time.sleep(wait_sec)
                    else:
                        time.sleep(0.1)
            if attempt < max_retries - 1:
                time.sleep(0.2)

    return (
        pd.DataFrame(),
        "INSUFFICIENT_HISTORICAL_DATA",
        [f"[{sym}] Không thể lấy dữ liệu lịch sử thực tế từ vnstock."],
    )
