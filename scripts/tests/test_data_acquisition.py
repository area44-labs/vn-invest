"""Unit tests for acquisition boundary in scripts/data/acquisition.py."""

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from scripts.data.acquisition import (
    MarketDataAcquirer,
    RawMarketDataPayload,
    acquire_raw_market_data,
)
from scripts.data_provider import ProviderRateLimitError


class TestMarketDataAcquisitionBoundary(unittest.TestCase):
    """Test MarketDataAcquirer and acquisition boundary contracts."""

    def test_successful_raw_data_acquisition(self):
        mock_df = pd.DataFrame(
            {
                "time": ["2025-01-02", "2025-01-03"],
                "open": [100.0, 102.0],
                "high": [105.0, 107.0],
                "low": [99.0, 101.0],
                "close": [102.0, 106.0],
                "volume": [1000.0, 1500.0],
            }
        )
        mock_provider = MagicMock()
        mock_provider.fetch_ohlcv.return_value = mock_df

        payload = acquire_raw_market_data("FPT", provider=mock_provider)

        self.assertIsInstance(payload, RawMarketDataPayload)
        self.assertEqual(payload.symbol, "FPT")
        self.assertEqual(payload.source_tag, "REAL_DATA")
        self.assertEqual(payload.provider_name, "vnstock")
        self.assertIsNone(payload.error)
        self.assertFalse(payload.raw_df.empty)

    def test_acquisition_failure_tagging(self):
        mock_provider = MagicMock()
        mock_provider.fetch_ohlcv.side_effect = RuntimeError("Provider offline")

        payload = acquire_raw_market_data("FPT", provider=mock_provider)

        self.assertEqual(payload.symbol, "FPT")
        self.assertEqual(payload.source_tag, "PROVIDER_FAILURE")
        self.assertTrue(payload.raw_df.empty)
        self.assertIn("Provider offline", payload.error)

    def test_acquisition_explicitly_invalid_tagging(self):
        mock_provider = MagicMock()
        mock_provider.fetch_ohlcv.side_effect = ValueError("OHLC relationship invalid")

        payload = acquire_raw_market_data("FPT", provider=mock_provider)

        self.assertEqual(payload.symbol, "FPT")
        self.assertEqual(payload.source_tag, "EXPLICITLY_INVALID")
        self.assertTrue(payload.raw_df.empty)

    @patch("scripts.data.acquisition.can_recover_rate_limit", return_value=False)
    def test_rate_limit_exceeded_raises(self, _mock_can_rec):
        mock_provider = MagicMock()
        mock_provider.fetch_ohlcv.side_effect = ProviderRateLimitError(
            "Rate limit exceeded", cooldown_seconds=5
        )

        acquirer = MarketDataAcquirer(provider=mock_provider)
        with self.assertRaises(ProviderRateLimitError):
            acquirer.acquire("FPT", max_rate_limit_retries=0)


if __name__ == "__main__":
    unittest.main()
