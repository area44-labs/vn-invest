"""Production Pipeline Runner for VN Invest orchestration."""

import logging
import os
import time
from typing import Any

from scripts.pipeline.constants import GENERATED_DIR
from scripts.pipeline.context import PipelineContext
from scripts.pipeline.result import PipelineResult
from scripts.pipeline.stages import (
    ArtifactPublishingStage,
    DataAcquisitionStage,
    DataValidationStage,
    MarketAnalysisStage,
    MonitoringStage,
    PerformanceStage,
    PipelineStage,
    RiskTradePlanStage,
    SignalRecommendationGenerationStage,
    UniverseValidationStage,
)
from scripts.pipeline.tracker import PerformanceTracker

logger = logging.getLogger(__name__)


class ProductionPipeline:
    """Production pipeline orchestrator executing explicit workflow stages in order."""

    def __init__(self, stages: list[PipelineStage] | None = None):
        if stages is None:
            self.stages: list[PipelineStage] = [
                DataAcquisitionStage(),
                DataValidationStage(),
                UniverseValidationStage(),
                MarketAnalysisStage(),
                SignalRecommendationGenerationStage(),
                RiskTradePlanStage(),
                PerformanceStage(),
                MonitoringStage(),
                ArtifactPublishingStage(),
            ]
        else:
            self.stages = stages

    def execute(self, context: PipelineContext) -> PipelineResult:
        """Run all pipeline stages sequentially against context."""
        if context.tracker is None:
            context.tracker = PerformanceTracker()

        if not context.generated_dir:
            context.generated_dir = os.path.abspath(GENERATED_DIR)

        t_pipeline_start = time.perf_counter()

        try:
            for stage in self.stages:
                logger.info("Executing pipeline stage: %s", stage.name)
                stage.execute(context)

            return PipelineResult(
                context.recommendations_payload,
                context.market_payload,
                context.history_payload,
                df_vnindex=context.df_vnindex_clean,
                df_vn30=context.df_vn30_clean
                if context.vn30_val.get("status") != "INSUFFICIENT"
                else None,
                universe_audit=context.universe_audit,
                monitoring_result=context.monitoring_result,
                monitoring_dict=context.monitoring_dict,
            )
        except Exception as exc:
            pipeline_status = "FAILED"
            pipeline_elapsed = time.perf_counter() - t_pipeline_start
            performance_data = context.tracker.get_performance_payload(
                pipeline_elapsed=pipeline_elapsed,
                pipeline_status=pipeline_status,
            )
            if hasattr(exc, "universe_audit") and isinstance(exc.universe_audit, dict):
                exc.universe_audit["performance"] = performance_data
            else:
                if context.expected_symbols:
                    context.performance_data = performance_data
                    audit_partial = context.update_universe_audit()
                    exc.universe_audit = audit_partial
                else:
                    exc.universe_audit = {"performance": performance_data}
            raise


def run_pipeline(
    update_data: bool = False,
    tracker: Any = None,
    generated_dir: str | None = None,
    publish_artifacts: bool = False,
) -> PipelineResult:
    """Execute standard production pipeline."""
    if generated_dir is None:
        generated_dir = GENERATED_DIR

    context = PipelineContext(
        update_data=update_data,
        publish_artifacts=publish_artifacts,
        tracker=tracker,
        generated_dir=os.path.abspath(generated_dir),
    )
    pipeline = ProductionPipeline()
    return pipeline.execute(context)


def generate_historical_report(
    data_as_of: str,
    universe_stock_map: dict[str, Any],
    df_vnindex: Any,
    df_vn30: Any | None = None,
    candidate_metadata: list[dict[str, Any]] | None = None,
    data_source: str = "explicit_historical_input",
    reference_date: str | None = None,
    tracker: Any = None,
    generated_dir: str | None = None,
    publish_artifacts: bool = False,
) -> PipelineResult:
    """Generate a point-in-time historical report using ProductionPipeline."""
    if candidate_metadata is None or not isinstance(candidate_metadata, list):
        raise TypeError("candidate_metadata must be a list of candidate stock dicts")
    if not candidate_metadata:
        raise ValueError("candidate_metadata cannot be empty")

    if not isinstance(universe_stock_map, dict):
        raise TypeError("universe_stock_map must be a dictionary mapping symbols to DataFrames")

    if generated_dir is None:
        generated_dir = GENERATED_DIR

    combined_stock_map = dict(universe_stock_map)
    combined_stock_map["VNINDEX"] = df_vnindex
    if df_vn30 is not None:
        combined_stock_map["VN30"] = df_vn30

    context = PipelineContext(
        update_data=False,
        publish_artifacts=publish_artifacts,
        tracker=tracker,
        generated_dir=os.path.abspath(generated_dir),
        reference_date=reference_date,
        is_historical=True,
        historical_data_as_of=data_as_of,
        universe_stock_map=combined_stock_map,
        candidate_metadata=candidate_metadata,
        data_source=data_source,
    )

    pipeline = ProductionPipeline()
    return pipeline.execute(context)


__all__ = ["ProductionPipeline", "generate_historical_report", "run_pipeline"]
