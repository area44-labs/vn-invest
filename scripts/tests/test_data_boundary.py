"""Comprehensive unit and integration test suite for Issue #172 data boundary separation.

Tests acquisition, normalization, validation, and pipeline integration boundaries in isolation
and end-to-end, confirming offline execution, provider replacement via canonical fixtures,
and fail-closed behavior on malformed/temporal data.
"""

import unittest

import pandas as pd

from scripts.data.acquisition import RawMarketDataPayload, acquire_raw_market_data
from scripts.data.models import FORBIDDEN_PROVIDER_FIELDS, CanonicalMarketData
from scripts.data.normalization import normalize_raw_market_data
from scripts.data.providers.base import MarketDataProvider
from scripts.data.validation import validate_canonical_market_data
from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime


class FakeCustomMarketProvider(MarketDataProvider):
    """Custom fake provider implementation for provider replacement testing."""

    @property
    def provider_name(self) -> str:
        return "custom_synthetic_provider"

    def fetch_ohlcv(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        max_retries: int = 2,
        target_date: str | None = None,
    ) -> pd.DataFrame:
        dates = [f"2025-01-{i:02d}" for i in range(1, 25)]
        if symbol.upper() in ("VNINDEX", "VN30"):
            return pd.DataFrame(
                {
                    "time": dates,
                    "open": [1200.0 + i for i in range(24)],
                    "high": [1210.0 + i for i in range(24)],
                    "low": [1195.0 + i for i in range(24)],
                    "close": [1205.0 + i for i in range(24)],
                    "volume": [500000000.0] * 24,
                }
            )
        return pd.DataFrame(
            {
                "time": dates,
                "open": [100.0 + i for i in range(24)],
                "high": [102.0 + i for i in range(24)],
                "low": [99.0 + i for i in range(24)],
                "close": [101.0 + i for i in range(24)],
                "volume": [1000000.0] * 24,
            }
        )


class TestDataBoundaryIsolationAndIntegration(unittest.TestCase):
    """Test data boundary contracts, malformed field handling, and provider replacement."""

    def test_provider_replacement_via_interface(self):
        """Provider replacement: replacing provider with FakeCustomMarketProvider without modifying acquisition or quantitative layer."""
        fake_provider = FakeCustomMarketProvider()

        # Step 1: Acquire raw data via custom fake provider
        payload_vnindex = acquire_raw_market_data("VNINDEX", provider=fake_provider)
        payload_stock = acquire_raw_market_data("FPT", provider=fake_provider)

        self.assertEqual(payload_vnindex.provider_name, "custom_synthetic_provider")
        self.assertEqual(payload_stock.provider_name, "custom_synthetic_provider")

        # Step 2: Normalization
        cmd_vnindex = normalize_raw_market_data(payload_vnindex)
        cmd_stock = normalize_raw_market_data(payload_stock)

        # Step 3: Validation
        v_vnindex = validate_canonical_market_data(cmd_vnindex)
        v_stock = validate_canonical_market_data(cmd_stock)

        self.assertEqual(v_vnindex.data_quality.status, "SUFFICIENT")
        self.assertEqual(v_stock.data_quality.status, "SUFFICIENT")

        # Step 4: Quantitative analysis strictly consumes canonical validated DataFrames
        regime_info = detect_market_regime(
            df_vnindex=v_vnindex.to_df(),
            df_vn30=None,
            breadth_ratio=0.8,
        )
        rec = generate_recommendation(
            symbol=v_stock.symbol,
            company_name="FPT Corp",
            sector="Technology",
            exchange="HOSE",
            df_stock=v_stock.to_df(),
            market_regime_info=regime_info,
            df_vnindex=v_vnindex.to_df(),
            data_as_of=v_stock.data_as_of,
            data_source=v_stock.source_tag,
        )
        self.assertEqual(rec.symbol, "FPT")
        self.assertIsNotNone(rec.signal_score)

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

    def test_no_provider_fields_in_canonical_models(self):
        """Confirm CanonicalMarketData strips provider-specific attributes."""
        cmd = CanonicalMarketData(
            symbol="VCB",
            data_as_of="2025-01-02",
        )
        for forbidden in FORBIDDEN_PROVIDER_FIELDS:
            self.assertFalse(hasattr(cmd, forbidden))


if __name__ == "__main__":
    unittest.main()
