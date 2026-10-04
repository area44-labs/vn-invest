"""Unit tests for normalization boundary in scripts/data/normalization.py."""

import unittest

import pandas as pd

from scripts.data.acquisition import RawMarketDataPayload
from scripts.data.normalization import normalize_raw_market_data


class TestMarketDataNormalizationBoundary(unittest.TestCase):
    """Test MarketDataNormalizer and canonical normalization rules."""

    def test_stock_price_unit_normalization(self):
        # Raw provider output for stock symbol (prices in thousand_VND/share)
        raw_df = pd.DataFrame(
            {
                "time": ["2025-01-02", "2025-01-03"],
                "open": [100.0, 102.0],
                "high": [105.0, 107.0],
                "low": [99.0, 101.0],
                "close": [102.0, 106.0],
                "volume": [1000.0, 1500.0],
                "ticker": ["FPT", "FPT"],  # provider-specific field
                "board": ["HOSE", "HOSE"],  # provider-specific field
            }
        )
        payload = RawMarketDataPayload(symbol="FPT", raw_df=raw_df, source_tag="REAL_DATA")

        cmd = normalize_raw_market_data(payload, source_price_unit="thousand_VND/share")

        self.assertEqual(cmd.symbol, "FPT")
        self.assertEqual(cmd.data_as_of, "2025-01-03")
        self.assertEqual(len(cmd.records), 2)
        # Verify 1000x scaling (100.0 thousand -> 100,000.0 VND)
        self.assertEqual(cmd.records[0].open, 100000.0)
        self.assertEqual(cmd.records[1].close, 106000.0)

        # Verify provider-specific fields are stripped in to_dict()
        cmd_dict = cmd.to_dict()
        self.assertNotIn("ticker", cmd_dict)
        self.assertNotIn("board", cmd_dict)

    def test_index_symbol_no_price_scaling(self):
        # Raw provider output for VNINDEX (prices in index points)
        raw_df = pd.DataFrame(
            {
                "time": ["2025-01-02"],
                "open": [1250.5],
                "high": [1260.0],
                "low": [1245.0],
                "close": [1258.2],
                "volume": [500000000.0],
            }
        )
        payload = RawMarketDataPayload(symbol="VNINDEX", raw_df=raw_df, source_tag="REAL_DATA")

        cmd = normalize_raw_market_data(payload, source_price_unit="thousand_VND/share")

        self.assertEqual(cmd.symbol, "VNINDEX")
        self.assertEqual(cmd.data_as_of, "2025-01-02")
        # Index points must NOT be scaled
        self.assertEqual(cmd.records[0].open, 1250.5)

    def test_explicit_data_as_of_override(self):
        raw_df = pd.DataFrame(
            {
                "date": ["2025-01-02"],
                "open": [100000.0],
                "high": [105000.0],
                "low": [99000.0],
                "close": [102000.0],
                "volume": [1000.0],
            }
        )
        payload = RawMarketDataPayload(symbol="VCB", raw_df=raw_df, source_tag="REAL_DATA")

        cmd = normalize_raw_market_data(
            payload, explicit_data_as_of="2025-01-02", source_price_unit="VND/share"
        )

        self.assertEqual(cmd.data_as_of, "2025-01-02")
        self.assertEqual(cmd.records[0].open, 100000.0)


if __name__ == "__main__":
    unittest.main()
