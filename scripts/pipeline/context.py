"""Pipeline Execution Context for VN Invest production orchestration."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from scripts.data.models import CanonicalMarketData
from scripts.domain import Recommendation
from scripts.domain.universe import Universe, UniverseScanResult
from scripts.domain.universe import UniverseProvider
from scripts.monitoring import PipelineMonitoringResult
from scripts.monitoring.models import is_recoverable_category
from scripts.pipeline.constants import PIPELINE_VERSION
from scripts.quant.config import DEFAULT_QUANT_CONFIG

QUANT_VERSION = DEFAULT_QUANT_CONFIG.quant_version
SIGNAL_MODEL_VERSION = DEFAULT_QUANT_CONFIG.model_version


@dataclass
class PipelineContext:
    """Holds runtime configuration, state, datasets, and execution outputs across pipeline stages."""

    # 1. Configuration
    update_data: bool = False
    publish_artifacts: bool = False
    generated_dir: str = ""
    use_cache: bool | None = None
    throttle: float = 0.0

    # Execution timestamps, versions & reference date
    reference_date: str | None = None
    generated_at: str | None = None
    pipeline_version: str = PIPELINE_VERSION

    # 2. Historical execution parameters
    is_historical: bool = False
    historical_data_as_of: str | None = None
    universe_stock_map: dict[str, pd.DataFrame | None] | None = None
    candidate_metadata: list[dict[str, Any]] | None = None

    # Domain Universe contract (single canonical source of truth)
    _universe: Universe | None = field(default=None, init=False, repr=False)
    _universe_scan_result: UniverseScanResult | None = field(default=None, init=False, repr=False)

    # 3. Data acquisition state & providers
    provider: UniverseProvider | None = None
    market_data_provider: Any | None = None

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

    temporal_res: dict[str, Any] = field(default_factory=dict)

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

    # --- Domain State Properties & Derived Views ---
    @property
    def universe(self) -> Universe | None:
        """The canonical Universe object for this context."""
        return self._universe

    @universe.setter
    def universe(self, val: Universe | None) -> None:
        if val is not None and not isinstance(val, Universe):
            raise TypeError(f"universe must be a Universe or None, got {type(val).__name__}")
        self._universe = val
        if val is not None:
            if self._universe_scan_result is None:
                self._universe_scan_result = UniverseScanResult(universe=val)
            else:
                self._universe_scan_result = self._universe_scan_result.with_updates(universe=val)
        else:
            self._universe_scan_result = None

    @property
    def universe_scan_result(self) -> UniverseScanResult | None:
        """The canonical UniverseScanResult tracking scan coverage."""
        return self._universe_scan_result

    @universe_scan_result.setter
    def universe_scan_result(self, val: UniverseScanResult | None) -> None:
        if val is not None and not isinstance(val, UniverseScanResult):
            raise TypeError(
                f"universe_scan_result must be a UniverseScanResult or None, got {type(val).__name__}"
            )
        self._universe_scan_result = val
        if val is not None:
            self._universe = val.universe

    # Compatibility properties derived directly from canonical domain state
    @property
    def raw_candidate_stocks(self) -> list[dict[str, Any]]:
        return self._universe.to_candidate_list() if self._universe else []

    @raw_candidate_stocks.setter
    def raw_candidate_stocks(self, val: Any) -> None:
        pass

    @property
    def candidate_stocks(self) -> list[dict[str, Any]]:
        return self._universe.to_candidate_list() if self._universe else []

    @candidate_stocks.setter
    def candidate_stocks(self, val: Any) -> None:
        pass

    @property
    def universe_info(self) -> dict[str, Any]:
        return self._universe.to_info_dict() if self._universe else {}

    @universe_info.setter
    def universe_info(self, val: Any) -> None:
        pass

    @property
    def expected_symbols(self) -> set[str]:
        if self._universe:
            return set(self._universe.expected_symbols)
        return set()

    @expected_symbols.setter
    def expected_symbols(self, val: Any) -> None:
        pass

    @property
    def processed_symbols(self) -> set[str]:
        if self._universe_scan_result:
            return set(self._universe_scan_result.processed_symbols)
        return set()

    @processed_symbols.setter
    def processed_symbols(self, val: Any) -> None:
        if not self._universe or not self._universe_scan_result:
            raise ValueError("Cannot set processed_symbols without context.universe")
        self._universe_scan_result = self._universe_scan_result.with_updates(
            processed_symbols=tuple(sorted(val))
        )

    @property
    def invalid_symbols(self) -> set[str]:
        if self._universe_scan_result:
            return set(self._universe_scan_result.invalid_symbols)
        return set()

    @invalid_symbols.setter
    def invalid_symbols(self, val: Any) -> None:
        if not self._universe or not self._universe_scan_result:
            raise ValueError("Cannot set invalid_symbols without context.universe")
        self._universe_scan_result = self._universe_scan_result.with_updates(
            invalid_symbols=tuple(sorted(val))
        )

    @property
    def insufficient_history_symbols(self) -> set[str]:
        if self._universe_scan_result:
            return set(self._universe_scan_result.insufficient_symbols)
        return set()

    @insufficient_history_symbols.setter
    def insufficient_history_symbols(self, val: Any) -> None:
        if not self._universe or not self._universe_scan_result:
            raise ValueError("Cannot set insufficient_history_symbols without context.universe")
        self._universe_scan_result = self._universe_scan_result.with_updates(
            insufficient_symbols=tuple(sorted(val))
        )

    @property
    def failed_symbols(self) -> set[str]:
        if self._universe_scan_result:
            return set(self._universe_scan_result.failed_symbols)
        return set()

    @failed_symbols.setter
    def failed_symbols(self, val: Any) -> None:
        if not self._universe or not self._universe_scan_result:
            raise ValueError("Cannot set failed_symbols without context.universe")
        self._universe_scan_result = self._universe_scan_result.with_updates(
            failed_symbols=tuple(sorted(val))
        )

    @property
    def missing_symbols(self) -> set[str]:
        if self._universe_scan_result:
            return set(self._universe_scan_result.missing_symbols)
        return set()

    @missing_symbols.setter
    def missing_symbols(self, val: Any) -> None:
        if not self._universe or not self._universe_scan_result:
            raise ValueError("Cannot set missing_symbols without context.universe")
        self._universe_scan_result = self._universe_scan_result.with_updates(
            missing_symbols=tuple(sorted(val))
        )

    @property
    def exclusions_map(self) -> dict[str, dict[str, Any]]:
        if self._universe_scan_result:
            return self._universe_scan_result.exclusions_map
        return {}

    @exclusions_map.setter
    def exclusions_map(self, val: Any) -> None:
        if not self._universe or not self._universe_scan_result:
            raise ValueError("Cannot set exclusions_map without context.universe")
        self._universe_scan_result = self._universe_scan_result.with_updates(exclusions_map=val)

    @property
    def universe_audit(self) -> dict[str, Any]:
        if self._universe_scan_result:
            return self._universe_scan_result.to_audit_dict(
                update_data=self.update_data,
                performance_data=self.performance_data or None,
            )
        return {}

    @universe_audit.setter
    def universe_audit(self, val: Any) -> None:
        pass

    def set_universe(self, universe: Universe) -> None:
        """Assign canonical domain Universe as single source of truth and synchronize context state."""
        if not isinstance(universe, Universe):
            raise TypeError(
                f"set_universe requires a Universe instance, got {type(universe).__name__}"
            )
        self.universe = universe

    def record_symbol_processed(self, symbol: str) -> None:
        """Record a symbol as successfully processed in universe_scan_result."""
        if not self._universe or not self._universe_scan_result:
            raise ValueError("Cannot record symbol status without context.universe")

        sym_u = symbol.upper()
        cur_proc = set(self._universe_scan_result.processed_symbols)
        cur_proc.add(sym_u)
        self._universe_scan_result = self._universe_scan_result.with_updates(
            processed_symbols=tuple(sorted(cur_proc))
        )

    def discard_symbol_processed(self, symbol: str) -> None:
        """Remove a symbol from processed_symbols in universe_scan_result."""
        if not self._universe or not self._universe_scan_result:
            raise ValueError("Cannot discard symbol status without context.universe")

        sym_u = symbol.upper()
        cur_proc = set(self._universe_scan_result.processed_symbols)
        cur_proc.discard(sym_u)
        self._universe_scan_result = self._universe_scan_result.with_updates(
            processed_symbols=tuple(sorted(cur_proc))
        )

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
        """Record a symbol exclusion diagnostic in universe_scan_result and update status sets."""
        if not self._universe or not self._universe_scan_result:
            raise ValueError("Cannot add exclusion without context.universe")

        sym_u = symbol.upper()
        res = self._universe_scan_result

        failed = set(res.failed_symbols)
        invalid = set(res.invalid_symbols)
        insufficient = set(res.insufficient_symbols)
        missing = set(res.missing_symbols)

        if status == "FAILED":
            failed.add(sym_u)
        elif status == "INVALID":
            invalid.add(sym_u)
        elif status == "INSUFFICIENT":
            insufficient.add(sym_u)
        elif status == "MISSING":
            missing.add(sym_u)

        ex_map = dict(res.exclusions_map)
        ex_map[sym_u] = {
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

        self._universe_scan_result = res.with_updates(
            failed_symbols=tuple(sorted(failed)),
            invalid_symbols=tuple(sorted(invalid)),
            insufficient_symbols=tuple(sorted(insufficient)),
            missing_symbols=tuple(sorted(missing)),
            exclusions_map=ex_map,
        )

    def update_universe_audit(self) -> dict[str, Any]:
        """Construct UniverseScanResult and return universe_audit dictionary."""
        if not isinstance(self._universe, Universe):
            raise TypeError("PipelineContext.universe must be set to a valid Universe instance")

        if not self._universe_scan_result:
            self._universe_scan_result = UniverseScanResult(universe=self._universe)

        self._universe_scan_result = self._universe_scan_result.with_updates(
            data_as_of=self.data_as_of,
            source_date=self.source_date,
            data_source=self.data_source,
        )
        return self._universe_scan_result.to_audit_dict(
            update_data=self.update_data,
            performance_data=self.performance_data or None,
        )

    def build_payloads(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Assemble recommendations, market, and history JSON payloads from context state."""
        if not self._universe:
            raise ValueError("build_payloads requires context.universe to be set")

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

        u_info = self._universe.to_info_dict()

        quant_versions = set()
        config_hashes = set()

        for r in self.scanned_recs:
            if isinstance(r, dict):
                qv = r.get("quant_version", QUANT_VERSION)
                ch = r.get("config_hash", DEFAULT_QUANT_CONFIG.get_config_hash())
            else:
                qv = getattr(r, "quant_version", QUANT_VERSION)
                ch = getattr(r, "config_hash", DEFAULT_QUANT_CONFIG.get_config_hash())
            quant_versions.add(qv)
            config_hashes.add(ch)

        if not self.scanned_recs:
            q_ver = QUANT_VERSION
            cfg_hash = DEFAULT_QUANT_CONFIG.get_config_hash()
        elif len(quant_versions) == 1 and len(config_hashes) == 1:
            q_ver = next(iter(quant_versions))
            cfg_hash = next(iter(config_hashes))
        else:
            raise ValueError(
                f"Mixed quantitative configuration versions {sorted(quant_versions)} "
                f"or config hashes {sorted(config_hashes)} detected in recommendations batch."
            )

        self.recommendations_payload = {
            "schema_version": "2.0",
            "signal_model_version": SIGNAL_MODEL_VERSION,
            "quant_version": q_ver,
            "config_hash": cfg_hash,
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
            "schema_version": "2.0",
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
