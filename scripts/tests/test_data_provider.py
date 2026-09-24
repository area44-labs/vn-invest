"""Unit tests for data provider boundary and canonical OHLCV validator.

Deterministic tests without network access covering all 13 canonical validator requirements
and provider boundary conversion/validation.
"""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from scripts.data_provider import (
    CanonicalOHLCVError,
    ProviderRateLimitError,
    VnstockDataProvider,
    is_circuit_breaker_active,
    reset_circuit_breaker,
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

    def tearDown(self):
        reset_circuit_breaker()

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
        """parse_wait_seconds handles 'wait 10 seconds', 'wait 10 sec', 'Chờ 10 giây', and fallback."""
        from scripts.data_provider import parse_wait_seconds

        self.assertEqual(parse_wait_seconds("Rate limit. wait 10 seconds"), 12)
        self.assertEqual(parse_wait_seconds("Rate limit. wait 10 sec"), 12)
        self.assertEqual(parse_wait_seconds("Rate limit. Chờ 10 giây"), 12)
        self.assertEqual(parse_wait_seconds("Rate limit. 10s"), 12)
        self.assertEqual(parse_wait_seconds("Rate limit. 10 sec"), 12)
        self.assertEqual(parse_wait_seconds("Rate limit. No numbers here"), 15)

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
        # Realistic Vnai RateLimitExceeded exception message format
        vnai_msg = (
            "\n"
            "============================================================\n"
            "⚠️  GIỚI HẠN API ĐÃ ĐẠT TỐI ĐA (Rate Limit Exceeded)\n"
            "============================================================\n\n"
            "📌 Bạn đã đạt giới hạn tối đa số lượt yêu cầu API trong 1 phút (minute).\n"
            "   (You have reached the maximum API request limit for this period)\n\n"
            "📊 Chi tiết (Details):\n"
            "   • Gói hiện tại: Khách (Guest)\n"
            "   • Giới hạn: 20 requests/phút\n"
            "   • Đã sử dụng: 20/20\n"
            "   • Chờ 40 giây để tiếp tục (Wait to retry)\n\n"
            "💡 Giải pháp (Solutions):\n"
            "   1️⃣ Chờ 40 giây rồi thử lại\n"
        )

        class RateLimitExceeded(Exception):
            pass

        exc = RateLimitExceeded(vnai_msg)

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
        """Regression test verifying 60s English rate limit message."""
        msg = "Rate limit exceeded. Wait 60 seconds."

        class RateLimitExceeded(Exception):
            pass

        mock_inst = MagicMock()
        mock_inst.history.side_effect = RateLimitExceeded(msg)
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)

        with self.assertRaises(ProviderRateLimitError) as ctx:
            provider.fetch_ohlcv("HPG", max_retries=3)

        self.assertEqual(mock_inst.history.call_count, 1)
        self.assertEqual(ctx.exception.cooldown_seconds, 62)
        self.assertTrue(is_circuit_breaker_active())

    def test_pipeline_halts_and_preserves_generated_files_on_rate_limit(self):
        """Regression test verifying generate_report.py halts cleanly (exit 1) and preserves generated files."""
        import json
        import tempfile
        from pathlib import Path
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

                # Pipeline exits with status code 1
                self.assertEqual(ctx.exception.code, 1)

            # Generated output file was NOT modified or overwritten
            saved_content = json.loads(recs_file.read_text(encoding="utf-8"))
            self.assertEqual(saved_content, initial_content)


if __name__ == "__main__":
    unittest.main()
