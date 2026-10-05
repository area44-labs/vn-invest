"""Pipeline Execution Context for VN Invest production orchestration."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from scripts.data.models import CanonicalMarketData
from scripts.domain import Recommendation
from scripts.domain.universe import Universe, UniverseScanResult
from scripts.lib.config import SIGNAL_MODEL_VERSION, is_recoverable_category
from scripts.lib.monitoring import PipelineMonitoringResult
from scripts.lib.vietnam_market import UniverseProvider


@dataclass
class PipelineContext:
    """Holds runtime configuration, state, datasets, and execution outputs across pipeline stages."""

    # 1. Configuration
    update_data: bool = False
    publish_artifacts: bool = False
    generated_dir: str = ""
    use_cache: bool | None = None
    throttle: float = 0.0

    # Execution timestamps & reference date
    reference_date: str | None = None
    generated_at: str | None = None

    # 2. Historical execution parameters
    is_historical: bool = False
    historical_data_as_of: str | None = None
    universe_stock_map: dict[str, pd.DataFrame | None] | None = None
    candidate_metadata: list[dict[str, Any]] | None = None

    # Domain Universe contract
    universe: Universe | None = None
    universe_scan_result: UniverseScanResult | None = None

    # 3. Data acquisition state & providers
    provider: UniverseProvider | None = None
    market_data_provider: Any | None = None
    raw_candidate_stocks: list[dict[str, Any]] = field(default_factory=list)
    candidate_stocks: list[dict[str, Any]] = field(default_factory=list)
    universe_info: dict[str, Any] = field(default_factory=dict)

    # Raw acquisition payloads
    raw_vnindex_payload: Any | None = None
    raw_vn30_payload: Any | None = None
    raw_stock_payloads: dict[str, Any] = field(default_factory=dict)

    # Canonical validated market data containers
    canonical_vnindex: CanonicalMarketData | None = None
    canonical_vn30: CanonicalMarketData | None = None
    canonical_stock_map: dict[str, CanonicalMarketData] = field(default_factory=dict)

    # Benchmark raw & clean datasets
    df_vnindex_raw: pd.DataFrame | None = None
    df_vnindex_clean: pd.DataFrame | None = None
    vnindex_val: dict[str, Any] = field(default_factory=dict)
    vn_source: str | None = None

    df_vn30_raw: pd.DataFrame | None = None
    df_vn30_clean: pd.DataFrame | None = None
    vn30_val: dict[str, Any] = field(default_factory=dict)
    vn30_source: str | None = None

    # Stock datasets map: symbol -> (df_stock, tag, warnings)
    stock_data_map: dict[str, tuple[pd.DataFrame, str | None, list[str]]] = field(
        default_factory=dict
    )
    stock_dates_map: dict[str, str | None] = field(default_factory=dict)

    # 4. Derived & calculated quantitative attributes
    data_as_of: str | None = None
    source_date: str | None = None
    data_source: str | None = None

    breadth_ratio: float = 0.50
    final_market_regime: dict[str, Any] | None = None

    scanned_recs: list[Recommendation | Any] = field(default_factory=list)
    scanned_recs_dicts: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    recommendations_payload: dict[str, Any] = field(default_factory=dict)
    market_payload: dict[str, Any] = field(default_factory=dict)
    history_payload: dict[str, Any] = field(default_factory=dict)

    # 5. Validation & Audit
    expected_symbols: set[str] = field(default_factory=set)
    processed_symbols: set[str] = field(default_factory=set)
    invalid_symbols: set[str] = field(default_factory=set)
    insufficient_history_symbols: set[str] = field(default_factory=set)
    failed_symbols: set[str] = field(default_factory=set)
    missing_symbols: set[str] = field(default_factory=set)
    exclusions_map: dict[str, dict[str, Any]] = field(default_factory=dict)

    temporal_res: dict[str, Any] = field(default_factory=dict)
    universe_audit: dict[str, Any] = field(default_factory=dict)

    # 6. Performance tracking (owned by pipeline/runner or test harness)
    tracker: Any = None
    pipeline_elapsed: float = 0.0
    performance_data: dict[str, Any] = field(default_factory=dict)

    # 7. Production monitoring
    monitoring_result: PipelineMonitoringResult | None = None
    monitoring_dict: dict[str, Any] = field(default_factory=dict)

    # 8. Output artifacts
    artifacts_to_publish: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self):
        if self.use_cache is None:
            self.use_cache = not self.update_data

        if self.generated_at is None:
            if self.reference_date:
                self.generated_at = self.reference_date
            else:
                self.generated_at = datetime.now(UTC).isoformat()

    def set_universe(self, universe: Universe) -> None:
        """Assign canonical domain Universe and synchronize context state."""
        self.universe = universe
        self.raw_candidate_stocks = universe.to_candidate_list()
        self.candidate_stocks = universe.to_candidate_list()
        self.universe_info = universe.to_info_dict()
        self.expected_symbols = set(universe.expected_symbols)

    def add_exclusion(
        self,
        symbol: str,
        stage: str,
        category: str,
        status: str,
        reason: str,
        latest_date: str | None = None,
        expected_date: str | None = None,
        processed: bool = False,
    ) -> None:
        """Record a symbol exclusion diagnostic in exclusions_map and update target status set."""
        sym_u = symbol.upper()
        if status == "FAILED":
            self.failed_symbols.add(sym_u)
        elif status == "INVALID":
            self.invalid_symbols.add(sym_u)
        elif status == "INSUFFICIENT":
            self.insufficient_history_symbols.add(sym_u)
        elif status == "MISSING":
            self.missing_symbols.add(sym_u)

        self.exclusions_map[sym_u] = {
            "symbol": sym_u,
            "stage": stage,
            "category": category,
            "status": status,
            "reason": reason,
            "latest_date": latest_date,
            "expected_date": expected_date,
            "processed": processed,
            "recoverable": is_recoverable_category(category),
        }

    def update_universe_audit(self) -> dict[str, Any]:
        """Construct UniverseScanResult and assign universe_audit dictionary."""
        current_u = self.universe
        if not isinstance(current_u, Universe):
            u_type = "HISTORICAL_SNAPSHOT" if self.is_historical else "CUSTOM"
            c_meta = self.candidate_metadata or self.candidate_stocks or []
            if not isinstance(c_meta, (list, tuple, set)):
                c_meta = []
            current_u = Universe.from_candidates(candidates=c_meta, universe_type=u_type)
            self.universe = current_u
            self.expected_symbols = set(current_u.expected_symbols)

        scan_result = UniverseScanResult(
            universe=current_u,
            processed_symbols=tuple(sorted(self.processed_symbols)),
            invalid_symbols=tuple(sorted(self.invalid_symbols)),
            insufficient_symbols=tuple(sorted(self.insufficient_history_symbols)),
            failed_symbols=tuple(sorted(self.failed_symbols)),
            missing_symbols=tuple(sorted(self.missing_symbols)),
            exclusions_map=dict(self.exclusions_map),
            data_as_of=self.data_as_of,
            source_date=self.source_date,
            data_source=self.data_source,
        )
        self.universe_scan_result = scan_result
        self.universe_audit = scan_result.to_audit_dict(
            update_data=self.update_data,
            performance_data=self.performance_data or None,
        )
        return self.universe_audit

    def build_payloads(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Assemble recommendations, market, and history JSON payloads from context state."""
        self.scanned_recs_dicts = [
            r.to_dict() if hasattr(r, "to_dict") else r for r in self.scanned_recs
        ]

        buy_cnt = sum(1 for r in self.scanned_recs if r["action"] == "BUY")
        watch_cnt = sum(1 for r in self.scanned_recs if r["action"] == "WATCH")
        hold_cnt = sum(1 for r in self.scanned_recs if r["action"] == "HOLD")
        sell_cnt = sum(1 for r in self.scanned_recs if r["action"] == "SELL")
        avoid_cnt = sum(1 for r in self.scanned_recs if r["action"] == "AVOID")

        self.summary = {
            "total_scanned": len(self.scanned_recs),
            "buy_count": buy_cnt,
            "watch_count": watch_cnt,
            "hold_count": hold_cnt,
            "sell_count": sell_cnt,
            "avoid_count": avoid_cnt,
        }

        if self.universe:
            u_info = self.universe.to_info_dict()
        elif self.is_historical:
            u_info = {
                "universe_type": "HISTORICAL_SNAPSHOT",
                "universe_size": len(self.candidate_metadata or []),
            }
        else:
            u_info = self.universe_info

        self.recommendations_payload = {
            "schema_version": "2.0",
            "signal_model_version": SIGNAL_MODEL_VERSION,
            "generated_at": self.generated_at,
            "data_as_of": self.data_as_of,
            "source_date": self.source_date,
            "data_source": self.data_source,
            "universe_info": u_info,
            "market": self.final_market_regime,
            "summary": self.summary,
            "recommendations": self.scanned_recs_dicts,
        }

        self.market_payload = {
            "data_as_of": self.data_as_of,
            "source_date": self.source_date,
            "generated_at": self.generated_at,
            "data_source": self.data_source,
            "universe_info": u_info,
            "market": self.final_market_regime,
            "summary": self.summary,
        }

        self.history_payload = self.recommendations_payload
        return self.recommendations_payload, self.market_payload, self.history_payload


__all__ = ["PipelineContext"]
