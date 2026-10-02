"""Pipeline Execution Context for VN Invest production orchestration."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class PipelineContext:
    """Holds runtime configuration, state, datasets, and execution outputs across pipeline stages."""

    update_data: bool = False
    publish_artifacts: bool = False
    tracker: Any = None
    generated_dir: str = ""
    reference_date: str | None = None

    # Historical execution parameters
    is_historical: bool = False
    historical_data_as_of: str | None = None
    universe_stock_map: dict[str, Any] | None = None
    candidate_metadata: list[dict[str, Any]] | None = None

    # Calculated & runtime attributes
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    use_cache: bool = True
    throttle: float = 0.0

    provider: Any = None
    raw_candidate_stocks: list[dict[str, Any]] = field(default_factory=list)
    candidate_stocks: list[dict[str, Any]] = field(default_factory=list)
    universe_info: dict[str, Any] = field(default_factory=dict)

    expected_symbols: set[str] = field(default_factory=set)
    processed_symbols: set[str] = field(default_factory=set)
    invalid_symbols: set[str] = field(default_factory=set)
    insufficient_history_symbols: set[str] = field(default_factory=set)
    failed_symbols: set[str] = field(default_factory=set)
    missing_symbols: set[str] = field(default_factory=set)
    exclusions_map: dict[str, dict[str, Any]] = field(default_factory=dict)

    df_vnindex_raw: Any = None
    df_vnindex_clean: Any = None
    vnindex_val: dict[str, Any] = field(default_factory=dict)
    vn_source: Any = None

    data_as_of: str | None = None
    source_date: str | None = None
    data_source: str | None = None

    df_vn30_raw: Any = None
    df_vn30_clean: Any = None
    vn30_val: dict[str, Any] = field(default_factory=dict)
    vn30_source: Any = None

    stock_data_map: dict[str, tuple[Any, Any, Any]] = field(default_factory=dict)
    stock_dates_map: dict[str, str | None] = field(default_factory=dict)

    temporal_res: dict[str, Any] = field(default_factory=dict)
    universe_audit: dict[str, Any] = field(default_factory=dict)

    breadth_ratio: float = 0.50
    final_market_regime: dict[str, Any] | None = None

    scanned_recs: list[Any] = field(default_factory=list)
    scanned_recs_dicts: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    recommendations_payload: dict[str, Any] = field(default_factory=dict)
    market_payload: dict[str, Any] = field(default_factory=dict)
    history_payload: dict[str, Any] = field(default_factory=dict)

    pipeline_elapsed: float = 0.0
    performance_data: dict[str, Any] = field(default_factory=dict)

    monitoring_result: Any = None
    monitoring_dict: dict[str, Any] = field(default_factory=dict)

    artifacts_to_publish: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self):
        self.use_cache = not self.update_data
        if self.reference_date:
            self.generated_at = self.reference_date


__all__ = ["PipelineContext"]
