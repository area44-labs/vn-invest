"""Unit tests for data provider boundary and canonical OHLCV validator.

Deterministic tests without network access covering all 13 canonical validator requirements
and provider boundary conversion/validation.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
from vnai.beam.quota import RateLimitExceeded

from scripts.data_provider import (
    CanonicalOHLCVError,
    ProviderRateLimitError,
    VnstockDataProvider,
    get_rate_limit_recovery_count,
    is_circuit_breaker_active,
    reset_circuit_breaker,
    reset_rate_limit_recovery_count,
    validate_canonical_ohlcv,
)
from scripts.lib.vietnam_market import get_historical_data


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


class TestCanonicalOHLCVValidator(unittest.TestCase):
    def test_1_valid_ohlcv_passes(self):
        """1. Valid canonical OHLCV data passes validation."""
        df = make_valid_canonical_df(25)
        self.assertTrue(validate_canonical_ohlcv(df))

    def test_2_empty_dataframe_fails(self):
        """2. Empty DataFrame or None fails validation."""
        with self.assertRaises(CanonicalOHLCVError) as ctx_none:
            validate_canonical_ohlcv(None)
        self.assertIn("Empty dataset", str(ctx_none.exception))

        with self.assertRaises(CanonicalOHLCVError) as ctx_empty:
            validate_canonical_ohlcv(pd.DataFrame())
        self.assertIn("Empty dataset", str(ctx_empty.exception))

    def test_3_missing_required_column_fails(self):
        """3. Missing required OHLCV column fails validation."""
        df = make_valid_canonical_df(20)
        df_no_close = df.drop(columns=["close"])
        with self.assertRaises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df_no_close)
        self.assertIn("Missing required columns", str(ctx.exception))

        df_no_date = df.drop(columns=["time"])
        with self.assertRaises(CanonicalOHLCVError) as ctx_date:
            validate_canonical_ohlcv(df_no_date)
        self.assertIn("Missing date column", str(ctx_date.exception))

    def test_4_duplicate_dates_fail(self):
        """4. Duplicate dates fail validation."""
        df = make_valid_canonical_df(20)
        df.loc[10, "time"] = df.loc[9, "time"]
        with self.assertRaises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        self.assertIn("Duplicate dates detected", str(ctx.exception))

    def test_5_unsorted_dates_fail(self):
        """5. Unsorted dates fail validation."""
        df = make_valid_canonical_df(20)
        # Swap date at index 5 and 6 so date order is non-monotonic
        tmp = df.loc[5, "time"]
        df.loc[5, "time"] = df.loc[6, "time"]
        df.loc[6, "time"] = tmp
        with self.assertRaises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        self.assertIn("Unsorted dates detected", str(ctx.exception))

    def test_6_nan_fails(self):
        """6. NaN values fail validation."""
        df = make_valid_canonical_df(20)
        df.loc[8, "close"] = np.nan
        with self.assertRaises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        self.assertIn("NaN values detected", str(ctx.exception))

    def test_7_infinite_value_fails(self):
        """7. Infinite values fail validation."""
        df = make_valid_canonical_df(20)
        df.loc[5, "close"] = np.inf
        with self.assertRaises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        self.assertIn("Infinite values detected", str(ctx.exception))

    def test_8_high_less_than_low_fails(self):
        """8. 'high < low' fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[4, "high"] = 40000.0
        df.loc[4, "low"] = 50000.0
        with self.assertRaises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        self.assertIn("Invalid OHLC relationship", str(ctx.exception))

    def test_9_open_greater_than_high_fails(self):
        """9. 'open > high' fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[3, "open"] = 60000.0
        df.loc[3, "high"] = 55000.0
        with self.assertRaises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        self.assertIn("Invalid OHLC relationship", str(ctx.exception))

    def test_10_open_less_than_low_fails(self):
        """10. 'open < low' fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[3, "open"] = 45000.0
        df.loc[3, "low"] = 48000.0
        with self.assertRaises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        self.assertIn("Invalid OHLC relationship", str(ctx.exception))

    def test_11_close_greater_than_high_fails(self):
        """11. 'close > high' fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[2, "close"] = 60000.0
        df.loc[2, "high"] = 55000.0
        with self.assertRaises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        self.assertIn("Invalid OHLC relationship", str(ctx.exception))

    def test_12_close_less_than_low_fails(self):
        """12. 'close < low' fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[2, "close"] = 40000.0
        df.loc[2, "low"] = 48000.0
        with self.assertRaises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        self.assertIn("Invalid OHLC relationship", str(ctx.exception))

    def test_13_negative_volume_fails(self):
        """13. Negative volume fails validation."""
        df = make_valid_canonical_df(20)
        df.loc[7, "volume"] = -100
        with self.assertRaises(CanonicalOHLCVError) as ctx:
            validate_canonical_ohlcv(df)
        self.assertIn("Negative volume detected", str(ctx.exception))


class TestVnstockProviderBoundary(unittest.TestCase):
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
        self.assertEqual(canonical_df.loc[0, "open"], 100000.0)
        self.assertEqual(canonical_df.loc[0, "close"], 102000.0)
        self.assertEqual(canonical_df.loc[0, "high"], 105000.0)
        self.assertEqual(canonical_df.loc[0, "low"], 95000.0)
        self.assertEqual(canonical_df.loc[0, "volume"], 500000)

        # Verify validation passed and DataFrame is canonical
        self.assertTrue(validate_canonical_ohlcv(canonical_df))


class TestDataProviderExceptionHandling(unittest.TestCase):
    def setUp(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    def tearDown(self):
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
        with self.assertRaises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("FPT", max_retries=3)

        self.assertEqual(mock_inst.history.call_count, 1)
        self.assertTrue(is_circuit_breaker_active())
        self.assertEqual(ctx.exception.cooldown_seconds, 32)
        self.assertEqual(ctx.exception.symbol, "FPT")

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
        with self.assertRaises(ProviderRateLimitError):
            provider.fetch_ohlcv("FPT", max_retries=3)

        self.assertEqual(mock_inst.history.call_count, 1)
        self.assertTrue(is_circuit_breaker_active())

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
        with self.assertRaises(ProviderRateLimitError):
            provider.fetch_ohlcv("FPT")

        self.assertEqual(mock_inst.history.call_count, 1)
        self.assertTrue(is_circuit_breaker_active())

        # Second request for HPG should fail immediately via circuit breaker without making any VnQuote calls
        mock_inst.reset_mock()
        with self.assertRaises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("HPG")

        self.assertEqual(mock_inst.history.call_count, 0)
        self.assertIn("circuit breaker is active", str(ctx.exception))

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
            with self.assertRaises(RuntimeError) as ctx:
                provider.fetch_ohlcv("FPT", max_retries=2)

            self.assertIn("Failed to fetch valid canonical OHLCV", str(ctx.exception))
            # 2 attempts * 2 sources = 4 calls total
            self.assertEqual(mock_inst.history.call_count, 4)
            self.assertFalse(is_circuit_breaker_active())

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
            with self.assertRaises(Exception) as ctx:
                provider.fetch_ohlcv("FPT", max_retries=3)

            self.assertIn(f"HTTP {status_code} Error", str(ctx.exception))
            # Fails immediately on 1st call without trying 2nd source or 2nd/3rd attempt
            self.assertEqual(mock_inst.history.call_count, 1)
            self.assertFalse(is_circuit_breaker_active())

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
        with self.assertRaises(requests.exceptions.RequestException):
            provider.fetch_ohlcv("FPT", max_retries=3)

        # Fails fast immediately on 1st call without retrying or trying 2nd source
        self.assertEqual(mock_inst.history.call_count, 1)

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
        with self.assertRaises(HTTP408Error):
            provider.fetch_ohlcv("FPT", max_retries=3)

        self.assertEqual(mock_inst.history.call_count, 1)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_parse_wait_seconds_formats(self, mock_quote, mock_sleep):
        """parse_wait_seconds handles 'wait 10 seconds', 'wait 10 sec', 'Chờ 10 giây', 40s/60s, retry_after attr, and fallback."""
        from scripts.data_provider import parse_wait_seconds

        self.assertEqual(parse_wait_seconds("Rate limit. wait 10 seconds"), 12)
        self.assertEqual(parse_wait_seconds("Rate limit. wait 10 sec"), 12)
        self.assertEqual(parse_wait_seconds("Rate limit. Chờ 10 giây"), 12)
        self.assertEqual(parse_wait_seconds("Rate limit. Chờ 40 giây"), 42)
        self.assertEqual(parse_wait_seconds("Rate limit. Chờ 60 giây"), 62)
        self.assertEqual(parse_wait_seconds("Rate limit. 40s"), 42)
        self.assertEqual(parse_wait_seconds("Rate limit. 60s"), 62)
        self.assertEqual(parse_wait_seconds("Rate limit. 10 sec"), 12)
        self.assertEqual(parse_wait_seconds("Rate limit. No numbers here"), 15)

        # Test with real RateLimitExceeded instance having retry_after attribute
        exc_40 = RateLimitExceeded("quote.history", "min", 20, 20, retry_after=40.0, tier="guest")
        self.assertEqual(parse_wait_seconds(str(exc_40), exc=exc_40), 42)

        exc_60 = RateLimitExceeded("quote.history", "min", 60, 60, retry_after=60.0, tier="free")
        self.assertEqual(parse_wait_seconds(str(exc_60), exc=exc_60), 62)

        # Test fallback edge cases: invalid/zero/None retry_after attributes
        exc_invalid_retry = RateLimitExceeded(
            "quote.history", "min", 20, 20, retry_after=None, tier="guest"
        )
        exc_invalid_retry.retry_after = "invalid"
        self.assertEqual(
            parse_wait_seconds("Rate limit reached. Wait 40 seconds", exc=exc_invalid_retry), 42
        )

        exc_zero_retry = RateLimitExceeded(
            "quote.history", "min", 20, 20, retry_after=None, tier="guest"
        )
        exc_zero_retry.retry_after = 0
        self.assertEqual(
            parse_wait_seconds("Rate limit reached. Wait 60 seconds", exc=exc_zero_retry), 62
        )

        exc_none_retry = RateLimitExceeded(
            "quote.history", "min", 20, 20, retry_after=None, tier="guest"
        )
        self.assertEqual(
            parse_wait_seconds("Rate limit reached. Chờ 50 giây", exc=exc_none_retry), 52
        )

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
        with self.assertRaises(RuntimeError) as ctx:
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertIn("Failed to fetch valid canonical OHLCV", str(ctx.exception))
        # It was treated as a transient ConnectionError, so it retried (2 attempts * 2 sources = 4 calls)
        self.assertEqual(mock_inst.history.call_count, 4)
        self.assertFalse(is_circuit_breaker_active())

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
        with self.assertRaises(RuntimeError) as ctx:
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertIn("Failed to fetch valid canonical OHLCV", str(ctx.exception))
        self.assertEqual(mock_inst.history.call_count, 4)
        self.assertFalse(is_circuit_breaker_active())

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

        self.assertIsNotNone(df_res)
        self.assertEqual(len(df_res), 10)
        self.assertEqual(mock_inst.history.call_count, 2)
        self.assertFalse(is_circuit_breaker_active())

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_fails_fast_on_non_retryable_data_error(self, mock_quote, mock_sleep):
        """Deterministic non-retryable exceptions (CanonicalOHLCVError, ValueError, TypeError, OSError) re-raise immediately."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = CanonicalOHLCVError("Invalid OHLC relationship")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with self.assertRaises(CanonicalOHLCVError):
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertEqual(mock_inst.history.call_count, 1)

        mock_inst.reset_mock()
        mock_inst.history.side_effect = OSError("Disk read error")
        with self.assertRaises(OSError):
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertEqual(mock_inst.history.call_count, 1)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_preserves_non_rate_limit_system_exit(self, mock_quote, mock_sleep):
        """Non-rate-limit SystemExit is NOT caught and propagates immediately without retrying."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = SystemExit("Generic system exit")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with self.assertRaises(SystemExit):
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertEqual(mock_inst.history.call_count, 1)
        self.assertFalse(is_circuit_breaker_active())

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
        with self.assertRaises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertEqual(mock_inst.history.call_count, 1)
        self.assertTrue(is_circuit_breaker_active())
        self.assertEqual(ctx.exception.cooldown_seconds, 12)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_preserves_keyboard_interrupt(self, mock_quote, mock_sleep):
        """KeyboardInterrupt is NOT caught by fetch_ohlcv and propagates immediately."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = KeyboardInterrupt("Ctrl+C pressed")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with self.assertRaises(KeyboardInterrupt):
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertEqual(mock_inst.history.call_count, 1)


class TestVnstockRealRateLimitRegression(unittest.TestCase):
    """Focused regression tests using real Vnstock / Vnai rate-limit exception shapes."""

    def setUp(self):
        reset_circuit_breaker()

    def tearDown(self):
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

        with self.assertRaises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("FPT", max_retries=3)

        # 1. No retries occur (call_count == 1)
        self.assertEqual(mock_inst.history.call_count, 1)

        # 2. Transformed to ProviderRateLimitError
        self.assertIsInstance(ctx.exception, ProviderRateLimitError)
        self.assertEqual(ctx.exception.symbol, "FPT")

        # 3. Parsed cooldown is preserved (40 + 2 = 42 seconds)
        self.assertEqual(ctx.exception.cooldown_seconds, 42)

        # 4. Circuit breaker is activated
        self.assertTrue(is_circuit_breaker_active())

        # 5. Subsequent provider requests are blocked fast without making network calls
        mock_inst.reset_mock()
        with self.assertRaises(ProviderRateLimitError) as ctx2:
            provider.fetch_ohlcv("VCB")

        self.assertEqual(mock_inst.history.call_count, 0)
        self.assertIn("circuit breaker is active", str(ctx2.exception))

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

        with self.assertRaises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("HPG", max_retries=3)

        self.assertEqual(mock_inst.history.call_count, 1)
        self.assertEqual(ctx.exception.cooldown_seconds, 62)
        self.assertTrue(is_circuit_breaker_active())

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
                with self.assertRaises(SystemExit) as ctx:
                    generate_report_main()

                # Pipeline exits with status code 1 for provider rate limits
                self.assertEqual(ctx.exception.code, 1)

            # Generated output file was NOT modified or overwritten
            saved_content = json.loads(recs_file.read_text(encoding="utf-8"))
            self.assertEqual(saved_content, initial_content)

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
                patch("scripts.generate_report.jsonschema.validate", return_value=None),
                patch(
                    "scripts.generate_report.evaluate_production_monitoring",
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
                with self.assertRaises(SystemExit) as ctx2:
                    generate_report_main()

                self.assertEqual(ctx2.exception.code, 1)

            # Path 3: Unexpected error converts to SystemExit(1)
            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.generate_report.run_pipeline",
                    side_effect=RuntimeError("Unexpected pipeline exception"),
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with self.assertRaises(SystemExit) as ctx3:
                    generate_report_main()

                self.assertEqual(ctx3.exception.code, 1)


class TestRateLimitRecoveryAndPipelineReliability(unittest.TestCase):
    """Focused tests for rate-limit recovery, universe scan continuity, and fail-closed report generation."""

    def setUp(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    def tearDown(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    @patch("scripts.lib.vietnam_market.time.sleep")
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

        def side_effect(symbol, start_date=None, end_date=None, max_retries=2):
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
        self.assertEqual(recs_data["summary"]["total_scanned"], len(candidates))
        self.assertEqual(len(recs_data["recommendations"]), len(candidates))
        self.assertIn("market", recs_data)

        # HPG was called twice (initial rate limit + successful recovery retry)
        self.assertEqual(hpg_calls, 2)
        # Rate limit recovery occurred and circuit breaker is clear
        self.assertEqual(get_rate_limit_recovery_count(), 1)
        self.assertFalse(is_circuit_breaker_active())
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

        def mock_get_historical_data(
            sym,
            start_date=None,
            end_date=None,
            max_retries=2,
            use_cache_only=False,
            allow_synthetic=False,
            throttle_delay=0.0,
        ):
            if sym == failing_sym:
                return (
                    pd.DataFrame(),
                    "PROVIDER_FAILURE",
                    [f"[{sym}] Failed to fetch data"],
                )
            return valid_df, "REAL_DATA", []

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
                    "scripts.generate_report.get_historical_data",
                    side_effect=mock_get_historical_data,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    generate_report_main()

                # Pipeline exits with non-zero exit code 1
                self.assertEqual(ctx.exception.code, 1)

            # Neither recommendations.json nor market.json was modified or overwritten
            self.assertEqual(json.loads(recs_file.read_text(encoding="utf-8")), initial_recs)
            self.assertEqual(json.loads(market_file.read_text(encoding="utf-8")), initial_market)

    def test_run_pipeline_invalid_vn30_fails_without_generating_report(self):
        """Regression test verifying that when VN30 benchmark data is invalid/empty,

        run_pipeline(update_data=True) fails closed with RuntimeError and includes VN30 in invalid_symbols.
        """
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)

        def mock_get_historical_data(
            sym,
            start_date=None,
            end_date=None,
            max_retries=2,
            use_cache_only=False,
            allow_synthetic=False,
            throttle_delay=0.0,
        ):
            if sym == "VN30":
                return (
                    pd.DataFrame(),
                    "PROVIDER_FAILURE",
                    ["[VN30] Failed to fetch data"],
                )
            return valid_df, "REAL_DATA", []

        with patch(
            "scripts.generate_report.get_historical_data",
            side_effect=mock_get_historical_data,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("VN30", str(ctx.exception))

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

        with self.assertRaises(ProviderRateLimitError) as ctx:
            # max_rate_limit_retries = 2
            get_historical_data("FPT", max_rate_limit_retries=2)

        # Fails after exhausting retries (attempts 0, 1, 2)
        self.assertEqual(ctx.exception.symbol, "FPT")
        self.assertEqual(get_rate_limit_recovery_count(), 2)


class TestUniverseCompletenessValidation(unittest.TestCase):
    """Offline unit tests verifying PR #136 complete universe processing and fail-closed validation."""

    def setUp(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    def tearDown(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    def test_1_complete_universe_proceeds(self):
        """1. Complete universe -> report generation proceeds successfully."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)

        def mock_get_hist(sym, **kwargs):
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            pipeline_res = run_pipeline(update_data=True)
            recs_data, market_data, _ = pipeline_res
            self.assertIn("recommendations", recs_data)
            self.assertIn("market", market_data)

    def test_2_one_expected_symbol_missing_fails(self):
        """2. One expected symbol missing -> fails closed with RuntimeError and preserves generated files."""
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

        def mock_get_hist(sym, **kwargs):
            return valid_df, "REAL_DATA", []

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
                    "scripts.generate_report.UniverseProvider._get_candidates",
                    return_value=dynamic_candidates,
                ),
                patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    run_pipeline(update_data=True)

                self.assertIn("Missing: 1", str(ctx.exception))
                self.assertIn("MISSING_SYM", str(ctx.exception))

            # Reset dynamic_candidates iter_count for main() test
            dynamic_candidates._iter_count = 0
            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.generate_report.UniverseProvider._get_candidates",
                    return_value=dynamic_candidates,
                ),
                patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with self.assertRaises(SystemExit) as ctx_exit:
                    generate_report_main()

                self.assertEqual(ctx_exit.exception.code, 1)

            # Output file was NOT modified
            self.assertEqual(json.loads(recs_file.read_text(encoding="utf-8")), initial_recs)

    def test_3_provider_failure_for_one_symbol_fails(self):
        """3. Provider failure for one symbol -> fails closed with RuntimeError and preserves files."""
        from scripts.generate_report import UniverseProvider, run_pipeline
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        failed_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == failed_candidate:
                return pd.DataFrame(), "PROVIDER_FAILURE", [f"[{sym}] Provider connection error"]
            return valid_df, "REAL_DATA", []

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            initial_recs = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            recs_file.write_text(json.dumps(initial_recs), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    run_pipeline(update_data=True)

                self.assertIn("Incomplete universe scan in update mode", str(ctx.exception))
                self.assertIn("Failed: 1", str(ctx.exception))
                self.assertIn(failed_candidate, str(ctx.exception))

                with patch("sys.argv", ["generate_report.py", "--update"]):
                    with self.assertRaises(SystemExit) as ctx_exit:
                        generate_report_main()
                    self.assertEqual(ctx_exit.exception.code, 1)

            # Artifact preserved
            self.assertEqual(json.loads(recs_file.read_text(encoding="utf-8")), initial_recs)

    def test_4_one_explicitly_invalid_symbol_allowed(self):
        """4. One explicitly invalid symbol (with all other symbols valid) -> allowed."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        invalid_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == invalid_candidate:
                # Return empty DataFrame with tag INVALID_SYMBOL (genuinely invalid symbol)
                return (
                    pd.DataFrame(),
                    "INVALID_SYMBOL",
                    [f"[{sym}] Invalid symbol"],
                )
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            pipeline_res = run_pipeline(update_data=True)
            recs_data, _market_data, _ = pipeline_res
            self.assertIn("recommendations", recs_data)
            # The invalid symbol is present in recommendations with action AVOID
            invalid_recs = [
                r for r in recs_data["recommendations"] if r["symbol"] == invalid_candidate
            ]
            self.assertEqual(len(invalid_recs), 1)
            self.assertEqual(invalid_recs[0]["action"], "AVOID")

    def test_get_historical_data_status_tag_distinctions(self):
        """Verify get_historical_data tags status strictly by issue type."""
        valid_df = make_valid_canonical_df(25)
        short_df = make_valid_canonical_df(5)
        empty_df = pd.DataFrame()
        missing_col_df = valid_df.drop(columns=["close"])
        missing_date_df = valid_df.drop(columns=["time"])

        with patch("scripts.lib.vietnam_market.VnstockDataProvider") as mock_prov_cls:
            mock_prov = mock_prov_cls.return_value

            # 1. Valid data -> REAL_DATA
            mock_prov.fetch_ohlcv.return_value = valid_df
            _df, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "REAL_DATA")

            # 2. Fewer than required valid rows -> INSUFFICIENT_HISTORICAL_DATA
            mock_prov.fetch_ohlcv.return_value = short_df
            _df, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "INSUFFICIENT_HISTORICAL_DATA")

            # 3. Empty DataFrame -> PROVIDER_FAILURE
            mock_prov.fetch_ohlcv.return_value = empty_df
            _df, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "PROVIDER_FAILURE")

            # 4. Missing required OHLCV column -> PROVIDER_FAILURE
            mock_prov.fetch_ohlcv.return_value = missing_col_df
            _df, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "PROVIDER_FAILURE")

            # 5. Missing date column -> PROVIDER_FAILURE
            mock_prov.fetch_ohlcv.return_value = missing_date_df
            _df, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "PROVIDER_FAILURE")

            # 6. Provider exception -> PROVIDER_FAILURE
            mock_prov.fetch_ohlcv.side_effect = RuntimeError("API connection timeout")
            _df, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "PROVIDER_FAILURE")

    def test_valid_symbol_with_insufficient_history_fails(self):
        """Valid symbol with insufficient history -> tagged insufficient_history and fails update mode."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        insufficient_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == insufficient_candidate:
                # Valid symbol but insufficient historical rows (< 20 rows)
                short_df = make_valid_canonical_df(5)
                return short_df, "INSUFFICIENT_HISTORICAL_DATA", ["insufficient_history"]
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.exception)
            self.assertIn("Insufficient History: 1", err_msg)
            self.assertIn(insufficient_candidate, err_msg)

    def test_5_duplicate_symbol_does_not_inflate_processed_count(self):
        """5. Duplicate symbols in candidate list -> deduplicated, does not inflate processed count."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates

        # Create candidate list with duplicate FPT
        duplicate_candidates = list(candidates) + [candidates[0]]

        def mock_get_hist(sym, **kwargs):
            return valid_df, "REAL_DATA", []

        with (
            patch(
                "scripts.generate_report.UniverseProvider._get_candidates",
                return_value=duplicate_candidates,
            ),
            patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
        ):
            pipeline_res = run_pipeline(update_data=True)
            recs_data, _, _ = pipeline_res
            self.assertIn("recommendations", recs_data)

        # Verify that if another symbol fails, duplicate FPT does NOT compensate for the failed symbol
        failed_sym = candidates[1]["symbol"].upper()

        def mock_get_hist_with_failure(sym, **kwargs):
            if sym == failed_sym:
                return pd.DataFrame(), "PROVIDER_FAILURE", ["Provider failed"]
            return valid_df, "REAL_DATA", []

        with (
            patch(
                "scripts.generate_report.UniverseProvider._get_candidates",
                return_value=duplicate_candidates,
            ),
            patch(
                "scripts.generate_report.get_historical_data",
                side_effect=mock_get_hist_with_failure,
            ),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("Failed: 1", str(ctx.exception))
            self.assertIn(failed_sym, str(ctx.exception))

    def test_6_empty_provider_result_fails_unless_explicitly_classified_invalid(self):
        """6. Empty provider result without explicit invalid classification -> treated as failed_symbols and fails closed."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        empty_candidate = candidates[1]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == empty_candidate:
                # Return empty DataFrame with tag PROVIDER_FAILURE (unclassified empty / provider error)
                return pd.DataFrame(), "PROVIDER_FAILURE", [f"[{sym}] Empty response from provider"]
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("Failed: 1", str(ctx.exception))
            self.assertIn(empty_candidate, str(ctx.exception))

    def test_7_partial_scan_fails(self):
        """7. Partial scan (loop terminates early or misses expected symbols) -> fails closed."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        unprocessed_candidate = candidates[-1]["symbol"].upper()

        # Simulate exception raised for the last candidate so it's not processed successfully
        def mock_get_hist(sym, **kwargs):
            if sym == unprocessed_candidate:
                raise RuntimeError(f"Processing error on {sym}")
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("Failed: 1", str(ctx.exception))
            self.assertIn(unprocessed_candidate, str(ctx.exception))

    def test_8_rate_limit_exception_propagates_as_existing_behavior(self):
        """8. Rate-limit exception -> propagates ProviderRateLimitError directly without converting to failed_symbols."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        rate_limit_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == rate_limit_candidate:
                raise ProviderRateLimitError("Quota exceeded", cooldown_seconds=30, symbol=sym)
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(ProviderRateLimitError) as ctx:
                run_pipeline(update_data=True)

            self.assertEqual(ctx.exception.symbol, rate_limit_candidate)

    def test_9_mixed_successful_invalid_failed_symbols_fails(self):
        """9. Mixed successful + invalid + insufficient history + failed symbols -> fails closed."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        invalid_candidate = candidates[0]["symbol"].upper()
        failed_candidate = candidates[1]["symbol"].upper()
        insufficient_candidate = candidates[2]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == invalid_candidate:
                return pd.DataFrame(), "INVALID_SYMBOL", ["Invalid symbol"]
            if sym == failed_candidate:
                return pd.DataFrame(), "PROVIDER_FAILURE", ["Timeout error"]
            if sym == insufficient_candidate:
                return (
                    make_valid_canonical_df(5),
                    "INSUFFICIENT_HISTORICAL_DATA",
                    ["insufficient_history"],
                )
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.exception)
            self.assertIn("Invalid: 1", err_msg)
            self.assertIn("Failed: 1", err_msg)
            self.assertIn("Insufficient History: 1", err_msg)
            self.assertIn(failed_candidate, err_msg)
            self.assertIn(insufficient_candidate, err_msg)

    def test_10_completeness_validation_reports_useful_diagnostics(self):
        """10. Completeness validation error message reports all required diagnostic metrics."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        failed_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == failed_candidate:
                return pd.DataFrame(), "PROVIDER_FAILURE", ["Failed fetch"]
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.exception)
            self.assertIn("Incomplete universe scan in update mode", err_msg)
            self.assertIn("Expected:", err_msg)
            self.assertIn("Processed:", err_msg)
            self.assertIn("Invalid:", err_msg)
            self.assertIn("Failed:", err_msg)
            self.assertIn("Missing:", err_msg)
            self.assertIn("Failed symbols:", err_msg)
            self.assertIn("Missing symbols:", err_msg)

    def test_insufficient_history_symbol_cannot_make_scan_appear_complete(self):
        """Insufficient-history candidate cannot satisfy processed_symbols ∪ invalid_symbols."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        insufficient_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == insufficient_candidate:
                return (
                    make_valid_canonical_df(5),
                    "INSUFFICIENT_HISTORICAL_DATA",
                    ["insufficient_history"],
                )
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.exception)
            self.assertIn("Incomplete universe scan in update mode", err_msg)
            self.assertIn("Insufficient History: 1", err_msg)
            self.assertIn(insufficient_candidate, err_msg)

    def test_provider_failure_cannot_be_masked_as_invalid_or_insufficient_history(self):
        """Provider failure is tracked strictly as failed_symbols and cannot be masked as invalid or insufficient history."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        failed_candidate = candidates[0]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == failed_candidate:
                return pd.DataFrame(), "PROVIDER_FAILURE", ["API network error"]
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.exception)
            self.assertIn("Failed: 1", err_msg)
            self.assertIn(f"Failed symbols: ['{failed_candidate}']", err_msg)
            self.assertIn("Invalid symbols: []", err_msg)
            self.assertIn("Insufficient history symbols: []", err_msg)

    def test_vnindex_insufficient_history_fails_closed(self):
        """Required benchmark VNINDEX with insufficient history -> fails closed."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)
        short_df = make_valid_canonical_df(5)

        def mock_get_hist(sym, **kwargs):
            if sym == "VNINDEX":
                return short_df, "INSUFFICIENT_HISTORICAL_DATA", ["insufficient_history"]
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("VNINDEX", str(ctx.exception))

    def test_vn30_insufficient_history_fails_closed(self):
        """Required benchmark VN30 with insufficient history -> fails closed."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)
        short_df = make_valid_canonical_df(5)

        def mock_get_hist(sym, **kwargs):
            if sym == "VN30":
                return short_df, "INSUFFICIENT_HISTORICAL_DATA", ["insufficient_history"]
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("VN30", str(ctx.exception))

    def test_generated_artifacts_remain_unchanged_when_validation_fails(self):
        """Generated report files remain untouched when update validation fails due to insufficient history or failed symbols."""
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)

        def mock_get_hist(sym, **kwargs):
            if sym == "ACB":
                return (
                    make_valid_canonical_df(5),
                    "INSUFFICIENT_HISTORICAL_DATA",
                    ["insufficient_history"],
                )
            return valid_df, "REAL_DATA", []

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
                patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    generate_report_main()

                self.assertEqual(ctx.exception.code, 1)

            self.assertEqual(json.loads(recs_file.read_text(encoding="utf-8")), initial_recs)
            self.assertEqual(json.loads(market_file.read_text(encoding="utf-8")), initial_market)

    def test_vnindex_provider_failure_fails(self):
        """Required benchmark VNINDEX provider failure -> fails closed."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)

        def mock_get_hist(sym, **kwargs):
            if sym == "VNINDEX":
                return pd.DataFrame(), "PROVIDER_FAILURE", ["VNINDEX connection timeout"]
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("VNINDEX", str(ctx.exception))

    def test_vn30_provider_failure_fails(self):
        """Required benchmark VN30 provider failure -> fails closed."""
        from scripts.generate_report import run_pipeline

        valid_df = make_valid_canonical_df(25)

        def mock_get_hist(sym, **kwargs):
            if sym == "VN30":
                return pd.DataFrame(), "PROVIDER_FAILURE", ["VN30 connection timeout"]
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("VN30", str(ctx.exception))


class TestReportGenerationValidationAndArtifactPreservation(unittest.TestCase):
    """Deterministic offline unit tests covering universe validation and artifact preservation."""

    def setUp(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    def tearDown(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()

    def test_scenario_1_complete_scan_generates_report(self):
        """Scenario 1: Complete scan -> report generated and saved to generated/."""
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)

        def mock_get_hist(sym, **kwargs):
            return valid_df, "REAL_DATA", []

        mock_mon_res = MagicMock()
        mock_mon_res.overall_status = "PASS"
        mock_mon_res.to_dict.return_value = {"overall_status": "PASS"}

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
                patch("scripts.generate_report.jsonschema.validate", return_value=None),
                patch(
                    "scripts.generate_report.evaluate_production_monitoring",
                    return_value=mock_mon_res,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                generate_report_main()

            # Verify report files were created
            self.assertTrue((generated_dir / "recommendations.json").exists())
            self.assertTrue((generated_dir / "market.json").exists())
            self.assertTrue((generated_dir / "monitoring.json").exists())

    def test_scenario_2_one_missing_symbol_preserves_artifacts(self):
        """Scenario 2: One missing symbol -> validation fails, existing artifacts unchanged."""
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

        def mock_get_hist(sym, **kwargs):
            return valid_df, "REAL_DATA", []

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            initial_content = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            recs_file.write_text(json.dumps(initial_content), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.generate_report.UniverseProvider._get_candidates",
                    return_value=dynamic_candidates,
                ),
                patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    generate_report_main()

                self.assertEqual(ctx.exception.code, 1)

            # File on disk remains untouched
            self.assertEqual(json.loads(recs_file.read_text(encoding="utf-8")), initial_content)

    def test_scenario_3_one_provider_failure_preserves_artifacts(self):
        """Scenario 3: One provider failure -> validation fails, existing artifacts unchanged."""
        from scripts.generate_report import UniverseProvider
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        failed_symbol = candidates[0]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == failed_symbol:
                return pd.DataFrame(), "PROVIDER_FAILURE", [f"[{failed_symbol}] Connection error"]
            return valid_df, "REAL_DATA", []

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            initial_content = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            recs_file.write_text(json.dumps(initial_content), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    generate_report_main()

                self.assertEqual(ctx.exception.code, 1)

            self.assertEqual(json.loads(recs_file.read_text(encoding="utf-8")), initial_content)

    def test_scenario_4_one_insufficient_history_symbol_preserves_artifacts(self):
        """Scenario 4: One insufficient-history symbol -> validation fails, existing artifacts unchanged."""
        from scripts.generate_report import UniverseProvider
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        short_df = make_valid_canonical_df(5)
        candidates = UniverseProvider().candidates
        insufficient_symbol = candidates[0]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == insufficient_symbol:
                return short_df, "INSUFFICIENT_HISTORICAL_DATA", ["insufficient_history"]
            return valid_df, "REAL_DATA", []

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            initial_content = {"schema_version": "2.0", "recommendations": [{"symbol": "OLD"}]}
            recs_file.write_text(json.dumps(initial_content), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    generate_report_main()

                self.assertEqual(ctx.exception.code, 1)

            self.assertEqual(json.loads(recs_file.read_text(encoding="utf-8")), initial_content)

    def test_scenario_5_benchmark_failure_preserves_artifacts(self):
        """Scenario 5: Benchmark failure (VNINDEX or VN30) -> validation fails, existing artifacts unchanged."""
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)

        def make_mock_get_hist(bench_target):
            def mock_get_hist(sym, **kwargs):
                if sym == bench_target:
                    return pd.DataFrame(), "PROVIDER_FAILURE", [f"[{bench_target}] Fetch failed"]
                return valid_df, "REAL_DATA", []

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
                    patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
                    patch("sys.argv", ["generate_report.py", "--update"]),
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        generate_report_main()

                    self.assertEqual(ctx.exception.code, 1)

                self.assertEqual(json.loads(recs_file.read_text(encoding="utf-8")), initial_content)

    def test_scenario_6_duplicate_symbol_still_incomplete_when_symbol_fails(self):
        """Scenario 6: Duplicate symbol -> deduplicated, does not inflate completeness count to bypass failure."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        duplicate_candidates = list(candidates) + [candidates[0]]
        failing_symbol = candidates[1]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == failing_symbol:
                return pd.DataFrame(), "PROVIDER_FAILURE", [f"[{failing_symbol}] Connection error"]
            return valid_df, "REAL_DATA", []

        with (
            patch(
                "scripts.generate_report.UniverseProvider._get_candidates",
                return_value=duplicate_candidates,
            ),
            patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            err_msg = str(ctx.exception)
            self.assertIn("Failed: 1", err_msg)
            self.assertIn(failing_symbol, err_msg)

    def test_scenario_7_partial_in_memory_dataset_blocks_report_generation(self):
        """Scenario 7: Partial in-memory dataset -> report generation blocked before payload generation."""
        from scripts.generate_report import UniverseProvider, run_pipeline

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        failing_symbol = candidates[-1]["symbol"].upper()

        def mock_get_hist(sym, **kwargs):
            if sym == failing_symbol:
                return pd.DataFrame(), "PROVIDER_FAILURE", ["Fetch failed"]
            return valid_df, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("Failed: 1", str(ctx.exception))
            self.assertIn(failing_symbol, str(ctx.exception))

    def test_scenario_8_validation_failure_after_some_calculations_preserves_artifacts(self):
        """Scenario 8: Validation failure after partial calculations -> previous artifacts remain unchanged."""
        from scripts.generate_report import UniverseProvider
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        candidates = UniverseProvider().candidates
        # Let first 5 symbols succeed (calculating bullish_count, MA20, etc.), but 6th symbol fails
        failing_symbol = candidates[5]["symbol"].upper()

        processed_count = 0

        def mock_get_hist(sym, **kwargs):
            nonlocal processed_count
            if sym == failing_symbol:
                return pd.DataFrame(), "PROVIDER_FAILURE", ["Failed mid-universe"]
            if sym not in ("VNINDEX", "VN30"):
                processed_count += 1
            return valid_df, "REAL_DATA", []

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
                patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    generate_report_main()

                self.assertEqual(ctx.exception.code, 1)

            # Verify that partial processing occurred before failure
            self.assertGreater(processed_count, 0)
            # Verify that artifacts on disk remain 100% identical and unchanged
            self.assertEqual(json.loads(recs_file.read_text(encoding="utf-8")), initial_recs)
            self.assertEqual(json.loads(market_file.read_text(encoding="utf-8")), initial_market)


if __name__ == "__main__":
    unittest.main()
