"""Comprehensive unit and integration test suite for Issue #172 data boundary separation.

Tests acquisition, normalization, validation, and pipeline integration boundaries in isolation
and end-to-end, confirming offline execution, provider replacement via canonical fixtures,
and fail-closed behavior on malformed/temporal data.
"""

import unittest
from unittest.mock import MagicMock

import pandas as pd

from scripts.data.acquisition import RawMarketDataPayload, acquire_raw_market_data
from scripts.data.models import FORBIDDEN_PROVIDER_FIELDS, CanonicalMarketData
from scripts.data.normalization import normalize_raw_market_data
from scripts.data.validation import validate_canonical_market_data
from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime


class TestDataBoundaryIsolationAndIntegration(unittest.TestCase):
    """Test data boundary contracts, malformed field handling, and provider replacement."""

    def test_provider_response_malformed_missing_fields(self):
        """Malformed provider DataFrame missing required columns handles fail-closed."""
        malformed_df = pd.DataFrame(
            {
                "time": ["2025-01-02"],
                "close": [100.0],
                # Missing 'open', 'high', 'low', 'volume'
            }
        )
        payload = RawMarketDataPayload(symbol="FPT", raw_df=malformed_df, source_tag="REAL_DATA")
        cmd = normalize_raw_market_data(payload)
        validated = validate_canonical_market_data(cmd)

        self.assertEqual(validated.source_tag, "PROVIDER_FAILURE")
        self.assertEqual(validated.data_quality.status, "INSUFFICIENT")
        self.assertIn("missing_required_columns", validated.data_quality.issues)

    def test_temporal_mismatch_fails_closed(self):
        """Record date in future relative to reference_date fails closed."""
        future_df = pd.DataFrame(
            {
                "date": ["2025-02-01"],
                "open": [100.0],
                "high": [105.0],
                "low": [99.0],
                "close": [102.0],
                "volume": [1000.0],
            }
        )
        cmd = CanonicalMarketData.from_df("FPT", future_df, data_as_of="2025-02-01")
        validated = validate_canonical_market_data(cmd, reference_date="2025-01-15")

        self.assertEqual(validated.source_tag, "EXPLICITLY_INVALID")
        self.assertEqual(validated.data_quality.status, "INSUFFICIENT")
        self.assertTrue(any("future_dated" in iss for iss in validated.data_quality.issues))

    def test_duplicate_and_incorrect_data_as_of(self):
        """Duplicate dates and malformed data_as_of format are caught fail-closed."""
        dup_df = pd.DataFrame(
            {
                "date": ["2025-01-02", "2025-01-02"],  # Duplicate date
                "open": [100.0, 101.0],
                "high": [105.0, 106.0],
                "low": [99.0, 100.0],
                "close": [102.0, 103.0],
                "volume": [1000.0, 1100.0],
            }
        )
        cmd = CanonicalMarketData.from_df("FPT", dup_df)
        validated = validate_canonical_market_data(cmd)

        self.assertIn("duplicate_dates", validated.data_quality.issues)
        self.assertEqual(validated.source_tag, "EXPLICITLY_INVALID")

        # Invalid date format raises ValueError
        with self.assertRaises(ValueError):
            CanonicalMarketData(symbol="FPT", data_as_of="2025/01/02")

    def test_provider_replacement_with_canonical_fixture_without_vnstock(self):
        """Quantitative engine consumes canonical fixture without importing or calling vnstock."""
        # Construct synthetic canonical fixture DataFrames
        dates = [f"2025-01-{i:02d}" for i in range(1, 25)]
        df_vnindex = pd.DataFrame(
            {
                "date": dates,
                "open": [1200.0 + i for i in range(24)],
                "high": [1210.0 + i for i in range(24)],
                "low": [1195.0 + i for i in range(24)],
                "close": [1205.0 + i for i in range(24)],
                "volume": [500000000.0] * 24,
            }
        )
        df_stock = pd.DataFrame(
            {
                "date": dates,
                "open": [100000.0 + i * 100 for i in range(24)],
                "high": [102000.0 + i * 100 for i in range(24)],
                "low": [99000.0 + i * 100 for i in range(24)],
                "close": [101000.0 + i * 100 for i in range(24)],
                "volume": [1000000.0] * 24,
            }
        )

        cmd_vnindex = CanonicalMarketData.from_df("VNINDEX", df_vnindex, data_as_of="2025-01-24")
        cmd_stock = CanonicalMarketData.from_df("FPT", df_stock, data_as_of="2025-01-24")

        # Confirm no provider fields present in canonical objects
        for forbidden in FORBIDDEN_PROVIDER_FIELDS:
            self.assertFalse(hasattr(cmd_vnindex, forbidden))
            self.assertFalse(hasattr(cmd_stock, forbidden))

        # Detect regime using canonical fixture DataFrame
        regime_info = detect_market_regime(
            df_vnindex=cmd_vnindex.to_df(),
            df_vn30=None,
            breadth_ratio=0.8,
        )
        self.assertIsNotNone(regime_info)
        self.assertIn(
            regime_info.get("regime"), ["STRONG_BULL", "BULL", "NEUTRAL", "BEAR", "PANIC"]
        )

        # Generate recommendation using canonical fixture DataFrame
        rec = generate_recommendation(
            symbol=cmd_stock.symbol,
            company_name="FPT Corporation",
            sector="Technology",
            exchange="HOSE",
            df_stock=cmd_stock.to_df(),
            market_regime_info=regime_info,
            df_vnindex=cmd_vnindex.to_df(),
            data_as_of=cmd_stock.data_as_of,
            data_source="CANONICAL_FIXTURE",
        )
        self.assertEqual(rec["symbol"], "FPT")
        self.assertEqual(rec["data_as_of"], "2025-01-24")
        self.assertIn("action", rec)
        self.assertIn("signal_score", rec)
        self.assertIsNotNone(rec.signal_score)

    def test_full_boundary_pipeline_flow(self):
        """Test full data boundary flow: acquire -> normalize -> validate."""
        mock_raw_df = pd.DataFrame(
            {
                "time": [f"2025-01-{i:02d}" for i in range(1, 25)],
                "open": [100.0] * 24,
                "high": [105.0] * 24,
                "low": [99.0] * 24,
                "close": [102.0] * 24,
                "volume": [1000.0] * 24,
            }
        )
        mock_provider = MagicMock()
        mock_provider.fetch_ohlcv.return_value = mock_raw_df

        # Step 1: Acquisition
        raw_payload = acquire_raw_market_data("FPT", provider=mock_provider)
        self.assertEqual(raw_payload.symbol, "FPT")

        # Step 2: Normalization
        canonical_data = normalize_raw_market_data(raw_payload)
        self.assertEqual(canonical_data.symbol, "FPT")
        self.assertEqual(canonical_data.data_as_of, "2025-01-24")
        self.assertEqual(canonical_data.records[0].open, 100000.0)  # normalized price

        # Step 3: Validation
        validated_data = validate_canonical_market_data(canonical_data, reference_date="2025-01-24")
        self.assertEqual(validated_data.data_quality.status, "SUFFICIENT")
        self.assertEqual(validated_data.source_tag, "REAL_DATA")
        self.assertEqual(len(validated_data.records), 24)


if __name__ == "__main__":
    unittest.main()
