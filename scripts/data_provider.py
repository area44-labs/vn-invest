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

    TRANSIENT_REQUESTS_EXCEPTIONS: tuple[type[BaseException], ...] = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
    )
except ImportError:
    TRANSIENT_REQUESTS_EXCEPTIONS = ()

# Provider unit constants
SOURCE_PRICE_UNIT_VNSTOCK = "thousand_VND/share"
SOURCE_VOLUME_UNIT_VNSTOCK = "shares"
INDEX_SYMBOLS = {"VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX", "VN30INDEX"}
REQUIRED_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


class CanonicalOHLCVError(ValueError):
    """Exception raised when canonical OHLCV validation fails."""


class ProviderRateLimitError(Exception):
    """Exception raised when the market data provider encounters a rate limit condition."""

    def __init__(
        self, message: str, cooldown_seconds: int | None = None, symbol: str | None = None
    ):
        super().__init__(message)
        self.cooldown_seconds = cooldown_seconds
        self.symbol = symbol


# Global process-wide rate limit circuit breaker state
_CIRCUIT_BREAKER_ACTIVE = False
_CIRCUIT_BREAKER_REASON = ""
_CIRCUIT_BREAKER_COOLDOWN = None

MAX_PIPELINE_RATE_LIMIT_RECOVERIES = 10
_RATE_LIMIT_RECOVERY_COUNT = 0


def get_rate_limit_recovery_count() -> int:
    """Return total number of rate-limit recoveries performed during the current process run."""
    return _RATE_LIMIT_RECOVERY_COUNT


def can_recover_rate_limit() -> bool:
    """Return True if total rate-limit recoveries are within the maximum allowed budget."""
    return _RATE_LIMIT_RECOVERY_COUNT < MAX_PIPELINE_RATE_LIMIT_RECOVERIES


def reset_rate_limit_recovery_count() -> None:
    """Reset the pipeline rate-limit recovery counter and circuit breaker state."""
    global _RATE_LIMIT_RECOVERY_COUNT
    _RATE_LIMIT_RECOVERY_COUNT = 0
    reset_circuit_breaker()


def increment_rate_limit_recovery_count() -> None:
    """Increment the pipeline rate-limit recovery counter."""
    global _RATE_LIMIT_RECOVERY_COUNT
    _RATE_LIMIT_RECOVERY_COUNT += 1


def is_circuit_breaker_active() -> bool:
    """Return True if the process-wide rate-limit circuit breaker is active."""
    return _CIRCUIT_BREAKER_ACTIVE


def get_circuit_breaker_info() -> tuple[bool, str, int | None]:
    """Get process-wide circuit breaker state info (is_active, reason, cooldown_seconds)."""
    return _CIRCUIT_BREAKER_ACTIVE, _CIRCUIT_BREAKER_REASON, _CIRCUIT_BREAKER_COOLDOWN


def reset_circuit_breaker() -> None:
    """Reset process-wide circuit breaker state (useful for testing or process restarts)."""
    global _CIRCUIT_BREAKER_ACTIVE, _CIRCUIT_BREAKER_REASON, _CIRCUIT_BREAKER_COOLDOWN
    _CIRCUIT_BREAKER_ACTIVE = False
    _CIRCUIT_BREAKER_REASON = ""
    _CIRCUIT_BREAKER_COOLDOWN = None


def trip_circuit_breaker(reason: str, cooldown_seconds: int | None = None) -> None:
    """Trip process-wide rate-limit circuit breaker."""
    global _CIRCUIT_BREAKER_ACTIVE, _CIRCUIT_BREAKER_REASON, _CIRCUIT_BREAKER_COOLDOWN
    _CIRCUIT_BREAKER_ACTIVE = True
    _CIRCUIT_BREAKER_REASON = reason
    _CIRCUIT_BREAKER_COOLDOWN = cooldown_seconds


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

TRANSIENT_HTTP_STATUS_CODES = {500, 502, 503, 504}

PROVIDER_RATE_LIMIT_PATTERNS = [
    "ratelimitederror",
    "rate limit",
    "giới hạn",
    "quota",
    "too many requests",
    "429",
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


def is_rate_limit_exception(exc: BaseException) -> bool:
    """Determine whether an exception or SystemExit represents a rate-limit condition."""
    exc_type_name = type(exc).__name__.lower()
    if "ratelimit" in exc_type_name:
        return True

    # Check for structured HTTP response status code == 429
    response = getattr(exc, "response", None)
    if response is not None and hasattr(response, "status_code"):
        try:
            if int(response.status_code) == 429:
                return True
        except ValueError, TypeError:
            pass

    err_msg = get_exception_message(exc).lower()
    return any(pattern in err_msg for pattern in PROVIDER_RATE_LIMIT_PATTERNS)


def is_client_auth_exception(exc: BaseException) -> bool:
    """Determine whether an exception represents a client/auth/permission error (all HTTP 4xx status codes except 429 Rate Limit)."""
    response = getattr(exc, "response", None)
    if response is not None and hasattr(response, "status_code"):
        try:
            status_code = int(response.status_code)
            return 400 <= status_code < 500 and status_code != 429
        except ValueError, TypeError:
            pass
    return False


def is_transient_exception(exc: BaseException) -> bool:
    """Determine whether an exception represents a transient network/server error (500, 502, 503, 504, ConnectionError, TimeoutError)."""
    if isinstance(exc, TRANSIENT_EXCEPTION_TYPES):
        return True

    if TRANSIENT_REQUESTS_EXCEPTIONS and isinstance(exc, TRANSIENT_REQUESTS_EXCEPTIONS):
        return True

    response = getattr(exc, "response", None)
    if response is not None and hasattr(response, "status_code"):
        try:
            status_code = int(response.status_code)
            if status_code in TRANSIENT_HTTP_STATUS_CODES:
                return True
        except ValueError, TypeError:
            pass

    return False


def is_vnstock_rate_limit_exit(exc: BaseException) -> bool:
    """Determine whether a SystemExit represents a vnstock rate-limit condition."""
    return is_rate_limit_exception(exc)


def is_retryable_exception(exc: Exception) -> bool:
    """Determine whether an exception represents a transient failure that can be retried.

    Rate limits and client/auth errors are NOT retryable.
    """
    if is_rate_limit_exception(exc) or is_client_auth_exception(exc):
        return False
    if isinstance(exc, NON_RETRYABLE_EXCEPTIONS):
        return False
    return is_transient_exception(exc)


def parse_wait_seconds(err_str: str, exc: BaseException | None = None) -> int:
    """Extract wait seconds from vnstock rate limit notice or exception retry_after attribute."""
    if exc is not None:
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            try:
                val = float(retry_after)
                if val > 0:
                    return round(val) + 2
            except ValueError, TypeError:
                pass

    match = re.search(r"(?:chờ|wait)?\s*(\d+)\s*(?:giây|seconds?|sec|s)\b", err_str, re.IGNORECASE)
    if match:
        return int(match.group(1)) + 2
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
        if is_circuit_breaker_active():
            _active, reason, cooldown = get_circuit_breaker_info()
            raise ProviderRateLimitError(
                f"Provider rate-limit circuit breaker is active. Skipping request for '{symbol}'. Reason: {reason}",
                cooldown_seconds=cooldown,
                symbol=symbol,
            )

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
                if is_circuit_breaker_active():
                    _active, reason, cooldown = get_circuit_breaker_info()
                    raise ProviderRateLimitError(
                        f"Provider rate-limit circuit breaker is active. Skipping request for '{sym}'. Reason: {reason}",
                        cooldown_seconds=cooldown,
                        symbol=sym,
                    )

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
                    if is_rate_limit_exception(exc):
                        err_msg = get_exception_message(exc)
                        cooldown_sec = parse_wait_seconds(err_msg, exc=exc)
                        trip_circuit_breaker(
                            reason=f"Rate limit encountered on symbol '{sym}' (source={source}): {err_msg}",
                            cooldown_seconds=cooldown_sec,
                        )
                        logger.error(
                            "Vnstock rate limit encountered for symbol '%s' (source=%s): %s. Tripping circuit breaker.",
                            sym,
                            source,
                            err_msg,
                        )
                        raise ProviderRateLimitError(
                            f"Vnstock provider rate limited for symbol '{sym}': {err_msg}",
                            cooldown_seconds=cooldown_sec,
                            symbol=sym,
                        ) from exc

                    if is_client_auth_exception(exc):
                        err_msg = get_exception_message(exc)
                        logger.error(
                            "Client/Auth error encountered for symbol '%s' (source=%s): %s. Failing fast.",
                            sym,
                            source,
                            err_msg,
                        )
                        raise

                    if not is_retryable_exception(exc):
                        raise

                    last_exception = exc
                    time.sleep(0.1)

            if attempt < max_retries - 1:
                time.sleep(0.2)

        if last_exception:
            raise RuntimeError(
                f"Failed to fetch valid canonical OHLCV from vnstock for '{sym}': {last_exception}"
            ) from last_exception

        raise RuntimeError(f"Failed to fetch valid canonical OHLCV from vnstock for '{sym}'.")
