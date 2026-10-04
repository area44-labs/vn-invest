"""Unit tests for MarketDataProvider boundary interfaces."""

import unittest
from unittest.mock import MagicMock

import pandas as pd

from scripts.data.providers.base import MarketDataProvider
from scripts.data.providers.vnstock import VnstockMarketProvider


class DummyFakeProvider(MarketDataProvider):
    """Fake provider for testing provider boundary polymorphism."""

    @property
    def provider_name(self) -> str:
        return "fake_provider"

    def fetch_ohlcv(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        max_retries: int = 2,
        target_date: str | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": ["2025-01-02"],
                "open": [100.0],
                "high": [105.0],
                "low": [99.0],
                "close": [102.0],
                "volume": [1000.0],
            }
        )


class TestDataProviderBoundary(unittest.TestCase):
    """Test MarketDataProvider contract and VnstockMarketProvider adapter."""

    def test_dummy_fake_provider(self):
        provider = DummyFakeProvider()
        self.assertEqual(provider.provider_name, "fake_provider")
        df = provider.fetch_ohlcv("FPT")
        self.assertFalse(df.empty)
        self.assertEqual(df["close"].iloc[0], 102.0)

    def test_vnstock_market_provider_adapter(self):
        mock_vnstock = MagicMock()
        mock_vnstock.fetch_ohlcv.return_value = pd.DataFrame({"close": [100.0]})

        adapter = VnstockMarketProvider(provider_instance=mock_vnstock)
        self.assertEqual(adapter.provider_name, "vnstock")

        df = adapter.fetch_ohlcv("VCB")
        self.assertEqual(df["close"].iloc[0], 100.0)
        mock_vnstock.fetch_ohlcv.assert_called_once_with(
            symbol="VCB",
            start_date=None,
            end_date=None,
            max_retries=2,
            target_date=None,
        )


if __name__ == "__main__":
    unittest.main()
