"""Unit tests for data provider boundary and canonical OHLCV validator.

Deterministic tests without network access covering all 13 canonical validator requirements
and provider boundary conversion/validation.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from vnai.beam.quota import RateLimitExceeded

from scripts.data.acquisition import InvalidSymbolError, get_historical_data
from scripts.data_provider import (
    CanonicalOHLCVError,
    ProviderRateLimitError,
    VnstockDataProvider,
    get_rate_limit_recovery_count,
    is_circuit_breaker_active,
    reset_circuit_breaker,
    reset_rate_limit_recovery_count,
    trip_circuit_breaker,
    validate_canonical_ohlcv,
)


def make_valid_canonical_df(num_rows: int = 25, start_date: str = "2026-08-01") -> pd.DataFrame:
    """Construct a valid canonical EOD OHLCV DataFrame."""
    dates = pd.date_range(start=start_date, periods=num_rows, freq="D").strftime("%Y-%m-%d")
    data = []
    base_price = 50000.0  # VND/share
    for i, d in enumerate(dates):
        p = base_price + (i * 100.0)
        data.append(
            {
                "time": d,
                "open": p,
                "high": p + 500.0,
                "low": p - 500.0,
                "close": p + 200.0,
                "volume": 100000 + (i * 1000),
            }
        )
    return pd.DataFrame(data)


@pytest.mark.unit
class TestCanonicalOHLCVValidator:
    def test_valid_ohlcv_passes_validation(self):
        """Valid canonical OHLCV data passes validation."""
        df = make_valid_canonical_df(25)
        assert validate_canonical_ohlcv(df)

    def test_empty_dataframe_fails_validation(self):
        """Empty DataFrame or None fails validation."""
        with pytest.raises(CanonicalOHLCVError) as ctx_none:
            validate_canonical_ohlcv(None)
        assert "Empty dataset" in str(ctx_none.value)

        with pytest.raises(CanonicalOHLCVError) as ctx_empty:
            validate_canonical_ohlcv(pd.DataFrame())
        assert "Empty dataset" in str(ctx_empty.value)

    def test_missing_required_column_fails_validation(self):
        """Missing required OHLCV column fails validation."""
        df = make_valid_canonical_df(20)
        df_no_close = df.drop(columns=["close"])
        with pytest.raises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df_no_close)
        assert "Missing required columns" in str(ctx.value)

        df_no_date = df.drop(columns=["time"])
        with pytest.raises(CanonicalOHLCVError) as ctx_date:
            validate_canonical_ohlcv(df_no_date)
        assert "Missing date column" in str(ctx_date.value)

    def test_duplicate_dates_fail_validation(self):
        """Duplicate dates fail validation."""
        df = make_valid_canonical_df(20)
        df.loc[10, "time"] = df.loc[9, "time"]
        with pytest.raises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        assert "Duplicate dates detected" in str(ctx.value)

    def test_unsorted_dates_fail_validation(self):
        """Unsorted dates fail validation."""
        df = make_valid_canonical_df(20)
        # Swap date at index 5 and 6 so date order is non-monotonic
        tmp = df.loc[5, "time"]
        df.loc[5, "time"] = df.loc[6, "time"]
        df.loc[6, "time"] = tmp
        with pytest.raises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        assert "Unsorted dates detected" in str(ctx.value)

    def test_nan_values_fail_validation(self):
        """NaN values fail validation."""
        df = make_valid_canonical_df(20)
        df.loc[8, "close"] = np.nan
        with pytest.raises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        assert "NaN values detected" in str(ctx.value)

    def test_infinite_value_fails_validation(self):
        """Infinite values fail validation."""
        df = make_valid_canonical_df(20)
        df.loc[5, "close"] = np.inf
        with pytest.raises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        assert "Infinite values detected" in str(ctx.value)

    def test_high_less_than_low_fails_validation(self):
        """'high < low' fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[4, "high"] = 40000.0
        df.loc[4, "low"] = 50000.0
        with pytest.raises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        assert "Invalid OHLC relationship" in str(ctx.value)

    def test_open_greater_than_high_fails_validation(self):
        """'open > high' fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[3, "open"] = 60000.0
        df.loc[3, "high"] = 55000.0
        with pytest.raises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        assert "Invalid OHLC relationship" in str(ctx.value)

    def test_open_less_than_low_fails_validation(self):
        """'open < low' fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[3, "open"] = 45000.0
        df.loc[3, "low"] = 48000.0
        with pytest.raises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        assert "Invalid OHLC relationship" in str(ctx.value)

    def test_close_greater_than_high_fails_validation(self):
        """'close > high' fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[2, "close"] = 60000.0
        df.loc[2, "high"] = 55000.0
        with pytest.raises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        assert "Invalid OHLC relationship" in str(ctx.value)

    def test_close_less_than_low_fails_validation(self):
        """'close < low' fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[2, "close"] = 40000.0
        df.loc[2, "low"] = 48000.0
        with pytest.raises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        assert "Invalid OHLC relationship" in str(ctx.value)

    def test_negative_volume_fails_validation(self):
        """Negative volume fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[7, "volume"] = -100
        with pytest.raises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        assert "Negative volume detected" in str(ctx.value)


@pytest.mark.unit
class TestVnstockProviderBoundary:
    @patch("scripts.data_provider.VnQuote")
    def test_provider_boundary_mock_integration(self, mock_vnquote_cls):
        """Demonstrate provider output -> canonical conversion -> validation without live network."""
        # Raw provider output from vnstock (prices in thousand_VND/share, e.g. 128.4)
        raw_data = []
        dates = pd.date_range(start="2026-08-01", periods=10, freq="D").strftime("%Y-%m-%d")
        for i, d in enumerate(dates):
            raw_data.append(
                {
                    "time": d,
                    "open": 100.0 + i,
                    "high": 105.0 + i,
                    "low": 95.0 + i,
                    "close": 102.0 + i,
                    "volume": 500000 + (i * 1000),
                }
            )
        raw_df = pd.DataFrame(raw_data)

        mock_quote_inst = MagicMock()
        mock_quote_inst.history.return_value = raw_df
        mock_vnquote_cls.return_value = mock_quote_inst

        provider = VnstockDataProvider(is_available=True)
        canonical_df = provider.fetch_ohlcv("FPT", "2026-08-01", "2026-08-10")

        # Verify unit normalization (100.0 thousand VND -> 100,000 VND)
        assert canonical_df.loc[0, "open"] == 100000.0
        assert canonical_df.loc[0, "close"] == 102000.0
        assert canonical_df.loc[0, "high"] == 105000.0
        assert canonical_df.loc[0, "low"] == 95000.0
        assert canonical_df.loc[0, "volume"] == 500000

        # Verify validation passed and DataFrame is canonical
        assert validate_canonical_ohlcv(canonical_df)


@pytest.mark.unit
class TestDataProviderExceptionHandling:
    def setup_method(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    def teardown_method(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_rate_limited_error_class_is_not_retried(self, mock_quote, mock_sleep):
        """RateLimitedError exception class is NOT retried, does not switch sources, and trips circuit breaker."""

        class RateLimitedError(Exception):
            pass

        mock_inst = MagicMock()
        mock_inst.history.side_effect = RateLimitedError("API Rate limit exceeded. Chờ 30 giây")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("FPT", max_retries=3)

        assert mock_inst.history.call_count == 1
        assert is_circuit_breaker_active()
        assert ctx.value.cooldown_seconds == 32
        assert ctx.value.symbol == "FPT"

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_429_is_not_retried(self, mock_quote, mock_sleep):
        """HTTP 429 status code is NOT retried, does not switch sources, and trips circuit breaker."""
        err = Exception("HTTP 429 Too Many Requests")
        res_mock = MagicMock()
        res_mock.status_code = 429
        err.response = res_mock

        mock_inst = MagicMock()
        mock_inst.history.side_effect = err
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(ProviderRateLimitError):
            provider.fetch_ohlcv("FPT", max_retries=3)

        assert mock_inst.history.call_count == 1
        assert is_circuit_breaker_active()

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_rate_limit_prevents_subsequent_symbol_requests(self, mock_quote, mock_sleep):
        """A rate-limit event trips the process-wide circuit breaker and prevents subsequent requests for other symbols."""

        class RateLimitedError(Exception):
            pass

        mock_inst = MagicMock()
        mock_inst.history.side_effect = RateLimitedError("Rate limit exceeded")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)

        # First request for FPT hits rate limit
        with pytest.raises(ProviderRateLimitError):
            provider.fetch_ohlcv("FPT")

        assert mock_inst.history.call_count == 1
        assert is_circuit_breaker_active()

        # Second request for HPG should fail immediately via circuit breaker without making any VnQuote calls
        mock_inst.reset_mock()
        with pytest.raises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("HPG")

        assert mock_inst.history.call_count == 0
        assert "circuit breaker is active" in str(ctx.value)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_500_502_503_504_have_bounded_retry(self, mock_quote, mock_sleep):
        """Server errors 500/502/503/504 have bounded retry behavior across sources and attempts."""

        def make_server_err(code: int):
            e = Exception(f"Server Error {code}")
            r = MagicMock()
            r.status_code = code
            e.response = r
            return e

        for status_code in [500, 502, 503, 504]:
            mock_inst = MagicMock()
            mock_inst.history.side_effect = make_server_err(status_code)
            mock_quote.return_value = mock_inst

            provider = VnstockDataProvider(is_available=True)
            with pytest.raises(RuntimeError) as ctx:
                provider.fetch_ohlcv("FPT", max_retries=2)

            assert "Failed to fetch valid canonical OHLCV" in str(ctx.value)
            # 2 attempts * 2 sources = 4 calls total
            assert mock_inst.history.call_count == 4
            assert not is_circuit_breaker_active()

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_401_403_fail_fast(self, mock_quote, mock_sleep):
        """Client/Auth errors (400, 401, 403, 404) fail fast without retrying or switching sources."""
        for status_code in [400, 401, 403, 404]:
            err = Exception(f"HTTP {status_code} Error")
            res_mock = MagicMock()
            res_mock.status_code = status_code
            err.response = res_mock

            mock_inst = MagicMock()
            mock_inst.history.side_effect = err
            mock_quote.return_value = mock_inst

            provider = VnstockDataProvider(is_available=True)
            with pytest.raises(Exception) as ctx:
                provider.fetch_ohlcv("FPT", max_retries=3)

            assert f"HTTP {status_code} Error" in str(ctx.value)
            # Fails immediately on 1st call without trying 2nd source or 2nd/3rd attempt
            assert mock_inst.history.call_count == 1
            assert not is_circuit_breaker_active()

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_generic_request_exception_fails_fast(self, mock_quote, mock_sleep):
        """A generic requests.exceptions.RequestException is NOT treated as transient and fails fast."""
        import requests

        generic_err = requests.exceptions.RequestException("Generic request error")
        mock_inst = MagicMock()
        mock_inst.history.side_effect = generic_err
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(requests.exceptions.RequestException):
            provider.fetch_ohlcv("FPT", max_retries=3)

        # Fails fast immediately on 1st call without retrying or trying 2nd source
        assert mock_inst.history.call_count == 1

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_408_fails_fast(self, mock_quote, mock_sleep):
        """HTTP 408 Request Timeout is treated as a client error and fails fast."""

        class HTTP408Error(Exception):
            pass

        err = HTTP408Error("HTTP 408 Request Timeout")
        res_mock = MagicMock()
        res_mock.status_code = 408
        err.response = res_mock

        mock_inst = MagicMock()
        mock_inst.history.side_effect = err
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(HTTP408Error):
            provider.fetch_ohlcv("FPT", max_retries=3)

        assert mock_inst.history.call_count == 1

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_parse_wait_seconds_formats(self, mock_quote, mock_sleep):
        """parse_wait_seconds handles 'wait 10 seconds', 'wait 10 sec', 'Chờ 10 giây', 40s/60s, retry_after attr, and fallback."""
        from scripts.data_provider import parse_wait_seconds

        assert parse_wait_seconds("Rate limit. wait 10 seconds") == 12
        assert parse_wait_seconds("Rate limit. wait 10 sec") == 12
        assert parse_wait_seconds("Rate limit. Chờ 10 giây") == 12
        assert parse_wait_seconds("Rate limit. Chờ 40 giây") == 42
        assert parse_wait_seconds("Rate limit. Chờ 60 giây") == 62
        assert parse_wait_seconds("Rate limit. 40s") == 42
        assert parse_wait_seconds("Rate limit. 60s") == 62
        assert parse_wait_seconds("Rate limit. 10 sec") == 12
        assert parse_wait_seconds("Rate limit. No numbers here") == 15

        # Test with real RateLimitExceeded instance having retry_after attribute
        exc_40 = RateLimitExceeded("quote.history", "min", 20, 20, retry_after=40.0, tier="guest")
        assert parse_wait_seconds(str(exc_40), exc=exc_40) == 42

        exc_60 = RateLimitExceeded("quote.history", "min", 60, 60, retry_after=60.0, tier="free")
        assert parse_wait_seconds(str(exc_60), exc=exc_60) == 62

        # Test fallback edge cases: invalid/zero/None retry_after attributes
        exc_invalid_retry = RateLimitExceeded(
            "quote.history", "min", 20, 20, retry_after=None, tier="guest"
        )
        exc_invalid_retry.retry_after = "invalid"
        assert (
            parse_wait_seconds("Rate limit reached. Wait 40 seconds", exc=exc_invalid_retry) == 42
        )

        exc_zero_retry = RateLimitExceeded(
            "quote.history", "min", 20, 20, retry_after=None, tier="guest"
        )
        exc_zero_retry.retry_after = 0
        assert parse_wait_seconds("Rate limit reached. Wait 60 seconds", exc=exc_zero_retry) == 62

        exc_none_retry = RateLimitExceeded(
            "quote.history", "min", 20, 20, retry_after=None, tier="guest"
        )
        assert parse_wait_seconds("Rate limit reached. Chờ 50 giây", exc=exc_none_retry) == 52

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_generic_wait_message_does_not_trip_circuit_breaker(self, mock_quote, mock_sleep):
        """A generic exception containing the word 'wait' is NOT classified as a rate limit and does NOT trip the circuit breaker."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = ConnectionError(
            "Please wait while the server processes the request"
        )
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(RuntimeError) as ctx:
            provider.fetch_ohlcv("FPT", max_retries=2)

        assert "Failed to fetch valid canonical OHLCV" in str(ctx.value)
        # It was treated as a transient ConnectionError, so it retried (2 attempts * 2 sources = 4 calls)
        assert mock_inst.history.call_count == 4
        assert not is_circuit_breaker_active()

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_retries_transient_network_exception_and_exhausts(
        self, mock_quote, mock_sleep
    ):
        """Transient network exceptions (ConnectionError, TimeoutError) are retried until max_retries exhausted."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = ConnectionError("Connection reset by peer")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(RuntimeError) as ctx:
            provider.fetch_ohlcv("FPT", max_retries=2)

        assert "Failed to fetch valid canonical OHLCV" in str(ctx.value)
        assert mock_inst.history.call_count == 4
        assert not is_circuit_breaker_active()

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_succeeds_after_transient_retry(self, mock_quote, mock_sleep):
        """Transient failure on first call succeeds on subsequent retry."""
        valid_df = make_valid_canonical_df(10)
        raw_df = valid_df.copy()
        for col in ["open", "high", "low", "close"]:
            raw_df[col] = raw_df[col] / 1000.0

        mock_inst = MagicMock()
        mock_inst.history.side_effect = [
            TimeoutError("Request timed out"),
            raw_df,
        ]
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        df_res = provider.fetch_ohlcv("FPT", max_retries=2)

        assert df_res is not None
        assert len(df_res) == 10
        assert mock_inst.history.call_count == 2
        assert not is_circuit_breaker_active()

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_fails_fast_on_non_retryable_data_error(self, mock_quote, mock_sleep):
        """Deterministic non-retryable exceptions (CanonicalOHLCVError, ValueError, TypeError, OSError) re-raise immediately."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = CanonicalOHLCVError("Invalid OHLC relationship")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(CanonicalOHLCVError):
            provider.fetch_ohlcv("FPT", max_retries=2)

        assert mock_inst.history.call_count == 1

        mock_inst.reset_mock()
        mock_inst.history.side_effect = OSError("Disk read error")
        with pytest.raises(OSError):
            provider.fetch_ohlcv("FPT", max_retries=2)

        assert mock_inst.history.call_count == 1

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_preserves_non_rate_limit_system_exit(self, mock_quote, mock_sleep):
        """Non-rate-limit SystemExit is NOT caught and propagates immediately without retrying."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = SystemExit("Generic system exit")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(SystemExit):
            provider.fetch_ohlcv("FPT", max_retries=2)

        assert mock_inst.history.call_count == 1
        assert not is_circuit_breaker_active()

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_catches_rate_limit_system_exit_and_trips_circuit_breaker(
        self, mock_quote, mock_sleep
    ):
        """Rate limit SystemExit trips circuit breaker immediately without retrying."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = SystemExit("Rate limit exceeded. Chờ 10 giây để tiếp tục")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("FPT", max_retries=2)

        assert mock_inst.history.call_count == 1
        assert is_circuit_breaker_active()
        assert ctx.value.cooldown_seconds == 12

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_preserves_keyboard_interrupt(self, mock_quote, mock_sleep):
        """KeyboardInterrupt is NOT caught by fetch_ohlcv and propagates immediately."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = KeyboardInterrupt("Ctrl+C pressed")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(KeyboardInterrupt):
            provider.fetch_ohlcv("FPT", max_retries=2)

        assert mock_inst.history.call_count == 1


@pytest.mark.unit
class TestVnstockRealRateLimitRegression:
    """Focused regression tests using real Vnstock / Vnai rate-limit exception shapes."""

    def setup_method(self):
        reset_circuit_breaker()

    def teardown_method(self):
        reset_circuit_breaker()

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_real_vnai_rate_limit_exceeded_exception_40s_cooldown(self, mock_quote, mock_sleep):
        """Regression test verifying real Vnai RateLimitExceeded exception format with 40s wait."""
        exc = RateLimitExceeded(
            resource_type="quote.history",
            limit_type="min",
            current_usage=20,
            limit_value=20,
            retry_after=40.0,
            tier="guest",
        )

        mock_inst = MagicMock()
        mock_inst.history.side_effect = exc
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)

        with pytest.raises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("FPT", max_retries=3)

        # 1. No retries occur (call_count == 1)
        assert mock_inst.history.call_count == 1

        # 2. Transformed to ProviderRateLimitError
        assert isinstance(ctx.value, ProviderRateLimitError)
        assert ctx.value.symbol == "FPT"

        # 3. Parsed cooldown is preserved (40 + 2 = 42 seconds)
        assert ctx.value.cooldown_seconds == 42

        # 4. Circuit breaker is activated
        assert is_circuit_breaker_active()

        # 5. Subsequent provider requests are blocked fast without making network calls
        mock_inst.reset_mock()
        with pytest.raises(ProviderRateLimitError) as ctx2:
            provider.fetch_ohlcv("VCB")

        assert mock_inst.history.call_count == 0
        assert "circuit breaker is active" in str(ctx2.value)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_real_vnstock_rate_limit_60s_english_message(self, mock_quote, mock_sleep):
        """Regression test verifying 60s English rate limit message using real RateLimitExceeded."""
        exc = RateLimitExceeded(
            resource_type="quote.history",
            limit_type="min",
            current_usage=60,
            limit_value=60,
            retry_after=60.0,
            tier="free",
        )

        mock_inst = MagicMock()
        mock_inst.history.side_effect = exc
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)

        with pytest.raises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("HPG", max_retries=3)

        assert mock_inst.history.call_count == 1
        assert ctx.value.cooldown_seconds == 62
        assert is_circuit_breaker_active()

    def test_pipeline_halts_and_preserves_generated_files_on_rate_limit(self):
        """Regression test verifying generate_report.py fails cleanly (exit code 1) and preserves generated files."""
        from scripts.generate_report import main as generate_report_main

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)

            recs_file = generated_dir / "recommendations.json"
            initial_content = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            recs_file.write_text(json.dumps(initial_content), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.generate_report.run_pipeline",
                    side_effect=ProviderRateLimitError("Rate limit reached", cooldown_seconds=42),
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx:
                    generate_report_main()

                # Pipeline exits with status code 1 for provider rate limits
                assert ctx.value.code == 1

            # Generated output file was NOT modified or overwritten
            saved_content = json.loads(recs_file.read_text(encoding="utf-8"))
            assert saved_content == initial_content

    def test_generate_report_three_exit_code_paths(self):
        """Regression test covering the 3 exit paths of generate_report.py:

        Path 1: Success pipeline completes cleanly without raising SystemExit (code 0).
        Path 2: ProviderRateLimitError raises SystemExit(1) and preserves generated files.
        Path 3: Unexpected exceptions propagate uncaught (producing exit 1 / error).
        """
        from scripts.generate_report import PipelineResult
        from scripts.generate_report import main as generate_report_main

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)

            recs_file = generated_dir / "recommendations.json"
            initial_recs = {"schema_version": "2.0", "recommendations": []}
            recs_file.write_text(json.dumps(initial_recs), encoding="utf-8")

            # Path 1: Successful run completes without raising SystemExit
            mock_payload = {
                "schema_version": "2.0",
                "signal_model_version": "2.0",
                "generated_at": "2026-09-24T00:00:00Z",
                "data_as_of": "2026-09-24",
                "source_date": "2026-09-24",
                "data_source": "REAL_DATA",
                "universe_info": {"universe_type": "TEST", "universe_size": 1},
                "market": {
                    "regime": "BULL",
                    "confidence": 0.8,
                    "trend": "UP",
                    "volatility": "LOW",
                    "liquidity": "HIGH",
                    "summary": "Bullish",
                },
                "summary": {
                    "total_scanned": 1,
                    "buy_count": 1,
                    "watch_count": 0,
                    "hold_count": 0,
                    "sell_count": 0,
                    "avoid_count": 0,
                },
                "recommendations": [
                    {
                        "symbol": "FPT",
                        "company_name": "FPT Corp",
                        "sector": "Tech",
                        "exchange": "HOSE",
                        "action": "BUY",
                        "signal_score": 85.0,
                        "risk_adjusted_score": 80.0,
                        "confidence": 0.85,
                        "data_quality": "SUFFICIENT",
                    }
                ],
            }
            mock_result = PipelineResult(
                mock_payload,
                mock_payload,
                mock_payload,
                df_vnindex=make_valid_canonical_df(25),
                df_vn30=make_valid_canonical_df(25),
            )

            mock_mon_res = MagicMock()
            mock_mon_res.overall_status = "PASS"
            mock_mon_res.to_dict.return_value = {"overall_status": "PASS"}

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch("scripts.generate_report.run_pipeline", return_value=mock_result),
                patch("jsonschema.validate", return_value=None),
                patch(
                    "scripts.pipeline.stages.evaluate_production_monitoring",
                    return_value=mock_mon_res,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                # Does NOT raise SystemExit on success
                generate_report_main()

            # Path 2: Rate limit error raises SystemExit(1)
            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.generate_report.run_pipeline",
                    side_effect=ProviderRateLimitError("Quota exceeded", cooldown_seconds=40),
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx2:
                    generate_report_main()

                assert ctx2.value.code == 1

            # Path 3: Unexpected error converts to SystemExit(1)
            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.generate_report.run_pipeline",
                    side_effect=RuntimeError("Unexpected pipeline exception"),
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx3:
                    generate_report_main()

                assert ctx3.value.code == 1


SMALL_TEST_UNIVERSE = [
    {"symbol": "ACB", "companyName": "ACB Bank", "sector": "Banking", "exchange": "HOSE"},
    {"symbol": "FPT", "companyName": "FPT Corp", "sector": "Tech", "exchange": "HOSE"},
    {"symbol": "HPG", "companyName": "Hoa Phat", "sector": "Steel", "exchange": "HOSE"},
]


@pytest.mark.unit
class TestRateLimitRecoveryAndPipelineReliability:
    """Focused tests for rate-limit recovery, universe scan continuity, and fail-closed report generation."""

    def setup_method(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()
        self.sleep_p1 = patch("scripts.data.acquisition.time.sleep")
        self.sleep_p2 = patch("scripts.data_provider.time.sleep")
        self.sleep_p3 = patch("scripts.pipeline.stages.time.sleep")
        self.univ_p = patch(
            "scripts.pipeline.stages.UniverseProvider._get_candidates",
            return_value=SMALL_TEST_UNIVERSE,
        )
        self.sleep_p1.start()
        self.sleep_p2.start()
        self.sleep_p3.start()
        self.univ_p.start()

    def teardown_method(self):
        patch.stopall()
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    @patch("scripts.pipeline.stages.time.sleep")
    @patch("scripts.data_provider.VnstockDataProvider.fetch_ohlcv")
    def test_run_pipeline_rate_limit_recovery_and_report_generation(self, mock_fetch, mock_sleep):
        """Exercises actual run_pipeline(update_data=True) flow:

        several symbols succeed -> one hits rate limit -> recovery occurs -> same symbol succeeds ->
        remaining symbols continue -> complete universe processed -> report generated.
        """
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        hpg_symbol = candidates[2]["symbol"] if len(candidates) > 2 else "HPG"

        rate_limit_exc = ProviderRateLimitError(
            f"Quota exceeded for {hpg_symbol}", cooldown_seconds=12, symbol=hpg_symbol
        )

        hpg_calls = 0

        def side_effect(symbol, start_date=None, end_date=None, max_retries=2, **kwargs):
            nonlocal hpg_calls
            if is_circuit_breaker_active():
                raise ProviderRateLimitError(
                    "Circuit breaker active", cooldown_seconds=12, symbol=symbol
                )
            if symbol == hpg_symbol:
                hpg_calls += 1
                if hpg_calls == 1:
                    raise rate_limit_exc
            return valid_df

        mock_fetch.side_effect = side_effect

        pipeline_res = run_pipeline(update_data=True)

        recs_data, _market_data, _ = pipeline_res

        # Complete universe processed
        assert recs_data["summary"]["total_scanned"] == len(candidates)
        assert len(recs_data["recommendations"]) == len(candidates)
        assert "market" in recs_data

        # HPG was called twice (initial rate limit + successful recovery retry)
        assert hpg_calls == 2
        # Rate limit recovery occurred and circuit breaker is clear
        assert get_rate_limit_recovery_count() == 1
        assert not is_circuit_breaker_active()
        mock_sleep.assert_any_call(12)

    def test_run_pipeline_incomplete_universe_fails_without_generating_report(self):
        """Regression test verifying that when one universe symbol remains invalid/empty,

        run_pipeline(update_data=True) fails closed and no final report files are generated or overwritten.
        """
        from scripts.generate_report import UniverseProvider
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        failing_sym = candidates[0]["symbol"]

        def mock_get_historical_data(symbol, **kwargs):
            if symbol == failing_sym:
                return pd.DataFrame()
            return valid_df

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)

            recs_file = generated_dir / "recommendations.json"
            market_file = generated_dir / "market.json"

            initial_recs = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            initial_market = {"regime": "NEUTRAL"}

            recs_file.write_text(json.dumps(initial_recs), encoding="utf-8")
            market_file.write_text(json.dumps(initial_market), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_get_historical_data,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx:
                    generate_report_main()

                # Pipeline exits with non-zero exit code 1
                assert ctx.value.code == 1

            # Neither recommendations.json nor market.json was modified or overwritten
            assert json.loads(recs_file.read_text(encoding="utf-8")) == initial_recs
            assert json.loads(market_file.read_text(encoding="utf-8")) == initial_market

    def test_run_pipeline_invalid_vn30_fails_without_generating_report(self):
        """Regression test verifying that when VN30 benchmark data is invalid/empty,

        run_pipeline(update_data=True) fails closed with RuntimeError and includes VN30 in invalid_symbols.
        """
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)

        def mock_get_historical_data(symbol, **kwargs):
            if symbol == "VN30":
                return pd.DataFrame()
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_historical_data,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "VN30" in str(ctx.value)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_unrecoverable_rate_limit_exhausts_budget_and_fails(self, mock_quote, mock_sleep):
        """Unrecoverable rate limit -> budget exhausted -> raises ProviderRateLimitError loudly."""
        rate_limit_exc = RateLimitExceeded(
            resource_type="quote.history",
            limit_type="min",
            current_usage=20,
            limit_value=20,
            retry_after=30.0,
            tier="guest",
        )
        mock_inst = MagicMock()
        mock_inst.history.side_effect = rate_limit_exc
        mock_quote.return_value = mock_inst

        with pytest.raises(ProviderRateLimitError) as ctx:
            # max_rate_limit_retries = 2
            get_historical_data("FPT", max_rate_limit_retries=2)

        # Fails after exhausting retries (attempts 0, 1, 2)
        assert ctx.value.symbol == "FPT"
        assert get_rate_limit_recovery_count() == 2


@pytest.mark.unit
class TestUniverseCompletenessValidation:
    """Offline unit tests verifying complete universe processing and fail-closed validation."""

    def setup_method(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()
        self.sleep_p1 = patch("scripts.data.acquisition.time.sleep")
        self.sleep_p2 = patch("scripts.data_provider.time.sleep")
        self.sleep_p3 = patch("scripts.pipeline.stages.time.sleep")
        self.univ_p = patch(
            "scripts.pipeline.stages.UniverseProvider._get_candidates",
            return_value=SMALL_TEST_UNIVERSE,
        )
        self.sleep_p1.start()
        self.sleep_p2.start()
        self.sleep_p3.start()
        self.univ_p.start()

    def teardown_method(self):
        patch.stopall()
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    def test_complete_universe_proceeds(self):
        """Complete universe -> report generation proceeds successfully."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)

        def mock_get_hist(symbol=None, **kwargs):
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            pipeline_res = run_pipeline(update_data=True)
            recs_data, market_data, _ = pipeline_res
            assert "recommendations" in recs_data
            assert "market" in market_data

    def test_one_expected_symbol_missing_fails(self):
        """One expected symbol missing -> fails closed with RuntimeError and preserves generated files."""
        from scripts.generate_report import UniverseProvider, run_pipeline
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates

        extra_candidates = list(candidates) + [
            {"symbol": "MISSING_SYM", "companyName": "Missing Corp", "sector": "Tech"}
        ]

        class DynamicCandidatesList(list):
            def __init__(self, full_list, missing_sym):
                super().__init__(full_list)
                self.missing_sym = missing_sym
                self._iter_count = 0

            def __iter__(self):
                self._iter_count += 1
                if self._iter_count == 1:
                    return super().__iter__()
                filtered = [
                    item
                    for item in list.__iter__(self)
                    if item["symbol"].upper() != self.missing_sym
                ]
                return iter(filtered)

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "MISSING_SYM":
                raise RuntimeError("Failed to fetch MISSING_SYM")
            return valid_df

        dynamic_candidates = DynamicCandidatesList(extra_candidates, "MISSING_SYM")

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            initial_recs = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            recs_file.write_text(json.dumps(initial_recs), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.pipeline.stages.UniverseProvider._get_candidates",
                    return_value=dynamic_candidates,
                ),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_get_hist,
                ),
            ):
                with pytest.raises(RuntimeError) as ctx:
                    run_pipeline(update_data=True)

                assert "MISSING_SYM" in str(ctx.value)

            # Reset dynamic_candidates iter_count for main() test
            dynamic_candidates._iter_count = 0
            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.pipeline.stages.UniverseProvider._get_candidates",
                    return_value=dynamic_candidates,
                ),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_get_hist,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx_exit:
                    generate_report_main()

                assert ctx_exit.value.code == 1

            # Output file was NOT modified
            assert json.loads(recs_file.read_text(encoding="utf-8")) == initial_recs

    def test_provider_failure_for_one_symbol_fails(self):
        """Provider failure for one symbol -> fails closed with RuntimeError."""
        from scripts.generate_report import UniverseProvider, run_pipeline
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        failed_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == failed_candidate:
                raise RuntimeError(f"[{sym}] Provider connection error")
            return valid_df

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            initial_recs = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            recs_file.write_text(json.dumps(initial_recs), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_get_hist,
                ),
            ):
                with pytest.raises(RuntimeError) as ctx:
                    run_pipeline(update_data=True)

                assert "Incomplete universe scan in update mode" in str(ctx.value)
                assert "Failed: 1" in str(ctx.value)
                assert failed_candidate in str(ctx.value)

                with patch("sys.argv", ["generate_report.py", "--update"]):
                    with pytest.raises(SystemExit) as ctx_exit:
                        generate_report_main()
                    assert ctx_exit.value.code == 1

            # Artifact preserved
            assert json.loads(recs_file.read_text(encoding="utf-8")) == initial_recs

    def test_one_explicitly_invalid_symbol_allowed(self):
        """One explicitly invalid symbol -> allowed if expected == processed ∪ invalid."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        invalid_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == invalid_candidate:
                raise InvalidSymbolError(f"Invalid symbol [{sym}]")
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            pipeline_res = run_pipeline(update_data=True)
            recs_data, _market_data, _ = pipeline_res
            assert "recommendations" in recs_data
            # The invalid symbol is present in recommendations with action AVOID
            invalid_recs = [
                r for r in recs_data["recommendations"] if r["symbol"] == invalid_candidate
            ]
            assert len(invalid_recs) == 1
            assert invalid_recs[0]["action"] == "AVOID"

    def test_get_historical_data_status_tag_distinctions(self):
        """Verify get_historical_data tags status strictly by issue type."""
        valid_df = make_valid_canonical_df(25)
        short_df = make_valid_canonical_df(5)
        empty_df = pd.DataFrame()
        missing_col_df = valid_df.drop(columns=["close"])
        missing_date_df = valid_df.drop(columns=["time"])

        with patch("scripts.data.acquisition.VnstockDataProvider") as mock_prov_cls:
            mock_prov = mock_prov_cls.return_value

            # 1. Valid data -> REAL_DATA
            mock_prov.fetch_ohlcv.return_value = valid_df
            _df, tag, _ = get_historical_data("FPT")
            assert tag == "REAL_DATA"

            # 2. Fewer than required valid rows -> INSUFFICIENT_HISTORICAL_DATA
            mock_prov.fetch_ohlcv.return_value = short_df
            _df, tag, _ = get_historical_data("FPT")
            assert tag == "INSUFFICIENT_HISTORICAL_DATA"

            # 3. Empty DataFrame -> PROVIDER_FAILURE
            mock_prov.fetch_ohlcv.return_value = empty_df
            _df, tag, _ = get_historical_data("FPT")
            assert tag == "PROVIDER_FAILURE"

            # 4. Missing required OHLCV column -> PROVIDER_FAILURE
            mock_prov.fetch_ohlcv.return_value = missing_col_df
            _df, tag, _ = get_historical_data("FPT")
            assert tag == "PROVIDER_FAILURE"

            # 5. Missing date column -> PROVIDER_FAILURE
            mock_prov.fetch_ohlcv.return_value = missing_date_df
            _df, tag, _ = get_historical_data("FPT")
            assert tag == "PROVIDER_FAILURE"

            # 6. Provider exception -> PROVIDER_FAILURE
            mock_prov.fetch_ohlcv.side_effect = RuntimeError("API connection timeout")
            _df, tag, _ = get_historical_data("FPT")
            assert tag == "PROVIDER_FAILURE"

    def test_valid_symbol_with_insufficient_history_fails(self):
        """Valid symbol with insufficient history -> tagged insufficient_history and fails update mode."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        insufficient_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == insufficient_candidate:
                return make_valid_canonical_df(5)
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.value)
            assert "Insufficient History: 1" in err_msg
            assert insufficient_candidate in err_msg

    def test_duplicate_symbol_does_not_inflate_processed_count(self):
        """Duplicate symbols in candidate list -> deduplicated, does not inflate processed count."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates

        # Create candidate list with duplicate FPT
        duplicate_candidates = list(candidates) + [candidates[0]]

        def mock_get_hist(symbol=None, **kwargs):
            return valid_df

        with (
            patch(
                "scripts.pipeline.stages.UniverseProvider._get_candidates",
                return_value=duplicate_candidates,
            ),
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_get_hist,
            ),
        ):
            pipeline_res = run_pipeline(update_data=True)
            recs_data, _, _ = pipeline_res
            assert "recommendations" in recs_data

        # Verify that if another symbol fails, duplicate FPT does NOT compensate for the failed symbol
        failed_sym = candidates[1]["symbol"].upper()

        def mock_get_hist_with_failure(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == failed_sym:
                raise RuntimeError("Provider failed")
            return valid_df

        with (
            patch(
                "scripts.pipeline.stages.UniverseProvider._get_candidates",
                return_value=duplicate_candidates,
            ),
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_get_hist_with_failure,
            ),
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "Failed: 1" in str(ctx.value)
            assert failed_sym in str(ctx.value)

    def test_empty_provider_result_fails_unless_explicitly_classified_invalid(self):
        """Empty provider result without explicit invalid classification -> treated as failed_symbols and fails closed."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        empty_candidate = candidates[1]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == empty_candidate:
                return pd.DataFrame()
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "Failed: 1" in str(ctx.value)
            assert empty_candidate in str(ctx.value)

    def test_partial_scan_fails(self):
        """Partial scan (loop terminates early or misses expected symbols) -> fails closed."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        unprocessed_candidate = candidates[-1]["symbol"].upper()

        # Simulate exception raised for the last candidate so it's not processed successfully
        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == unprocessed_candidate:
                raise RuntimeError(f"Processing error on {sym}")
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "Failed: 1" in str(ctx.value)
            assert unprocessed_candidate in str(ctx.value)

    def test_rate_limit_exception_propagates_directly(self):
        """Rate-limit exception -> propagates ProviderRateLimitError directly without converting to failed_symbols."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        rate_limit_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == rate_limit_candidate:
                raise ProviderRateLimitError("Quota exceeded", cooldown_seconds=30, symbol=sym)
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(ProviderRateLimitError) as ctx:
                run_pipeline(update_data=True)

            assert ctx.value.symbol == rate_limit_candidate

    def test_mixed_successful_invalid_failed_symbols_fails(self):
        """Mixed successful + invalid + insufficient history + failed symbols -> fails closed."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        invalid_candidate = candidates[0]["symbol"].upper()
        failed_candidate = candidates[1]["symbol"].upper()
        insufficient_candidate = candidates[2]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == invalid_candidate:
                raise InvalidSymbolError(f"Invalid symbol [{sym}]")
            if sym == failed_candidate:
                raise RuntimeError("Timeout error")
            if sym == insufficient_candidate:
                return make_valid_canonical_df(5)
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.value)
            assert "Invalid: 1" in err_msg
            assert "Failed: 1" in err_msg
            assert "Insufficient History: 1" in err_msg
            assert failed_candidate in err_msg
            assert insufficient_candidate in err_msg

    def test_completeness_validation_reports_useful_diagnostics(self):
        """Completeness validation error message reports all required diagnostic metrics."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        failed_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == failed_candidate:
                raise RuntimeError("Failed fetch")
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.value)
            assert "Incomplete universe scan in update mode" in err_msg
            assert "Expected:" in err_msg
            assert "Processed:" in err_msg
            assert "Invalid:" in err_msg
            assert "Failed:" in err_msg
            assert "Missing:" in err_msg
            assert "Failed symbols:" in err_msg
            assert "Missing symbols:" in err_msg

    def test_insufficient_history_symbol_cannot_make_scan_appear_complete(self):
        """Insufficient-history candidate cannot satisfy processed_symbols ∪ invalid_symbols."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        insufficient_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == insufficient_candidate:
                return make_valid_canonical_df(5)
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.value)
            assert "Incomplete universe scan in update mode" in err_msg
            assert "Insufficient History: 1" in err_msg
            assert insufficient_candidate in err_msg

    def test_provider_failure_cannot_be_masked_as_invalid_or_insufficient_history(self):
        """Provider failure is tracked strictly as failed_symbols and cannot be masked as invalid or insufficient history."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        failed_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == failed_candidate:
                raise RuntimeError("API network error")
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.value)
            assert "Failed: 1" in err_msg
            assert f"Failed symbols: ['{failed_candidate}']" in err_msg
            assert "Invalid symbols: []" in err_msg
            assert "Insufficient history symbols: []" in err_msg

    def test_vnindex_insufficient_history_fails_closed(self):
        """Required benchmark VNINDEX with insufficient history -> fails closed."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)
        short_df = make_valid_canonical_df(5)

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "VNINDEX":
                return short_df
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "VNINDEX" in str(ctx.value)

    def test_vn30_insufficient_history_fails_closed(self):
        """Required benchmark VN30 with insufficient history -> fails closed."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)
        short_df = make_valid_canonical_df(5)

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "VN30":
                return short_df
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "VN30" in str(ctx.value)

    def test_generated_artifacts_remain_unchanged_when_validation_fails(self):
        """Generated report files remain untouched when update validation fails due to insufficient history or failed symbols."""
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "ACB":
                return make_valid_canonical_df(5)
            return valid_df

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            market_file = generated_dir / "market.json"

            initial_recs = {"schema_version": "2.0", "recommendations": [{"symbol": "INITIAL"}]}
            initial_market = {"regime": "NEUTRAL"}

            recs_file.write_text(json.dumps(initial_recs), encoding="utf-8")
            market_file.write_text(json.dumps(initial_market), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_get_hist,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx:
                    generate_report_main()

                assert ctx.value.code == 1

            assert json.loads(recs_file.read_text(encoding="utf-8")) == initial_recs
            assert json.loads(market_file.read_text(encoding="utf-8")) == initial_market

    def test_vnindex_provider_failure_fails(self):
        """Required benchmark VNINDEX provider failure -> fails closed."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "VNINDEX":
                raise RuntimeError("VNINDEX connection timeout")
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "VNINDEX" in str(ctx.value)

    def test_vn30_provider_failure_fails(self):
        """Required benchmark VN30 provider failure -> fails closed."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "VN30":
                raise RuntimeError("VN30 connection timeout")
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "VN30" in str(ctx.value)


@pytest.mark.unit
class TestReportGenerationValidationAndArtifactPreservation:
    """Deterministic offline unit tests covering universe validation and artifact preservation."""

    def setup_method(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()
        self.sleep_p1 = patch("scripts.data.acquisition.time.sleep")
        self.sleep_p2 = patch("scripts.data_provider.time.sleep")
        self.sleep_p3 = patch("scripts.pipeline.stages.time.sleep")
        self.univ_p = patch(
            "scripts.pipeline.stages.UniverseProvider._get_candidates",
            return_value=SMALL_TEST_UNIVERSE,
        )
        self.sleep_p1.start()
        self.sleep_p2.start()
        self.sleep_p3.start()
        self.univ_p.start()

    def teardown_method(self):
        patch.stopall()
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    def test_complete_scan_generates_report(self):
        """Complete scan -> report generated and saved to generated/."""
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)

        def mock_get_hist(symbol=None, **kwargs):
            return valid_df

        mock_mon_res = MagicMock()
        mock_mon_res.overall_status = "PASS"
        mock_mon_res.to_dict.return_value = {"overall_status": "PASS"}

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_get_hist,
                ),
                patch("jsonschema.validate", return_value=None),
                patch(
                    "scripts.pipeline.stages.evaluate_production_monitoring",
                    return_value=mock_mon_res,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                generate_report_main()

            # Verify report files were created
            assert (generated_dir / "recommendations.json").exists()
            assert (generated_dir / "market.json").exists()
            assert (generated_dir / "monitoring.json").exists()

    def test_one_missing_symbol_preserves_artifacts(self):
        """One missing symbol -> validation fails, existing artifacts unchanged."""
        from scripts.generate_report import UniverseProvider
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates

        extra_candidates = list(candidates) + [
            {"symbol": "MISSING_SYM", "companyName": "Missing Corp", "sector": "Tech"}
        ]

        class DynamicCandidatesList(list):
            def __init__(self, full_list, missing_sym):
                super().__init__(full_list)
                self.missing_sym = missing_sym
                self._iter_count = 0

            def __iter__(self):
                self._iter_count += 1
                if self._iter_count == 1:
                    return super().__iter__()
                return iter([item for item in self if item["symbol"].upper() != self.missing_sym])

        dynamic_candidates = DynamicCandidatesList(extra_candidates, "MISSING_SYM")

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "MISSING_SYM":
                raise RuntimeError("Failed to fetch MISSING_SYM")
            return valid_df

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            initial_content = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            recs_file.write_text(json.dumps(initial_content), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.pipeline.stages.UniverseProvider._get_candidates",
                    return_value=dynamic_candidates,
                ),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_get_hist,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx:
                    generate_report_main()

                assert ctx.value.code == 1

            # File on disk remains untouched
            assert json.loads(recs_file.read_text(encoding="utf-8")) == initial_content

    def test_one_provider_failure_preserves_artifacts(self):
        """One provider failure -> validation fails, existing artifacts unchanged."""
        from scripts.generate_report import UniverseProvider
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        failed_symbol = candidates[0]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == failed_symbol:
                raise RuntimeError(f"[{failed_symbol}] Connection error")
            return valid_df

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            initial_content = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            recs_file.write_text(json.dumps(initial_content), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_get_hist,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx:
                    generate_report_main()

                assert ctx.value.code == 1

            assert json.loads(recs_file.read_text(encoding="utf-8")) == initial_content

    def test_one_insufficient_history_symbol_preserves_artifacts(self):
        """One symbol with insufficient historical data -> validation fails, existing artifacts unchanged."""
        from scripts.generate_report import UniverseProvider
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        short_df = make_valid_canonical_df(5)
        candidates = UniverseProvider().candidates
        insufficient_symbol = candidates[0]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == insufficient_symbol:
                return short_df
            return valid_df

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            initial_content = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            recs_file.write_text(json.dumps(initial_content), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_get_hist,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx:
                    generate_report_main()

                assert ctx.value.code == 1

            assert json.loads(recs_file.read_text(encoding="utf-8")) == initial_content

    def test_benchmark_failure_preserves_artifacts(self):
        """Benchmark fetch failure -> validation fails, existing artifacts unchanged."""
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)

        def make_mock_get_hist(bench_target):
            def mock_get_hist(symbol=None, **kwargs):
                sym = symbol or kwargs.get("sym")
                if sym == bench_target:
                    raise RuntimeError(f"[{bench_target}] Fetch failed")
                return valid_df

            return mock_get_hist

        for bench in ["VNINDEX", "VN30"]:
            mock_get_hist = make_mock_get_hist(bench)

            with tempfile.TemporaryDirectory() as tmpdir:
                generated_dir = Path(tmpdir) / "generated"
                generated_dir.mkdir(parents=True, exist_ok=True)
                recs_file = generated_dir / "recommendations.json"
                initial_content = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
                recs_file.write_text(json.dumps(initial_content), encoding="utf-8")

                with (
                    patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                    patch(
                        "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                        side_effect=mock_get_hist,
                    ),
                    patch("sys.argv", ["generate_report.py", "--update"]),
                ):
                    with pytest.raises(SystemExit) as ctx:
                        generate_report_main()

                    assert ctx.value.code == 1

                assert json.loads(recs_file.read_text(encoding="utf-8")) == initial_content

    def test_duplicate_symbol_still_incomplete_when_symbol_fails(self):
        """Candidate list with duplicates still fails if another symbol fails, existing artifacts unchanged."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        duplicate_candidates = list(candidates) + [candidates[0]]
        failing_symbol = candidates[1]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == failing_symbol:
                raise RuntimeError(f"[{failing_symbol}] Connection error")
            return valid_df

        with (
            patch(
                "scripts.pipeline.stages.UniverseProvider._get_candidates",
                return_value=duplicate_candidates,
            ),
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_get_hist,
            ),
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.value)
            assert "Failed: 1" in err_msg
            assert failing_symbol in err_msg

    def test_partial_in_memory_dataset_blocks_report_generation(self):
        """Incomplete scan results -> report generation blocked, disk files untouched."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        failing_symbol = candidates[-1]["symbol"].upper()

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == failing_symbol:
                raise RuntimeError("Fetch failed")
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "Failed: 1" in str(ctx.value)
            assert failing_symbol in str(ctx.value)

    def test_validation_failure_after_some_calculations_preserves_artifacts(self):
        """Completeness validation fails after partial pipeline calculations -> pre-existing artifacts untouched."""
        from scripts.generate_report import UniverseProvider
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        # Let first 1 symbol succeed (calculating bullish_count, MA20, etc.), but 2nd symbol fails
        failing_symbol = candidates[1]["symbol"].upper()

        processed_count = 0

        def mock_get_hist(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            nonlocal processed_count
            if sym == failing_symbol:
                raise RuntimeError("Failed mid-universe")
            if sym not in ("VNINDEX", "VN30"):
                processed_count += 1
            return valid_df

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            market_file = generated_dir / "market.json"

            initial_recs = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            initial_market = {"regime": "NEUTRAL"}

            recs_file.write_text(json.dumps(initial_recs), encoding="utf-8")
            market_file.write_text(json.dumps(initial_market), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_get_hist,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx:
                    generate_report_main()

                assert ctx.value.code == 1

            # Verify that partial processing occurred before failure
            assert processed_count > 0
            # Verify that artifacts on disk remain 100% identical and unchanged
            assert json.loads(recs_file.read_text(encoding="utf-8")) == initial_recs
            assert json.loads(market_file.read_text(encoding="utf-8")) == initial_market


@pytest.mark.unit
class TestPR155ProviderReliabilityAndPerformance:
    """Provider Reliability & Performance deterministic offline test suite."""

    def setup_method(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()
        VnstockDataProvider.reset_global_call_history()
        self.sleep_p1 = patch("scripts.data.acquisition.time.sleep")
        self.sleep_p2 = patch("scripts.data_provider.time.sleep")
        self.sleep_p3 = patch("scripts.pipeline.stages.time.sleep")
        self.univ_p = patch(
            "scripts.pipeline.stages.UniverseProvider._get_candidates",
            return_value=SMALL_TEST_UNIVERSE,
        )
        self.sleep_p1.start()
        self.sleep_p2.start()
        self.sleep_p3.start()
        self.univ_p.start()

    def teardown_method(self):
        patch.stopall()
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()
        VnstockDataProvider.reset_global_call_history()

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_successful_provider_call_timing(self, mock_quote, mock_sleep):
        """Successful provider call records timing structure."""
        valid_raw = make_valid_canonical_df(10)
        valid_raw_norm = valid_raw.copy()
        for col in ["open", "high", "low", "close"]:
            valid_raw_norm[col] /= 1000.0

        mock_inst = MagicMock()
        mock_inst.history.return_value = valid_raw_norm
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        df = provider.fetch_ohlcv("FPT")

        assert df is not None
        timing = provider.get_last_call_timing()
        assert timing is not None
        assert timing["provider"] == "vnstock"
        assert timing["source"] == "kbs"
        assert timing["operation"] == "history"
        assert timing["symbol"] == "FPT"
        assert timing["success"]
        assert timing["retry_count"] == 0
        assert timing["error"] is None
        assert timing["elapsed_seconds"] >= 0.0

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_provider_exception_timing_and_diagnostic(self, mock_quote, mock_sleep):
        """Provider exception records structured timing and diagnostic error information."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = ConnectionError("Network read timeout")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(RuntimeError):
            provider.fetch_ohlcv("VCB", max_retries=1)

        history = provider.get_call_history()
        assert len(history) > 0
        last_call = history[-1]
        assert last_call["provider"] == "vnstock"
        assert last_call["symbol"] == "VCB"
        assert not last_call["success"]
        assert "Network read timeout" in last_call["error"]

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_bounded_transient_retry(self, mock_quote, mock_sleep):
        """Transient network/server errors have bounded retries and do not loop infinitely."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = TimeoutError("Server timeout")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(RuntimeError):
            provider.fetch_ohlcv("SSI", max_retries=2)

        # max_retries=2 * 2 sources = exactly 4 attempts total
        assert mock_inst.history.call_count == 4
        history = provider.get_call_history()
        assert len(history) == 4

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_rate_limit_no_retry_behavior(self, mock_quote, mock_sleep):
        """Rate limit exception is NOT retried across attempts or sources and trips circuit breaker."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = RateLimitExceeded(
            "quote.history", "min", 20, 20, retry_after=30.0, tier="guest"
        )
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(ProviderRateLimitError):
            provider.fetch_ohlcv("HPG", max_retries=3)

        # Fails immediately on 1st call without retrying
        assert mock_inst.history.call_count == 1
        assert is_circuit_breaker_active()

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_circuit_breaker_behavior(self, mock_quote, mock_sleep):
        """Active circuit breaker blocks subsequent requests immediately without making API calls."""
        trip_circuit_breaker("Pre-tripped in test", cooldown_seconds=60)

        mock_inst = MagicMock()
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("TCB")

        assert mock_inst.history.call_count == 0
        assert "circuit breaker is active" in str(ctx.value)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_deterministic_source_fallback(self, mock_quote, mock_sleep):
        """Source fallback follows deterministic order ['kbs', 'msn']."""
        valid_raw = make_valid_canonical_df(10)
        for col in ["open", "high", "low", "close"]:
            valid_raw[col] /= 1000.0

        calls = []

        def side_effect(start=None, end=None):
            args = mock_quote.call_args
            source = args.kwargs.get("source") if args else None
            calls.append(source)
            if len(calls) == 1:
                raise ConnectionError("kbs failed")
            return valid_raw

        mock_inst = MagicMock()
        mock_inst.history.side_effect = side_effect
        mock_quote.side_effect = lambda symbol, source: mock_inst

        provider = VnstockDataProvider(is_available=True)
        df = provider.fetch_ohlcv("FPT", max_retries=1)

        assert df is not None
        history = provider.get_call_history()
        assert len(history) == 2
        assert history[0]["source"] == "kbs"
        assert not history[0]["success"]
        assert history[1]["source"] == "msn"
        assert history[1]["success"]

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_stale_source_followed_by_canonical_date_source(self, mock_quote, mock_sleep):
        """Stale source followed by canonical-date source prefers canonical-date source."""
        stale_df = make_valid_canonical_df(10, start_date="2026-09-01")  # max date 2026-09-10
        for col in ["open", "high", "low", "close"]:
            stale_df[col] /= 1000.0

        canonical_df = make_valid_canonical_df(15, start_date="2026-09-01")  # max date 2026-09-15
        for col in ["open", "high", "low", "close"]:
            canonical_df[col] /= 1000.0

        def quote_factory(symbol, source):
            m = MagicMock()
            if source == "kbs":
                m.history.return_value = stale_df
            else:
                m.history.return_value = canonical_df
            return m

        mock_quote.side_effect = quote_factory

        provider = VnstockDataProvider(is_available=True)
        res_df = provider.fetch_ohlcv("FPT", target_date="2026-09-15")

        assert res_df["time"].max() == "2026-09-15"

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_all_sources_stale_fail_closed(self, mock_quote, mock_sleep):
        """When all sources return stale data relative to target_date, update pipeline fails closed."""
        from scripts.generate_report import run_pipeline

        stale_df = make_valid_canonical_df(15, start_date="2026-08-01")  # max date 2026-08-15
        canonical_df = make_valid_canonical_df(25, start_date="2026-08-01")  # max date 2026-08-25

        def mock_get_hist(symbol, **kwargs):
            if symbol in ("VNINDEX", "VN30"):
                return canonical_df
            # Stocks are all stale (2026-08-15 vs VNINDEX 2026-08-25)
            return stale_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "Incomplete universe scan in update mode" in str(ctx.value)

    def test_canonical_date_invariant_remains_enforced(self):
        """In update mode, every processed stock must match VNINDEX data_as_of exactly."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25, start_date="2026-09-01")
        target_date = valid_df["time"].max()

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv"
        ) as mock_get_hist:
            mock_get_hist.return_value = valid_df
            recs_data, market_data, _ = run_pipeline(update_data=True)

            assert market_data["data_as_of"] == target_date
            assert recs_data["data_as_of"] == target_date
            for rec in recs_data["recommendations"]:
                assert rec["data_as_of"] == target_date

    def test_provider_diagnostics_use_existing_stage_category_taxonomy(self):
        """Universe audit diagnostics strictly use PIPELINE_STAGES and FAILURE_CATEGORIES."""
        from scripts.monitoring.models import (
            FAILURE_CATEGORIES,
            PIPELINE_STAGES,
            is_recoverable_category,
        )

        assert "BENCHMARK_FETCH" in PIPELINE_STAGES
        assert "STOCK_FETCH" in PIPELINE_STAGES
        assert "PROVIDER_FAILURE" in FAILURE_CATEGORIES
        assert "RATE_LIMIT" in FAILURE_CATEGORIES

        assert is_recoverable_category("PROVIDER_FAILURE")
        assert is_recoverable_category("RATE_LIMIT")
        assert not is_recoverable_category("EXPLICITLY_INVALID")

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_retry_count_is_deterministic(self, mock_quote, mock_sleep):
        """Retry count in timing logs is 0 for initial attempt and increments deterministically."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = [
            ConnectionError("Attempt 0 kbs failed"),
            TimeoutError("Attempt 0 msn failed"),
            ConnectionError("Attempt 1 kbs failed"),
            TimeoutError("Attempt 1 msn failed"),
        ]
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with pytest.raises(RuntimeError):
            provider.fetch_ohlcv("MBB", max_retries=2)

        history = provider.get_call_history()
        assert len(history) == 4

        # Attempt 0 calls
        assert history[0]["retry_count"] == 0
        assert history[0]["source"] == "kbs"
        assert history[1]["retry_count"] == 0
        assert history[1]["source"] == "msn"

        # Attempt 1 calls
        assert history[2]["retry_count"] == 1
        assert history[2]["source"] == "kbs"
        assert history[3]["retry_count"] == 1
        assert history[3]["source"] == "msn"

    def test_provider_failure_preserves_existing_artifact_behavior(self):
        """Provider failure during report update preserves existing generated JSON artifacts on disk."""
        from scripts.generate_report import main as generate_report_main

        with tempfile.TemporaryDirectory() as tmpdir:
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)

            recs_file = gen_dir / "recommendations.json"
            initial_data = {"schema_version": "2.0", "recommendations": [{"symbol": "PRESERVED"}]}
            recs_file.write_text(json.dumps(initial_data), encoding="utf-8")

            def mock_get_hist(symbol, **kwargs):
                if symbol == "ACB":
                    raise RuntimeError("ACB fetch failed")
                return make_valid_canonical_df(25)

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(gen_dir)),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_get_hist,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx:
                    generate_report_main()

                assert ctx.value.code == 1

            # Artifact on disk remains untouched
            assert json.loads(recs_file.read_text(encoding="utf-8")) == initial_data

    def test_no_duplicate_uncontrolled_provider_calls(self):
        """Universe scan deduplicates symbols and does not make duplicate/uncontrolled provider calls."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)
        calls_set = set()
        call_counts = {}

        def mock_get_hist(symbol, **kwargs):
            call_counts[symbol] = call_counts.get(symbol, 0) + 1
            calls_set.add(symbol)
            return valid_df

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_get_hist,
        ):
            run_pipeline(update_data=True)

        # Every unique symbol in universe (plus VNINDEX/VN30) is called exactly once
        for sym, cnt in call_counts.items():
            assert cnt == 1, f"Symbol {sym} was called {cnt} times instead of 1"

    def test_existing_freshness_tests_remain_green(self):
        """Existing freshness test suite passes cleanly."""
        from scripts.tests.test_data_date import (
            TestProductionDataFreshness,
            TestTemporalIntegrityValidation,
        )

        inst1 = TestProductionDataFreshness()
        for m in sorted(dir(inst1)):
            if m.startswith("test_"):
                if hasattr(inst1, "setup_method"):
                    inst1.setup_method()
                try:
                    getattr(inst1, m)()
                finally:
                    if hasattr(inst1, "teardown_method"):
                        inst1.teardown_method()

        inst2 = TestTemporalIntegrityValidation()
        for m in sorted(dir(inst2)):
            if m.startswith("test_"):
                if hasattr(inst2, "setup_method"):
                    inst2.setup_method()
                try:
                    getattr(inst2, m)()
                finally:
                    if hasattr(inst2, "teardown_method"):
                        inst2.teardown_method()
