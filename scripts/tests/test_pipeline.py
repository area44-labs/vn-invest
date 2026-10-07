"""Unit tests for ProductionPipeline, PipelineContext, and pipeline stage execution order."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.domain.universe import Universe
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
from scripts.pipeline.tracker import PerformanceTracker


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


@pytest.mark.integration
class TestPipelineContextContractAndLifecycle:
    """Verify PipelineContext contract, typing, lifecycle semantics, and state management helpers."""

    def test_pipeline_context_defaults_and_construction(self):
        """Verify default PipelineContext initialization, decoupled tracker, and attribute defaults."""
        ctx = PipelineContext()

        assert not ctx.update_data
        assert not ctx.publish_artifacts
        assert ctx.use_cache
        assert ctx.throttle == 0.0
        assert ctx.generated_dir == ""
        assert ctx.reference_date is None
        assert ctx.generated_at is not None

        # Context does NOT instantiate PerformanceTracker directly
        assert ctx.tracker is None
        assert len(ctx.expected_symbols) == 0
        assert len(ctx.processed_symbols) == 0
        assert len(ctx.exclusions_map) == 0

        # Update mode defaults use_cache to False
        ctx_update = PipelineContext(update_data=True)
        assert not ctx_update.use_cache

    def test_pipeline_runner_initializes_context_tracker(self):
        """Verify ProductionPipeline manages PerformanceTracker lifecycle when context.tracker is None."""
        ctx = PipelineContext()
        ctx.set_universe(
            Universe.from_candidates(
                [{"symbol": "AAA", "companyName": "Co A", "sector": "Tech", "exchange": "HOSE"}]
            )
        )
        assert ctx.tracker is None

        pipeline = ProductionPipeline(stages=[MockStage("noop", [])])
        pipeline.execute(ctx)

        assert isinstance(ctx.tracker, PerformanceTracker)

    def test_pipeline_context_lifecycle_semantics(self):
        """Verify reference_date, generated_at, data_as_of, and use_cache lifecycle semantics."""
        # reference_date sets generated_at when generated_at is omitted
        ctx = PipelineContext(reference_date="2026-09-01")
        assert ctx.reference_date == "2026-09-01"
        assert ctx.generated_at == "2026-09-01"

        # Explicit generated_at is preserved
        ctx_explicit = PipelineContext(
            reference_date="2026-09-01", generated_at="2026-09-01T12:00:00Z"
        )
        assert ctx_explicit.generated_at == "2026-09-01T12:00:00Z"

        # Explicit use_cache is preserved regardless of update_data
        ctx_cache = PipelineContext(update_data=True, use_cache=True)
        assert ctx_cache.use_cache

        # Tracker passed explicitly is preserved
        custom_tracker = PerformanceTracker()
        ctx_tracker = PipelineContext(tracker=custom_tracker)
        assert ctx_tracker.tracker is custom_tracker

    def test_pipeline_context_add_exclusion_helper(self):
        """Verify add_exclusion helper updates status sets and exclusions_map accurately."""
        ctx = PipelineContext()
        u = Universe.from_candidates(
            [
                {"symbol": "AAA", "companyName": "Comp A", "sector": "Tech", "exchange": "HOSE"},
                {"symbol": "BBB", "companyName": "Comp B", "sector": "Tech", "exchange": "HOSE"},
                {"symbol": "CCC", "companyName": "Comp C", "sector": "Tech", "exchange": "HOSE"},
                {"symbol": "DDD", "companyName": "Comp D", "sector": "Tech", "exchange": "HOSE"},
            ],
            benchmarks=("VNINDEX", "VN30"),
        )
        ctx.set_universe(u)

        ctx.add_exclusion(
            symbol="AAA",
            stage="FETCH",
            category="RATE_LIMIT",
            status="FAILED",
            reason="Cooldown",
            latest_date="2026-08-30",
            expected_date="2026-09-01",
        )
        assert "AAA" in ctx.failed_symbols
        assert "AAA" in ctx.exclusions_map
        assert ctx.exclusions_map["AAA"]["category"] == "RATE_LIMIT"

        ctx.add_exclusion(
            symbol="BBB",
            stage="FETCH",
            category="INVALID_SYMBOL",
            status="INVALID",
            reason="Unrecognized symbol",
        )
        assert "BBB" in ctx.invalid_symbols

        ctx.add_exclusion(
            symbol="CCC",
            stage="FETCH",
            category="INSUFFICIENT_HISTORICAL_DATA",
            status="INSUFFICIENT",
            reason="Short history",
        )
        assert "CCC" in ctx.insufficient_history_symbols

        ctx.add_exclusion(
            symbol="DDD",
            stage="UNIVERSE_DISCOVERY",
            category="UNIVERSE_INCOMPLETE",
            status="MISSING",
            reason="Not found",
        )
        assert "DDD" in ctx.missing_symbols

    def test_pipeline_context_update_universe_audit_helper(self):
        """Verify update_universe_audit constructs valid universe_audit payload."""

        ctx = PipelineContext(update_data=False)
        u = Universe.from_candidates(
            [
                {"symbol": "AAA", "companyName": "Comp A", "sector": "Tech", "exchange": "HOSE"},
                {"symbol": "BBB", "companyName": "Comp B", "sector": "Tech", "exchange": "HOSE"},
            ],
            benchmarks=("VNINDEX", "VN30"),
        )
        ctx.set_universe(u)
        ctx.processed_symbols = {"VNINDEX", "VN30", "AAA"}
        ctx.add_exclusion(
            symbol="BBB",
            stage="STOCK_FETCH",
            category="INSUFFICIENT_HISTORICAL_DATA",
            status="INSUFFICIENT",
            reason="Insufficient sessions",
        )

        audit = ctx.update_universe_audit()
        assert audit["status"] == "DEGRADED"
        assert audit["counts"]["processed_count"] == 3
        assert audit["counts"]["insufficient_history_count"] == 1
        assert "BBB" in audit["insufficient_history_symbols"]

    def test_pipeline_context_build_payloads_helper(self):
        """Verify build_payloads constructs recommendations, market, and history payloads."""
        ctx = PipelineContext(reference_date="2026-09-01")
        u = Universe.from_candidates(
            [
                {"symbol": "AAA", "companyName": "Comp A", "sector": "Tech", "exchange": "HOSE"},
                {"symbol": "BBB", "companyName": "Comp B", "sector": "Tech", "exchange": "HOSE"},
            ],
            benchmarks=("VNINDEX", "VN30"),
        )
        ctx.set_universe(u)
        ctx.data_as_of = "2026-09-01"
        ctx.data_source = "REAL_DATA"
        ctx.final_market_regime = {"regime": "STRONG_BULL"}
        ctx.scanned_recs = [
            {"symbol": "AAA", "action": "BUY"},
            {"symbol": "BBB", "action": "WATCH"},
        ]

        recs_payload, market_payload, history_payload = ctx.build_payloads()

        assert recs_payload["data_as_of"] == "2026-09-01"
        assert recs_payload["summary"]["total_scanned"] == 2
        assert recs_payload["summary"]["buy_count"] == 1
        assert recs_payload["summary"]["watch_count"] == 1

        assert market_payload["market"]["regime"] == "STRONG_BULL"
        assert history_payload is recs_payload

    def test_pipeline_stage_to_stage_state_propagation(self):
        """Verify sequential stage execution propagates context state seamlessly."""

        class StageA(PipelineStage):
            @property
            def name(self) -> str:
                return "stage_a"

            def execute(self, context: PipelineContext) -> None:
                u = Universe.from_candidates(
                    [
                        {
                            "symbol": "AAA",
                            "companyName": "Comp A",
                            "sector": "Tech",
                            "exchange": "HOSE",
                        }
                    ],
                    benchmarks=("VNINDEX", "VN30"),
                )
                context.set_universe(u)

        class StageB(PipelineStage):
            @property
            def name(self) -> str:
                return "stage_b"

            def execute(self, context: PipelineContext) -> None:
                context.processed_symbols = set(context.expected_symbols)
                context.scanned_recs = [{"symbol": "AAA", "action": "BUY"}]

        class StageC(PipelineStage):
            @property
            def name(self) -> str:
                return "stage_c"

            def execute(self, context: PipelineContext) -> None:
                context.build_payloads()

        pipeline = ProductionPipeline(stages=[StageA(), StageB(), StageC()])
        context = PipelineContext()
        context.set_universe(
            Universe.from_candidates(
                [{"symbol": "AAA", "companyName": "Co A", "sector": "Tech", "exchange": "HOSE"}]
            )
        )
        pipeline.execute(context)

        assert len(context.candidate_stocks) == 1
        assert context.summary["buy_count"] == 1
        assert "recommendations" in context.recommendations_payload


@pytest.mark.integration
class TestPipelineStageOrderAndConstruction:
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

        assert stage_names == expected_stages
        assert len(pipeline.stages) == 9
        assert isinstance(pipeline.stages[0], DataAcquisitionStage)
        assert isinstance(pipeline.stages[1], DataValidationStage)
        assert isinstance(pipeline.stages[2], UniverseValidationStage)
        assert isinstance(pipeline.stages[3], MarketAnalysisStage)
        assert isinstance(pipeline.stages[4], SignalRecommendationGenerationStage)
        assert isinstance(pipeline.stages[5], RiskTradePlanStage)
        assert isinstance(pipeline.stages[6], PerformanceStage)
        assert isinstance(pipeline.stages[7], MonitoringStage)
        assert isinstance(pipeline.stages[8], ArtifactPublishingStage)

    def test_custom_stage_injection(self):
        """Verify ProductionPipeline accepts custom stage instances."""
        execution_log: list[str] = []
        custom_stages = [
            MockStage("stage_a", execution_log),
            MockStage("stage_b", execution_log),
        ]

        pipeline = ProductionPipeline(stages=custom_stages)
        assert len(pipeline.stages) == 2

        context = PipelineContext()
        context.set_universe(
            Universe.from_candidates(
                [{"symbol": "AAA", "companyName": "Co A", "sector": "Tech", "exchange": "HOSE"}]
            )
        )
        pipeline.execute(context)

        assert execution_log == ["stage_a", "stage_b"]

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
        context.set_universe(
            Universe.from_candidates(
                [{"symbol": "AAA", "companyName": "Co A", "sector": "Tech", "exchange": "HOSE"}]
            )
        )
        pipeline.execute(context)

        assert execution_log == [
            "1_acquisition",
            "2_val",
            "3_universe",
            "4_market",
            "5_signals",
            "6_risk",
            "7_perf",
            "8_monitoring",
            "9_publish",
        ]


@pytest.mark.integration
class TestPipelineProgrammaticExecution:
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
            patch("scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv") as mock_fetch,
            patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls,
        ):
            mock_provider = MagicMock()
            mock_provider.get_universe.return_value = Universe.from_candidates(
                [{"symbol": "AAA", "companyName": "Comp A", "sector": "Tech", "exchange": "HOSE"}],
                benchmarks=("VNINDEX", "VN30"),
            )
            mock_provider_cls.return_value = mock_provider

            mock_fetch.return_value = valid_df

            res = run_pipeline(update_data=False, generated_dir=tmpdir)

            assert isinstance(res, PipelineResult)
            assert len(res) == 3

            recs, market, history = res
            assert "recommendations" in recs
            assert "market" in market
            assert "recommendations" in history

            assert res.df_vnindex is not None
            assert res.universe_audit is not None

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

            assert isinstance(res, PipelineResult)
            recs, market, _ = res
            assert recs["data_as_of"] == "2025-01-20"
            assert market["data_as_of"] == "2025-01-20"


SINGLE_STOCK_UNIVERSE = [
    {"symbol": "AAA", "companyName": "Comp A", "sector": "Tech", "exchange": "HOSE"}
]


@pytest.mark.integration
class TestPipelineErrorAndFailureBehavior:
    def setup_method(self):
        self.sleep_patcher1 = patch("scripts.data.acquisition.time.sleep")
        self.sleep_patcher2 = patch("scripts.data_provider.time.sleep")
        self.sleep_patcher3 = patch("scripts.lib.vietnam_market.time.sleep")
        self.sleep_patcher1.start()
        self.sleep_patcher2.start()
        self.sleep_patcher3.start()

    def teardown_method(self):
        patch.stopall()

    """Verify error handling and failure behavior compatibility."""

    def test_empty_candidate_universe_raises_runtime_error(self):
        """Verify empty candidate universe halts data acquisition with RuntimeError."""
        with patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls:
            mock_provider = MagicMock()
            mock_provider.get_universe.return_value = Universe.from_candidates(
                [], universe_type="EMPTY"
            )
            mock_provider_cls.return_value = mock_provider

            with pytest.raises(RuntimeError) as cm:
                run_pipeline(update_data=False)

            assert "Candidate universe is empty or missing" in str(cm.value)

    def test_update_mode_incomplete_universe_raises_runtime_error(self):
        """Verify update_data=True fails closed with RuntimeError when candidate fetch fails."""
        empty_df = pd.DataFrame()
        with (
            patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls,
            patch("scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv") as mock_fetch,
        ):
            mock_provider = MagicMock()
            mock_provider.get_universe.return_value = Universe.from_candidates(
                [{"symbol": "AAA", "companyName": "Comp A", "sector": "Tech", "exchange": "HOSE"}],
                benchmarks=("VNINDEX", "VN30"),
            )
            mock_provider_cls.return_value = mock_provider

            mock_fetch.return_value = empty_df

            with pytest.raises(RuntimeError) as cm:
                run_pipeline(update_data=True)

            assert "Incomplete universe scan in update mode" in str(cm.value)
            assert hasattr(cm.value, "universe_audit")


@pytest.mark.integration
class TestMonitoringAndPublishingStages:
    """Verify JSON Schema validation preservation and ArtifactPublishingStage behavior."""

    def test_monitoring_stage_enforces_json_schema_validation(self):
        """Verify MonitoringStage enforces schema validation and raises ValueError on invalid payload."""
        context = PipelineContext(tracker=PerformanceTracker())
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
        with pytest.raises(ValueError) as cm:
            stage.execute(context)

        assert "out of range [0.0, 100.0]" in str(cm.value)

    def test_artifact_publishing_stage_publishes_when_enabled(self):
        """Verify ArtifactPublishingStage executes atomic publication when publish_artifacts=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = PipelineContext(publish_artifacts=True, generated_dir=tmpdir)
            context.data_as_of = "2026-09-29"
            context.recommendations_payload = {
                "schema_version": "2.0",
                "signal_model_version": "2.0",
                "generated_at": "2026-09-29T12:00:00Z",
                "data_as_of": "2026-09-29",
                "source_date": "2026-09-29",
                "market": {
                    "regime": "BULL",
                    "confidence": 0.9,
                    "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
                },
                "summary": {
                    "total_scanned": 0,
                    "buy_count": 0,
                    "watch_count": 0,
                    "hold_count": 0,
                    "sell_count": 0,
                    "avoid_count": 0,
                },
                "recommendations": [],
            }
            context.market_payload = {"schema_version": "2.0", "market": {}}
            context.monitoring_dict = {"status": "PASS"}

            stage = ArtifactPublishingStage()
            stage.execute(context)

            assert "recommendations.json" in context.artifacts_to_publish
            assert "market.json" in context.artifacts_to_publish
            assert "monitoring.json" in context.artifacts_to_publish

    def test_artifact_publishing_stage_rejects_monitoring_failure(self):
        """Verify ArtifactPublishingStage raises SystemExit(1) on monitoring FAIL when publish_artifacts=True and logs failed checks."""
        mock_check = MagicMock()
        mock_check.check_name = "drift_market_payload_temporal_safety"
        mock_check.status = "FAIL"
        mock_check.measured_value = "Missing date"
        mock_check.expected_condition = "Valid data_as_of"
        mock_check.message = (
            "Explicit standalone market_payload missing required data_as_of date field"
        )

        mock_monitoring_res = MagicMock()
        mock_monitoring_res.overall_status = "FAIL"
        mock_monitoring_res.checks = [mock_check]

        context = PipelineContext(publish_artifacts=True)
        context.monitoring_result = mock_monitoring_res

        stage = ArtifactPublishingStage()
        with (
            self.assertLogs("scripts.pipeline.stages", level="ERROR") as cm_logs,
            pytest.raises(SystemExit) as cm,
        ):
            stage.execute(context)

        assert cm.value.code == 1
        logged_text = "\n".join(cm_logs.output)
        assert "Production update rejected due to monitoring failure." in logged_text
        assert "Failed monitoring check count: 1" in logged_text
        assert "drift_market_payload_temporal_safety" in logged_text
        assert (
            "Explicit standalone market_payload missing required data_as_of date field"
            in logged_text
        )

    def test_atomic_rejection_preserves_disk_artifacts_byte_for_byte(self):
        """Verify atomic rejection when monitoring fails preserves existing disk artifacts byte-for-byte."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rec_path = os.path.join(tmpdir, "recommendations.json")
            original_content = '{"original": "data"}'
            with open(rec_path, "w", encoding="utf-8") as f:
                f.write(original_content)

            mock_check = MagicMock()
            mock_check.check_name = "test_check"
            mock_check.status = "FAIL"
            mock_check.measured_value = 0
            mock_check.expected_condition = "1"
            mock_check.message = "Failed check reason"

            mock_monitoring_res = MagicMock()
            mock_monitoring_res.overall_status = "FAIL"
            mock_monitoring_res.checks = [mock_check]

            context = PipelineContext(publish_artifacts=True, generated_dir=tmpdir)
            context.monitoring_result = mock_monitoring_res
            context.recommendations_payload = {"new": "payload"}

            stage = ArtifactPublishingStage()
            with pytest.raises(SystemExit):
                stage.execute(context)

            with open(rec_path, "r", encoding="utf-8") as f:
                current_content = f.read()

            assert current_content == original_content
