"""Data Provider Module for VN Invest v2.

Isolates external market-data providers (such as vnstock) behind a clean boundary,
normalizes units into internal canonical format, and validates canonical OHLCV data
before passing it to the quantitative engine.
"""

import logging
import re
import time
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    from vnstock.api.quote import Quote as VnQuote

    VNSTOCK_AVAILABLE = True
except ImportError:
    VNSTOCK_AVAILABLE = False

try:
    import requests

    REQUESTS_EXCEPTIONS: tuple[type[BaseException], ...] = (requests.exceptions.RequestException,)
except ImportError:
    REQUESTS_EXCEPTIONS = ()

# Provider unit constants
SOURCE_PRICE_UNIT_VNSTOCK = "thousand_VND/share"
SOURCE_VOLUME_UNIT_VNSTOCK = "shares"
INDEX_SYMBOLS = {"VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX", "VN30INDEX"}
REQUIRED_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


class CanonicalOHLCVError(ValueError):
    """Exception raised when canonical OHLCV validation fails."""


NON_RETRYABLE_EXCEPTIONS = (
    CanonicalOHLCVError,
    TypeError,
    ValueError,
    KeyError,
    AttributeError,
    IndexError,
)

TRANSIENT_EXCEPTION_TYPES = (
    ConnectionError,
    TimeoutError,
)

RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}

PROVIDER_RATE_LIMIT_PATTERNS = [
    "rate limit",
    "giới hạn",
    "wait",
    "quota",
    "temporarily unavailable",
    "service unavailable",
    "too many requests",
]


def get_exception_message(exc: BaseException) -> str:
    """Extract normalized string representation of an exception including str(exc) and exc.code if present."""
    msg = str(exc)
    code = getattr(exc, "code", None)
    if code is not None:
        code_str = str(code)
        if code_str and code_str not in msg:
            msg = f"{msg} {code_str}".strip() if msg else code_str
    return msg


def is_vnstock_rate_limit_exit(exc: BaseException) -> bool:
    """Determine whether a SystemExit represents a vnstock rate-limit condition."""
    if not isinstance(exc, SystemExit):
        return False
    msg_str = get_exception_message(exc).lower()
    return any(p in msg_str for p in ["rate limit", "giới hạn", "wait", "quota", "429"])


def is_retryable_exception(exc: Exception) -> bool:
    """Determine whether an exception represents a transient failure that can be retried.

    Non-retryable failures include:
    - CanonicalOHLCVError (validation failures on returned data)
    - TypeError, ValueError, KeyError, AttributeError, IndexError (deterministic code/data errors)
    - Generic OSError (non-network system/IO errors)
    - Deterministic HTTP client errors (e.g., 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found)

    Retryable failures include:
    - Explicit network/connection/timeout exceptions (ConnectionError, TimeoutError)
    - Structured HTTP response status codes in 429 (Too Many Requests) or 5xx (Server Error)
    - Provider-specific rate limit, quota, and wait notices in exception messages
    """
    if isinstance(exc, NON_RETRYABLE_EXCEPTIONS):
        return False

    # Check for structured HTTP response status code if attached
    response = getattr(exc, "response", None)
    if response is not None and hasattr(response, "status_code"):
        try:
            status_code = int(response.status_code)
            if status_code in RETRYABLE_HTTP_STATUS_CODES:
                return True
            if 400 <= status_code < 500:
                return False
            if status_code >= 500:
                return True
        except ValueError, TypeError:
            pass

    # Standard Requests exceptions without explicit response status or with request-level failures
    if REQUESTS_EXCEPTIONS and isinstance(exc, REQUESTS_EXCEPTIONS):
        # HTTPError with response is handled above; other RequestExceptions (ConnectionError, Timeout) are retryable
        return True

    if isinstance(exc, TRANSIENT_EXCEPTION_TYPES):
        return True

    err_str = get_exception_message(exc).lower()
    return any(p in err_str for p in PROVIDER_RATE_LIMIT_PATTERNS)


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


def validate_canonical_ohlcv(df: pd.DataFrame) -> bool:
    """Validate that a DataFrame conforms strictly to canonical OHLCV requirements.

    Must reject:
    - Empty data (None or empty DataFrame)
    - Missing required columns (date/time, open, high, low, close, volume)
    - Duplicate dates
    - Unsorted dates (must be strictly ascending)
    - NaN or Infinite values in numeric columns or dates
    - Invalid OHLC relationships (high < low, open > high, open < low, close > high, close < low)
    - Negative volume (volume < 0)

    Raises CanonicalOHLCVError with a clear, actionable error message on failure.
    Returns True if valid.
    """
    if df is None or df.empty:
        raise CanonicalOHLCVError("Empty dataset: DataFrame is None or empty.")

    # Column inspection
    cols_lower = [str(c).lower() for c in df.columns]
    col_map = {str(c).lower(): c for c in df.columns}

    date_col = None
    for candidate in ["time", "date"]:
        if candidate in cols_lower:
            date_col = col_map[candidate]
            break

    if not date_col:
        raise CanonicalOHLCVError(
            "Missing date column: DataFrame must contain a 'time' or 'date' column."
        )

    missing_cols = [c for c in REQUIRED_OHLCV_COLUMNS if c not in cols_lower]
    if missing_cols:
        raise CanonicalOHLCVError(
            f"Missing required columns: DataFrame missing required OHLCV column(s) {missing_cols}."
        )

    # Date parsing and NaN check
    parsed_dates = pd.to_datetime(df[date_col], errors="coerce")
    if parsed_dates.isna().any():
        raise CanonicalOHLCVError("NaN or invalid date values detected in date column.")

    # Duplicate dates check
    if parsed_dates.duplicated().any():
        raise CanonicalOHLCVError("Duplicate dates detected in OHLCV date column.")

    # Date ordering check (must be strictly ascending)
    if not parsed_dates.is_monotonic_increasing:
        raise CanonicalOHLCVError(
            "Unsorted dates detected in OHLCV data: dates must be strictly ascending."
        )

    # Numeric columns NaN and Infinite check
    for col_name in REQUIRED_OHLCV_COLUMNS:
        orig_col = col_map[col_name]
        series = pd.to_numeric(df[orig_col], errors="coerce")
        if series.isna().any():
            raise CanonicalOHLCVError(f"NaN values detected in numeric column '{col_name}'.")
        arr = series.to_numpy()
        if np.isinf(arr).any():
            raise CanonicalOHLCVError(f"Infinite values detected in numeric column '{col_name}'.")

    # Numeric values extraction for relational checks
    open_s = pd.to_numeric(df[col_map["open"]])
    high_s = pd.to_numeric(df[col_map["high"]])
    low_s = pd.to_numeric(df[col_map["low"]])
    close_s = pd.to_numeric(df[col_map["close"]])
    vol_s = pd.to_numeric(df[col_map["volume"]])

    # Negative volume check
    if (vol_s < 0).any():
        raise CanonicalOHLCVError("Negative volume detected in OHLCV volume column.")

    # Invalid OHLC relationship check
    # high < low, open > high, open < low, close > high, close < low
    invalid_ohlc = (
        (high_s < low_s)
        | (open_s > high_s)
        | (open_s < low_s)
        | (close_s > high_s)
        | (close_s < low_s)
    )
    if invalid_ohlc.any():
        raise CanonicalOHLCVError(
            "Invalid OHLC relationship detected: prices violate low <= open/close <= high."
        )

    return True


class VnstockDataProvider:
    """Adapter/boundary for external vnstock market-data provider."""

    def __init__(self, is_available: bool = VNSTOCK_AVAILABLE):
        self.is_available = is_available

    def fetch_ohlcv(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        max_retries: int = 2,
    ) -> pd.DataFrame:
        """Fetch real historical EOD OHLCV data for a given symbol from vnstock.

        Converts provider output into canonical internal representation, normalizes units,
        runs validation, and returns canonical OHLCV DataFrame.
        """
        if not self.is_available:
            raise RuntimeError("vnstock provider package is not available in environment.")

        sym = symbol.strip().upper()
        if not start_date or not end_date:
            now_dt = datetime.now(UTC)
            end_date = now_dt.strftime("%Y-%m-%d")
            start_date = (now_dt - timedelta(days=365)).strftime("%Y-%m-%d")

        sources = ["kbs", "msn"]
        last_exception = None

        for attempt in range(max_retries):
            for source in sources:
                try:
                    q = VnQuote(symbol=sym, source=source)
                    raw_df = q.history(start=start_date, end=end_date)
                    if raw_df is not None and not raw_df.empty:
                        # Convert column names to lowercase
                        df_norm = raw_df.copy()
                        df_norm.columns = [str(c).lower() for c in df_norm.columns]

                        # Unit normalization: stocks in thousand_VND/share -> VND/share
                        if sym not in INDEX_SYMBOLS:
                            price_cols = [
                                c
                                for c in ["open", "high", "low", "close", "vwap"]
                                if c in df_norm.columns
                            ]
                            for col in price_cols:
                                df_norm[col] = pd.to_numeric(df_norm[col], errors="coerce") * 1000.0

                        # Run canonical validation
                        validate_canonical_ohlcv(df_norm)
                        return df_norm
                except (Exception, SystemExit) as exc:
                    if isinstance(exc, SystemExit):
                        if not is_vnstock_rate_limit_exit(exc):
                            raise
                    elif not is_retryable_exception(exc):
                        raise

                    last_exception = exc
                    err_msg = get_exception_message(exc)
                    err_str = err_msg.lower()
                    is_rate_limit = any(
                        x in err_str
                        for x in [
                            "rate limit",
                            "giới hạn",
                            "wait",
                            "quota",
                            "429",
                        ]
                    )

                    if is_rate_limit:
                        wait_sec = parse_wait_seconds(err_msg)
                        logger.warning(
                            "Rate limit encountered for '%s' (source=%s). Waiting %d seconds before retrying...",
                            sym,
                            source,
                            wait_sec,
                        )
                        time.sleep(wait_sec)
                    else:
                        time.sleep(0.1)
            if attempt < max_retries - 1:
                time.sleep(0.2)

        if last_exception:
            raise RuntimeError(
                f"Failed to fetch valid canonical OHLCV from vnstock for '{sym}': {last_exception}"
            ) from last_exception

        raise RuntimeError(f"Failed to fetch valid canonical OHLCV from vnstock for '{sym}'.")
