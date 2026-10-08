"""Regression tests for production update-data pipeline requirements."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.data_provider import ProviderRateLimitError
from scripts.domain.universe import Universe
from scripts.pipeline.context import PipelineContext
from scripts.pipeline.runner import run_pipeline
from scripts.pipeline.stages import (
    ArtifactPublishingStage,
)
from scripts.pipeline.tracker import PerformanceTracker


def make_valid_ohlcv_df(
    start_date: str = "2026-09-01", periods: int = 30, base_price: float = 50.0
) -> pd.DataFrame:
    """Helper creating clean valid OHLCV DataFrame for testing."""
    dates = pd.date_range(start_date, periods=periods, freq="D")
    return pd.DataFrame(
        {
            "time": dates.strftime("%Y-%m-%d"),
            "open": [base_price] * periods,
            "high": [base_price + 2.0] * periods,
            "low": [base_price - 2.0] * periods,
            "close": [base_price + 1.0] * periods,
            "volume": [10000.0] * periods,
        }
    )


@pytest.mark.integration
class TestUpdateDataPipelineRequirements:
    """Regression test suite covering complete production update-data execution path requirements."""

    def test_incomplete_symbol_universe_raises_runtime_error_in_update_mode(self):
        """Requirement 1 & 3: Incomplete symbol universe in update mode raises RuntimeError and halts before report publishing."""
        valid_df = make_valid_ohlcv_df("2026-09-01", periods=30)

        def mock_fetch(symbol, start_date, end_date, **kwargs):
            if symbol == "VIC":
                return pd.DataFrame()  # Empty dataset simulating acquisition failure
            return valid_df

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_fetch,
            ),
            patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls,
        ):
            mock_provider = MagicMock()
            mock_provider.get_universe.return_value = Universe.from_candidates(
                [
                    {
                        "symbol": "FPT",
                        "companyName": "FPT Corp",
                        "sector": "Tech",
                        "exchange": "HOSE",
                    },
                    {
                        "symbol": "VIC",
                        "companyName": "Vingroup",
                        "sector": "Real Estate",
                        "exchange": "HOSE",
                    },
                ],
                benchmarks=("VNINDEX", "VN30"),
            )
            mock_provider_cls.return_value = mock_provider

            with pytest.raises(RuntimeError) as exc_info:
                run_pipeline(update_data=True, generated_dir=tmpdir, publish_artifacts=True)

            err_msg = str(exc_info.value)
            assert "Incomplete universe scan in update mode" in err_msg
            assert "Failed symbols: ['VIC']" in err_msg or "'VIC'" in err_msg
            assert hasattr(exc_info.value, "universe_audit")

            # Verify no artifacts were published to generated_dir
            assert not os.path.exists(os.path.join(tmpdir, "recommendations.json"))
            assert not os.path.exists(os.path.join(tmpdir, "market.json"))

    def test_benchmark_acquisition_failure_halts_pipeline_in_update_mode(self):
        """Requirement 7: Benchmark acquisition failure (VNINDEX or VN30) halts update pipeline and prevents report publishing."""
        valid_df = make_valid_ohlcv_df("2026-09-01", periods=30)

        def mock_fetch(symbol, start_date, end_date, **kwargs):
            if symbol == "VNINDEX":
                raise RuntimeError("Connection reset by peer fetching VNINDEX")
            return valid_df

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_fetch,
            ),
            patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls,
        ):
            mock_provider = MagicMock()
            mock_provider.get_universe.return_value = Universe.from_candidates(
                [
                    {
                        "symbol": "FPT",
                        "companyName": "FPT Corp",
                        "sector": "Tech",
                        "exchange": "HOSE",
                    }
                ],
                benchmarks=("VNINDEX", "VN30"),
            )
            mock_provider_cls.return_value = mock_provider

            with pytest.raises(RuntimeError) as exc_info:
                run_pipeline(update_data=True, generated_dir=tmpdir, publish_artifacts=True)

            assert "Incomplete universe scan in update mode" in str(exc_info.value)
            assert "BENCHMARK_FETCH" in str(exc_info.value) or "VNINDEX" in str(exc_info.value)

            # Confirm no artifacts were created
            assert not os.path.exists(os.path.join(tmpdir, "recommendations.json"))

    def test_mixed_trading_dates_temporal_integrity_violation(self):
        """Requirement 4, 5, 7: Stock data date greater than VNINDEX data_as_of triggers temporal violation and halts pipeline."""
        vnindex_df = make_valid_ohlcv_df("2026-09-01", periods=20)  # max date: 2026-09-20
        future_stock_df = make_valid_ohlcv_df("2026-09-05", periods=20)  # max date: 2026-09-24

        def mock_fetch(symbol, start_date, end_date, **kwargs):
            if symbol in ("VNINDEX", "VN30"):
                return vnindex_df
            if symbol == "FPT":
                return future_stock_df
            return vnindex_df

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_fetch,
            ),
            patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls,
        ):
            mock_provider = MagicMock()
            mock_provider.get_universe.return_value = Universe.from_candidates(
                [
                    {
                        "symbol": "FPT",
                        "companyName": "FPT Corp",
                        "sector": "Tech",
                        "exchange": "HOSE",
                    }
                ],
                benchmarks=("VNINDEX", "VN30"),
            )
            mock_provider_cls.return_value = mock_provider

            with pytest.raises(RuntimeError) as exc_info:
                run_pipeline(update_data=True, generated_dir=tmpdir, publish_artifacts=True)

            assert "Temporal issues" in str(exc_info.value) or "Incomplete universe scan" in str(
                exc_info.value
            )

    def test_stale_latest_price_in_update_mode(self):
        """Requirement 5: Stale stock data date in update_data=True mode triggers strict temporal match failure and halts pipeline."""
        vnindex_df = make_valid_ohlcv_df("2026-09-01", periods=20)  # max date: 2026-09-20
        stale_stock_df = make_valid_ohlcv_df("2026-08-15", periods=20)  # max date: 2026-09-03

        def mock_fetch(symbol, start_date, end_date, **kwargs):
            if symbol in ("VNINDEX", "VN30"):
                return vnindex_df
            if symbol == "FPT":
                return stale_stock_df
            return vnindex_df

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_fetch,
            ),
            patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls,
        ):
            mock_provider = MagicMock()
            mock_provider.get_universe.return_value = Universe.from_candidates(
                [
                    {
                        "symbol": "FPT",
                        "companyName": "FPT Corp",
                        "sector": "Tech",
                        "exchange": "HOSE",
                    }
                ],
                benchmarks=("VNINDEX", "VN30"),
            )
            mock_provider_cls.return_value = mock_provider

            with pytest.raises(RuntimeError) as exc_info:
                run_pipeline(update_data=True, generated_dir=tmpdir, publish_artifacts=True)

            assert "Incomplete universe scan in update mode" in str(exc_info.value)

    def test_premature_report_generation_prevention(self):
        """Requirement 2 & 3: Ensure pipeline halts at UniverseValidationStage BEFORE calculating quant recommendations when scanning is incomplete."""
        valid_df = make_valid_ohlcv_df("2026-09-01", periods=30)

        def mock_fetch(symbol, start_date, end_date, **kwargs):
            if symbol == "SSI":
                return pd.DataFrame()
            return valid_df

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_fetch,
            ),
            patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls,
            patch(
                "scripts.pipeline.stages.SignalRecommendationEngine.generate_recommendations"
            ) as mock_quant_engine,
        ):
            mock_provider = MagicMock()
            mock_provider.get_universe.return_value = Universe.from_candidates(
                [
                    {
                        "symbol": "FPT",
                        "companyName": "FPT Corp",
                        "sector": "Tech",
                        "exchange": "HOSE",
                    },
                    {
                        "symbol": "SSI",
                        "companyName": "SSI Securities",
                        "sector": "Finance",
                        "exchange": "HOSE",
                    },
                ],
                benchmarks=("VNINDEX", "VN30"),
            )
            mock_provider_cls.return_value = mock_provider

            with pytest.raises(RuntimeError):
                run_pipeline(update_data=True, generated_dir=tmpdir, publish_artifacts=True)

            # Assert quant recommendation engine was NEVER called
            mock_quant_engine.assert_not_called()

    def test_invalid_monitoring_data_causes_publish_rejection_and_preserves_artifacts(self):
        """Requirement 6 & 7: Monitoring failure during ArtifactPublishingStage rejects publish and leaves existing disk artifacts byte-for-byte untouched."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rec_file = os.path.join(tmpdir, "recommendations.json")
            original_content = '{"existing": "canonical_data_v1"}'
            with open(rec_file, "w", encoding="utf-8") as f:
                f.write(original_content)

            mock_check = MagicMock()
            mock_check.check_name = "schema_validation"
            mock_check.status = "FAIL"
            mock_check.measured_value = {}
            mock_check.expected_condition = "Valid schema"
            mock_check.message = "Schema validation error simulated for testing"

            mock_monitoring_res = MagicMock()
            mock_monitoring_res.overall_status = "FAIL"
            mock_monitoring_res.checks = [mock_check]

            context = PipelineContext(
                update_data=True,
                publish_artifacts=True,
                generated_dir=tmpdir,
                tracker=PerformanceTracker(),
            )
            context.monitoring_result = mock_monitoring_res
            context.recommendations_payload = {"new": "corrupt_data"}

            stage = ArtifactPublishingStage()
            with pytest.raises(SystemExit) as cm:
                stage.execute(context)

            assert cm.value.code == 1

            # Read disk file to confirm byte-for-byte preservation
            with open(rec_file, "r", encoding="utf-8") as f:
                preserved_content = f.read()

            assert preserved_content == original_content

    def test_rate_limit_error_during_data_acquisition_halts_pipeline(self):
        """Requirement 7: Unrecoverable ProviderRateLimitError during DataAcquisitionStage propagates and halts pipeline."""
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=ProviderRateLimitError("Rate limit exceeded"),
            ),
            patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls,
        ):
            mock_provider = MagicMock()
            mock_provider.get_universe.return_value = Universe.from_candidates(
                [
                    {
                        "symbol": "FPT",
                        "companyName": "FPT Corp",
                        "sector": "Tech",
                        "exchange": "HOSE",
                    }
                ],
                benchmarks=("VNINDEX", "VN30"),
            )
            mock_provider_cls.return_value = mock_provider

            with pytest.raises(ProviderRateLimitError):
                run_pipeline(update_data=True, generated_dir=tmpdir, publish_artifacts=True)

            # Confirm no files published
            assert not os.path.exists(os.path.join(tmpdir, "recommendations.json"))
