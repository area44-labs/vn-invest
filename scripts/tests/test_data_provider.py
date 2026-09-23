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
    VnstockDataProvider,
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
    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_retries_transient_exception_and_exhausts(self, mock_quote, mock_sleep):
        """Transient exceptions (e.g. ConnectionError, TimeoutError) are caught and retried until max_retries."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = ConnectionError("Connection reset by peer")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with self.assertRaises(RuntimeError) as ctx:
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertIn("Failed to fetch valid canonical OHLCV", str(ctx.exception))
        # 2 attempts * 2 sources = 4 calls
        self.assertEqual(mock_inst.history.call_count, 4)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_succeeds_after_transient_retry(self, mock_quote, mock_sleep):
        """Transient failure on first call succeeds on subsequent retry."""
        valid_df = make_valid_canonical_df(10)
        # 100000 VND / 1000 -> 100.0 thousand VND for raw input simulation
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

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_fails_fast_on_non_retryable_exception(self, mock_quote, mock_sleep):
        """Deterministic/non-retryable exceptions (CanonicalOHLCVError, ValueError, TypeError, generic OSError) re-raise immediately."""
        # Test CanonicalOHLCVError
        mock_inst = MagicMock()
        mock_inst.history.side_effect = CanonicalOHLCVError("Invalid OHLC relationship")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with self.assertRaises(CanonicalOHLCVError):
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertEqual(mock_inst.history.call_count, 1)

        # Test generic OSError (non-network system/IO error)
        mock_inst.reset_mock()
        mock_inst.history.side_effect = OSError("Disk read error")
        with self.assertRaises(OSError):
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertEqual(mock_inst.history.call_count, 1)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_structured_http_status_codes(self, mock_quote, mock_sleep):
        """Structured HTTP 429/5xx status codes trigger retries, whereas HTTP 400 fails fast."""

        def make_http_err(status_code: int):
            err = Exception(f"HTTP {status_code} Error")
            res_mock = MagicMock()
            res_mock.status_code = status_code
            err.response = res_mock
            return err

        mock_inst = MagicMock()

        # HTTP 400 Bad Request -> Fail fast immediately (call_count == 1)
        mock_inst.history.side_effect = make_http_err(400)
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with self.assertRaises(Exception) as ctx_400:
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertIn("HTTP 400 Error", str(ctx_400.exception))
        self.assertEqual(mock_inst.history.call_count, 1)

        # HTTP 429 Too Many Requests -> Retried (2 attempts * 2 sources = 4 calls)
        mock_inst.reset_mock()
        mock_inst.history.side_effect = make_http_err(429)
        with self.assertRaises(RuntimeError) as ctx_429:
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertIn("Failed to fetch valid canonical OHLCV", str(ctx_429.exception))
        self.assertEqual(mock_inst.history.call_count, 4)

        # HTTP 500 Internal Server Error -> Retried
        mock_inst.reset_mock()
        mock_inst.history.side_effect = make_http_err(500)
        with self.assertRaises(RuntimeError) as ctx_500:
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertIn("Failed to fetch valid canonical OHLCV", str(ctx_500.exception))
        self.assertEqual(mock_inst.history.call_count, 4)

        # Test ValueError
        mock_inst.reset_mock()
        mock_inst.history.side_effect = ValueError("Invalid argument")
        with self.assertRaises(ValueError):
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertEqual(mock_inst.history.call_count, 1)

        # Test TypeError
        mock_inst.reset_mock()
        mock_inst.history.side_effect = TypeError("Expected string, got int")
        with self.assertRaises(TypeError):
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertEqual(mock_inst.history.call_count, 1)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_preserves_provider_fallback_order(self, mock_quote, mock_sleep):
        """Transient errors on primary source 'kbs' fall back to secondary source 'msn' before attempt 2."""
        valid_df = make_valid_canonical_df(10)
        raw_df = valid_df.copy()
        for col in ["open", "high", "low", "close"]:
            raw_df[col] = raw_df[col] / 1000.0

        calls = []

        def mock_quote_factory(symbol, source):
            m = MagicMock()
            if source == "kbs":
                m.history.side_effect = ConnectionError("KBS service unavailable")
            else:
                m.history.return_value = raw_df
            calls.append(source)
            return m

        mock_quote.side_effect = mock_quote_factory

        provider = VnstockDataProvider(is_available=True)
        df_res = provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertIsNotNone(df_res)
        # Attempt 1 source 1 ('kbs') -> ConnectionError, Attempt 1 source 2 ('msn') -> success
        self.assertEqual(calls, ["kbs", "msn"])

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_preserves_non_rate_limit_system_exit(self, mock_quote, mock_sleep):
        """Non-rate-limit SystemExit is NOT caught by fetch_ohlcv and propagates immediately without retrying."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = SystemExit("Generic system exit")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with self.assertRaises(SystemExit):
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertEqual(mock_inst.history.call_count, 1)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_catches_rate_limit_system_exit_and_waits(self, mock_quote, mock_sleep):
        """Rate limit SystemExit with standard string message is caught, parsed for wait time, and slept before retrying."""
        raw_data = [
            {
                "time": "2026-08-01",
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 102.0,
                "volume": 500000,
            }
        ]
        raw_df = pd.DataFrame(raw_data)

        mock_inst = MagicMock()
        mock_inst.history.side_effect = [
            SystemExit("Rate limit exceeded. Chờ 10 giây để tiếp tục"),
            raw_df,
        ]
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        res_df = provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertFalse(res_df.empty)
        # Should have slept 12s (10 + 2 padding)
        mock_sleep.assert_any_call(12)
        self.assertEqual(mock_inst.history.call_count, 2)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_catches_rate_limit_system_exit_in_code_attribute(
        self, mock_quote, mock_sleep
    ):
        """Rate limit SystemExit where message resides in exc.code is caught and retried successfully."""
        raw_data = [
            {
                "time": "2026-08-01",
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 102.0,
                "volume": 500000,
            }
        ]
        raw_df = pd.DataFrame(raw_data)

        rate_limit_exit = SystemExit()
        rate_limit_exit.code = "GIỚI HẠN API ĐÃ ĐẠT TỐI ĐA (Rate Limit Exceeded). Chờ 15 giây"

        mock_inst = MagicMock()
        mock_inst.history.side_effect = [
            rate_limit_exit,
            raw_df,
        ]
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        res_df = provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertFalse(res_df.empty)
        # Should have slept 17s (15 + 2 padding)
        mock_sleep.assert_any_call(17)
        self.assertEqual(mock_inst.history.call_count, 2)

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

        # Should fail immediately on first call without retrying
        self.assertEqual(mock_inst.history.call_count, 1)

    @patch("scripts.data_provider.time.sleep")
    @patch("scripts.data_provider.VnQuote")
    def test_fetch_ohlcv_preserves_generator_exit(self, mock_quote, mock_sleep):
        """GeneratorExit is NOT caught by fetch_ohlcv and propagates immediately."""
        mock_inst = MagicMock()
        mock_inst.history.side_effect = GeneratorExit("Generator closed")
        mock_quote.return_value = mock_inst

        provider = VnstockDataProvider(is_available=True)
        with self.assertRaises(GeneratorExit):
            provider.fetch_ohlcv("FPT", max_retries=2)

        self.assertEqual(mock_inst.history.call_count, 1)


if __name__ == "__main__":
    unittest.main()
