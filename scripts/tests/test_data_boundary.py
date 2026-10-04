"""Comprehensive unit and integration test suite for Issue #172 data boundary separation.

Tests acquisition, normalization, validation, and pipeline integration boundaries in isolation
and end-to-end, confirming offline execution, provider replacement via canonical fixtures,
and fail-closed behavior on malformed/temporal data.
"""

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from scripts.data.acquisition import (
    InvalidSymbolError,
    RawMarketDataPayload,
    acquire_raw_market_data,
)
from scripts.data.models import FORBIDDEN_PROVIDER_FIELDS, CanonicalMarketData
from scripts.data.normalization import normalize_raw_market_data
from scripts.data.providers.base import MarketDataProvider
from scripts.data.validation import validate_canonical_market_data
from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.pipeline.context import PipelineContext
from scripts.pipeline.stages import (
    DataAcquisitionStage,
    DataValidationStage,
    MarketAnalysisStage,
    MonitoringStage,
    PerformanceStage,
    RiskTradePlanStage,
    SignalRecommendationGenerationStage,
)
from scripts.pipeline.tracker import PerformanceTracker


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

    def test_production_pipeline_execution_with_fake_provider(self):
        """Production pipeline stages execute through provider -> acquisition -> normalization -> validation -> quantitative using FakeCustomMarketProvider."""
        ctx = PipelineContext()
        ctx.tracker = PerformanceTracker()
        ctx.market_data_provider = FakeCustomMarketProvider()
        ctx.update_data = False

        # Stage 1: Acquisition
        acq_stage = DataAcquisitionStage()
        acq_stage.execute(ctx)

        self.assertIsNotNone(ctx.raw_vnindex_payload)
        self.assertEqual(ctx.raw_vnindex_payload.provider_name, "custom_synthetic_provider")
        self.assertEqual(ctx.raw_vn30_payload.provider_name, "custom_synthetic_provider")
        self.assertIn("FPT", ctx.raw_stock_payloads)
        self.assertEqual(ctx.raw_stock_payloads["FPT"].provider_name, "custom_synthetic_provider")

        # Stage 2: Validation
        val_stage = DataValidationStage()
        val_stage.execute(ctx)

        self.assertIsNotNone(ctx.df_vnindex_clean)
        self.assertFalse(ctx.df_vnindex_clean.empty)
        self.assertEqual(ctx.vnindex_val.get("status"), "SUFFICIENT")

        # Stage 4 & 5: Quantitative
        mkt_stage = MarketAnalysisStage()
        mkt_stage.execute(ctx)
        self.assertIsNotNone(ctx.final_market_regime)

        sig_stage = SignalRecommendationGenerationStage()
        sig_stage.execute(ctx)
        self.assertTrue(len(ctx.scanned_recs) > 0)

        risk_stage = RiskTradePlanStage()
        risk_stage.execute(ctx)
        self.assertIn("recommendations", ctx.recommendations_payload)

        perf_stage = PerformanceStage()
        perf_stage.execute(ctx)

        mon_stage = MonitoringStage()
        mon_stage.execute(ctx)
        self.assertIsNotNone(ctx.monitoring_result)

    def test_structured_acquisition_error_propagation_no_string_parsing(self):
        """Structured acquisition exceptions propagate failure_type directly without error string parsing."""
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock_provider"
        mock_provider.fetch_ohlcv.side_effect = InvalidSymbolError("Symbol ABC not found")

        payload = acquire_raw_market_data("ABC", provider=mock_provider)
        self.assertEqual(payload.failure_type, "INVALID_SYMBOL")
        self.assertEqual(payload.source_tag, "INVALID_SYMBOL")

        cmd = normalize_raw_market_data(payload)
        self.assertEqual(cmd.source_tag, "INVALID_SYMBOL")

        v_data = validate_canonical_market_data(cmd)
        self.assertEqual(v_data.source_tag, "INVALID_SYMBOL")
        self.assertEqual(v_data.data_quality.status, "INSUFFICIENT")

    def test_validation_checks_unsorted_and_invalid_ohlc(self):
        """Validation boundary detects unsorted dates and invalid OHLC relationships fail-closed."""
        unsorted_df = pd.DataFrame(
            {
                "date": ["2025-01-03", "2025-01-02"],  # Unsorted dates
                "open": [100.0, 101.0],
                "high": [105.0, 106.0],
                "low": [99.0, 100.0],
                "close": [102.0, 103.0],
                "volume": [1000.0, 1100.0],
            }
        )
        cmd_unsorted = CanonicalMarketData.from_df("FPT", unsorted_df)
        v_unsorted = validate_canonical_market_data(cmd_unsorted)
        self.assertIn("unsorted_dates", v_unsorted.data_quality.issues)
        self.assertEqual(v_unsorted.source_tag, "EXPLICITLY_INVALID")

        invalid_ohlc_df = pd.DataFrame(
            {
                "date": ["2025-01-02"],
                "open": [100.0],
                "high": [105.0],
                "low": [110.0],  # Invalid: low > high
                "close": [102.0],
                "volume": [1000.0],
            }
        )
        cmd_invalid_ohlc = CanonicalMarketData.from_df("FPT", invalid_ohlc_df)
        v_invalid_ohlc = validate_canonical_market_data(cmd_invalid_ohlc)
        self.assertIn("invalid_ohlc_relationship", v_invalid_ohlc.data_quality.issues)
        self.assertEqual(v_invalid_ohlc.source_tag, "EXPLICITLY_INVALID")

    @patch("scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv")
    def test_production_acquisition_stage_uses_market_data_acquirer(self, mock_fetch_ohlcv):
        """Verify DataAcquisitionStage in production uses MarketDataAcquirer and provider boundary."""
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock_provider"
        mock_provider.fetch_ohlcv.return_value = pd.DataFrame(
            {
                "time": [f"2025-01-{i:02d}" for i in range(1, 25)],
                "open": [100.0] * 24,
                "high": [105.0] * 24,
                "low": [99.0] * 24,
                "close": [102.0] * 24,
                "volume": [1000.0] * 24,
            }
        )

        ctx = PipelineContext()
        ctx.tracker = PerformanceTracker()
        ctx.market_data_provider = mock_provider
        ctx.update_data = False

        acq_stage = DataAcquisitionStage()
        acq_stage.execute(ctx)

        self.assertTrue(mock_provider.fetch_ohlcv.called)

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
