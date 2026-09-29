"""Pipeline Result Contracts for VN Invest production orchestration."""

from dataclasses import dataclass, field
from typing import Any

from scripts.domain.pipeline_result import PipelineResult


@dataclass
class StageResult:
    """Represents the execution outcome of an individual pipeline stage."""

    stage_name: str
    status: str = "SUCCESS"  # SUCCESS, FAILED, SKIPPED, DEGRADED
    elapsed_seconds: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


__all__ = ["PipelineResult", "StageResult"]
