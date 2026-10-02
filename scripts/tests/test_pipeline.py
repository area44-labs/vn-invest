"""Unit tests for ProductionPipeline and pipeline stage execution order."""

import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from scripts.pipeline import (
    ArtifactPublishingStage,
    DataAcquisitionStage,
    DataValidationStage,
    MarketAnalysisStage,
    MonitoringStage,
    PerformanceStage,
    PipelineContext,
    PipelineResult,
    PipelineStage,
    ProductionPipeline,
    RiskTradePlanStage,
    SignalRecommendationGenerationStage,
    UniverseValidationStage,
    generate_historical_report,
    run_pipeline,
)


class MockStage(PipelineStage):
    """Test double for tracking stage execution order."""

    def __init__(self, stage_name: str, execution_log: list[str]):
        self._name = stage_name
        self.execution_log = execution_log

    @property
    def name(self) -> str:
        return self._name

    def execute(self, context: PipelineContext) -> None:
        self.execution_log.append(self._name)


class TestPipelineStageOrderAndConstruction(unittest.TestCase):
    """Verify ProductionPipeline stage construction and strict execution order."""

    def test_default_stage_construction_and_ordering(self):
        """Verify default ProductionPipeline constructs all 9 stages in canonical order."""
        pipeline = ProductionPipeline()
        stage_names = [stage.name for stage in pipeline.stages]

        expected_stages = [
            "data_acquisition",
            "data_validation",
            "universe_validation",
            "market_analysis",
            "signal_recommendation_generation",
            "risk_trade_plan",
            "performance",
            "monitoring",
            "artifact_publishing",
        ]

        self.assertEqual(stage_names, expected_stages)
        self.assertEqual(len(pipeline.stages), 9)
        self.assertIsInstance(pipeline.stages[0], DataAcquisitionStage)
        self.assertIsInstance(pipeline.stages[1], DataValidationStage)
        self.assertIsInstance(pipeline.stages[2], UniverseValidationStage)
        self.assertIsInstance(pipeline.stages[3], MarketAnalysisStage)
        self.assertIsInstance(pipeline.stages[4], SignalRecommendationGenerationStage)
        self.assertIsInstance(pipeline.stages[5], RiskTradePlanStage)
        self.assertIsInstance(pipeline.stages[6], PerformanceStage)
        self.assertIsInstance(pipeline.stages[7], MonitoringStage)
        self.assertIsInstance(pipeline.stages[8], ArtifactPublishingStage)

    def test_custom_stage_injection(self):
        """Verify ProductionPipeline accepts custom stage instances."""
        execution_log: list[str] = []
        custom_stages = [
            MockStage("stage_a", execution_log),
            MockStage("stage_b", execution_log),
        ]

        pipeline = ProductionPipeline(stages=custom_stages)
        self.assertEqual(len(pipeline.stages), 2)

        context = PipelineContext()
        pipeline.execute(context)

        self.assertEqual(execution_log, ["stage_a", "stage_b"])

    def test_sequential_stage_execution_order(self):
        """Verify stages execute in strict sequential order."""
        execution_log: list[str] = []
        stages = [
            MockStage("1_acquisition", execution_log),
            MockStage("2_val", execution_log),
            MockStage("3_universe", execution_log),
            MockStage("4_market", execution_log),
            MockStage("5_signals", execution_log),
            MockStage("6_risk", execution_log),
            MockStage("7_perf", execution_log),
            MockStage("8_monitoring", execution_log),
            MockStage("9_publish", execution_log),
        ]

        pipeline = ProductionPipeline(stages=stages)
        context = PipelineContext()
        pipeline.execute(context)

        self.assertEqual(
            execution_log,
            [
                "1_acquisition",
                "2_val",
                "3_universe",
                "4_market",
                "5_signals",
                "6_risk",
                "7_perf",
                "8_monitoring",
                "9_publish",
            ],
        )


class TestPipelineProgrammaticExecution(unittest.TestCase):
    """Verify programmatic execution entry points and result structure."""

    def test_run_pipeline_returns_valid_pipeline_result(self):
        """Verify run_pipeline returns PipelineResult with tuple unpacking support."""
        valid_df = pd.DataFrame(
            {
                "time": pd.date_range("2026-09-01", periods=25, freq="D"),
                "open": [10.0] * 25,
                "high": [12.0] * 25,
                "low": [9.0] * 25,
                "close": [11.0] * 25,
                "volume": [1000] * 25,
            }
        )

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("scripts.generate_report.get_historical_data") as mock_get_hist,
            patch("scripts.generate_report.UniverseProvider") as mock_provider_cls,
        ):
            mock_provider = MagicMock()
            mock_provider.candidates = [
                {"symbol": "AAA", "companyName": "Comp A", "sector": "Tech", "exchange": "HOSE"}
            ]
            mock_provider.get_info.return_value = {"universe_type": "TEST", "universe_size": 1}
            mock_provider_cls.return_value = mock_provider

            mock_get_hist.return_value = (valid_df, "REAL_DATA", [])

            res = run_pipeline(update_data=False, generated_dir=tmpdir)

            self.assertIsInstance(res, PipelineResult)
            self.assertEqual(len(res), 3)

            recs, market, history = res
            self.assertIn("recommendations", recs)
            self.assertIn("market", market)
            self.assertIn("recommendations", history)

            self.assertIsNotNone(res.df_vnindex)
            self.assertIsNotNone(res.universe_audit)

    def test_generate_historical_report_returns_pipeline_result(self):
        """Verify generate_historical_report executes cleanly via pipeline."""
        df_vnindex = pd.DataFrame(
            {
                "time": pd.date_range("2025-01-01", periods=30, freq="D"),
                "open": [10.0] * 30,
                "high": [12.0] * 30,
                "low": [9.0] * 30,
                "close": [11.0] * 30,
                "volume": [1000] * 30,
            }
        )
        df_stock = df_vnindex.copy()

        universe_map = {"AAA": df_stock}
        candidates = [
            {"symbol": "AAA", "companyName": "Comp A", "sector": "Tech", "exchange": "HOSE"}
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            res = generate_historical_report(
                data_as_of="2025-01-20",
                universe_stock_map=universe_map,
                df_vnindex=df_vnindex,
                candidate_metadata=candidates,
                generated_dir=tmpdir,
            )

            self.assertIsInstance(res, PipelineResult)
            recs, market, _ = res
            self.assertEqual(recs["data_as_of"], "2025-01-20")
            self.assertEqual(market["data_as_of"], "2025-01-20")


class TestPipelineErrorAndFailureBehavior(unittest.TestCase):
    """Verify error handling and failure behavior compatibility."""

    def test_empty_candidate_universe_raises_runtime_error(self):
        """Verify empty candidate universe halts data acquisition with RuntimeError."""
        with patch("scripts.generate_report.UniverseProvider") as mock_provider_cls:
            mock_provider = MagicMock()
            mock_provider.candidates = []
            mock_provider_cls.return_value = mock_provider

            with self.assertRaises(RuntimeError) as cm:
                run_pipeline(update_data=False)

            self.assertIn("Candidate universe is empty", str(cm.exception))

    def test_update_mode_incomplete_universe_raises_runtime_error(self):
        """Verify update_data=True fails closed with RuntimeError when candidate fetch fails."""
        empty_df = pd.DataFrame()
        with (
            patch("scripts.generate_report.UniverseProvider") as mock_provider_cls,
            patch("scripts.generate_report.get_historical_data") as mock_get_hist,
        ):
            mock_provider = MagicMock()
            mock_provider.candidates = [
                {"symbol": "AAA", "companyName": "Comp A", "sector": "Tech", "exchange": "HOSE"}
            ]
            mock_provider.get_info.return_value = {"universe_type": "TEST", "universe_size": 1}
            mock_provider_cls.return_value = mock_provider

            mock_get_hist.return_value = (empty_df, "PROVIDER_FAILURE", ["Error"])

            with self.assertRaises(RuntimeError) as cm:
                run_pipeline(update_data=True)

            self.assertIn("Incomplete universe scan in update mode", str(cm.exception))
            self.assertTrue(hasattr(cm.exception, "universe_audit"))


class TestMonitoringAndPublishingStages(unittest.TestCase):
    """Verify JSON Schema validation preservation and ArtifactPublishingStage behavior."""

    def test_monitoring_stage_enforces_json_schema_validation(self):
        """Verify MonitoringStage enforces schema validation and raises ValueError on invalid payload."""
        from scripts.generate_report import PerformanceTracker

        context = PipelineContext()
        context.tracker = PerformanceTracker()
        context.recommendations_payload = {
            "schema_version": "2.0",
            "signal_model_version": "2.0.0",
            "generated_at": "2026-09-29T12:00:00Z",
            "data_as_of": "2026-09-29",
            "source_date": "2026-09-29",
            "data_source": "TEST",
            "universe_info": {"universe_size": 1},
            "market": {"regime": "BULLISH"},
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
                    "symbol": "AAA",
                    "company_name": "Comp A",
                    "exchange": "HOSE",
                    "sector": "Tech",
                    "action": "BUY",
                    "signal_score": 150.0,  # Invalid score > 100.0 violates schema!
                    "data_as_of": "2026-09-29",
                }
            ],
        }
        context.market_payload = {"data_as_of": "2026-09-29"}
        context.history_payload = context.recommendations_payload
        context.is_historical = True

        stage = MonitoringStage()
        with self.assertRaises(ValueError) as cm:
            stage.execute(context)

        self.assertIn("out of range [0.0, 100.0]", str(cm.exception))

    def test_artifact_publishing_stage_publishes_when_enabled(self):
        """Verify ArtifactPublishingStage executes atomic publication when publish_artifacts=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = PipelineContext(publish_artifacts=True, generated_dir=tmpdir)
            context.data_as_of = "2026-09-29"
            context.recommendations_payload = {"recommendations": []}
            context.market_payload = {"market": {}}
            context.monitoring_dict = {"status": "PASS"}

            stage = ArtifactPublishingStage()
            stage.execute(context)

            self.assertIn("recommendations.json", context.artifacts_to_publish)
            self.assertIn("market.json", context.artifacts_to_publish)
            self.assertIn("monitoring.json", context.artifacts_to_publish)

    def test_artifact_publishing_stage_rejects_monitoring_failure(self):
        """Verify ArtifactPublishingStage raises SystemExit(1) on monitoring FAIL when publish_artifacts=True."""
        mock_monitoring_res = MagicMock()
        mock_monitoring_res.overall_status = "FAIL"

        context = PipelineContext(publish_artifacts=True)
        context.monitoring_result = mock_monitoring_res

        stage = ArtifactPublishingStage()
        with self.assertRaises(SystemExit) as cm:
            stage.execute(context)

        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
