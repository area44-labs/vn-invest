"""History subsystem contracts, models, and directory conventions."""

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

MAX_RETAINED_REPORTS: int = 14
DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")

RunStatus = Literal["SUCCESS", "FAILED", "SKIPPED"]
RunType = Literal["SCHEDULED", "MANUAL", "BACKFILL"]

VALID_RUN_STATUSES = {"SUCCESS", "FAILED", "SKIPPED"}
VALID_RUN_TYPES = {"SCHEDULED", "MANUAL", "BACKFILL"}


def is_valid_date_string(date_str: Any) -> bool:
    """Validate canonical YYYY-MM-DD date format and calendar validity."""
    if not isinstance(date_str, str) or not DATE_REGEX.match(date_str):
        return False
    parts = date_str.split("-")
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        dt = datetime(y, m, d, tzinfo=UTC)
        return dt.strftime("%Y-%m-%d") == date_str
    except ValueError:
        return False
    except OverflowError:
        return False


def get_partition_path(base_dir: str, trading_date: str, extension: str = ".jsonl") -> str:
    """Return relative or absolute partitioned file path YYYY/MM/YYYY-MM-DD.<ext>."""
    if not is_valid_date_string(trading_date):
        raise ValueError(f"Invalid canonical trading_date format: {trading_date!r}")
    parts = trading_date.split("-")
    year, month = parts[0], parts[1]
    filename = f"{trading_date}{extension}"
    return os.path.join(base_dir, year, month, filename)


def generate_recommendation_id(
    trading_date: str,
    symbol: str,
    action: str,
    model_version: str | None = None,
    config_hash: str | None = None,
) -> str:
    """Generate deterministic, stable recommendation identity."""
    if not is_valid_date_string(trading_date):
        raise ValueError(f"Invalid trading_date for recommendation identity: {trading_date!r}")
    if not symbol or not isinstance(symbol, str):
        raise ValueError("Symbol must be a non-empty string")
    if not action or not isinstance(action, str):
        raise ValueError("Action must be a non-empty string")

    clean_sym = symbol.strip().upper()
    clean_action = action.strip().upper()
    mv = str(model_version or "").strip()
    ch = str(config_hash or "").strip()

    fingerprint_raw = f"{trading_date}|{clean_sym}|{clean_action}|{mv}|{ch}"
    h = hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()[:12]
    return f"rec_{trading_date}_{clean_sym}_{h}"


@dataclass(frozen=True)
class RecommendationLedgerEntry:
    """Immutable persistent record of an individual stock recommendation in the historical ledger."""

    recommendation_id: str
    symbol: str
    trading_date: str
    action: str
    reference_price: float | None = None
    target_price: float | None = None
    confidence: float | None = None
    signal_score: float | None = None
    risk_adjusted_score: float | None = None
    risk_level: str | None = None
    strategy_version: str | None = None
    model_version: str | None = None
    config_hash: str | None = None
    reasons: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.recommendation_id or not isinstance(self.recommendation_id, str):
            raise ValueError("recommendation_id must be a non-empty string")
        if not self.symbol or not isinstance(self.symbol, str):
            raise ValueError("symbol must be a non-empty string")
        if not is_valid_date_string(self.trading_date):
            raise ValueError(f"trading_date must be valid YYYY-MM-DD date: {self.trading_date!r}")
        if not self.action or not isinstance(self.action, str):
            raise ValueError("action must be a non-empty string")
        if self.schema_version < 1:
            raise ValueError(f"Invalid schema_version: {self.schema_version}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize ledger entry to dictionary."""
        return {
            "recommendation_id": self.recommendation_id,
            "symbol": self.symbol,
            "trading_date": self.trading_date,
            "action": self.action,
            "reference_price": self.reference_price,
            "target_price": self.target_price,
            "confidence": self.confidence,
            "signal_score": self.signal_score,
            "risk_adjusted_score": self.risk_adjusted_score,
            "risk_level": self.risk_level,
            "strategy_version": self.strategy_version,
            "model_version": self.model_version,
            "config_hash": self.config_hash,
            "reasons": list(self.reasons),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecommendationLedgerEntry:
        """Deserialize ledger entry from dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data).__name__}")
        return cls(
            recommendation_id=str(data["recommendation_id"]),
            symbol=str(data["symbol"]).strip().upper(),
            trading_date=str(data["trading_date"]),
            action=str(data["action"]).strip().upper(),
            reference_price=data.get("reference_price"),
            target_price=data.get("target_price"),
            confidence=data.get("confidence"),
            signal_score=data.get("signal_score"),
            risk_adjusted_score=data.get("risk_adjusted_score"),
            risk_level=data.get("risk_level"),
            strategy_version=data.get("strategy_version"),
            model_version=data.get("model_version"),
            config_hash=data.get("config_hash"),
            reasons=tuple(data.get("reasons") or ()),
            schema_version=int(data.get("schema_version", 1)),
        )


@dataclass(frozen=True)
class RunManifestEntry:
    """Immutable persistent record of a pipeline run execution."""

    run_id: str
    trading_date: str
    generated_at: str
    status: str
    run_type: str = "SCHEDULED"
    error_metadata: dict[str, Any] | None = None
    commit_sha: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.run_id or not isinstance(self.run_id, str):
            raise ValueError("run_id must be a non-empty string")
        if not is_valid_date_string(self.trading_date):
            raise ValueError(f"trading_date must be valid YYYY-MM-DD date: {self.trading_date!r}")
        if not self.generated_at or not isinstance(self.generated_at, str):
            raise ValueError("generated_at must be a non-empty ISO timestamp string")
        if self.status not in VALID_RUN_STATUSES:
            raise ValueError(
                f"Invalid status '{self.status}'. Must be one of {sorted(VALID_RUN_STATUSES)}"
            )
        if self.run_type not in VALID_RUN_TYPES:
            raise ValueError(
                f"Invalid run_type '{self.run_type}'. Must be one of {sorted(VALID_RUN_TYPES)}"
            )
        if self.schema_version < 1:
            raise ValueError(f"Invalid schema_version: {self.schema_version}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize run manifest entry to dictionary."""
        return {
            "run_id": self.run_id,
            "trading_date": self.trading_date,
            "generated_at": self.generated_at,
            "status": self.status,
            "run_type": self.run_type,
            "error_metadata": dict(self.error_metadata) if self.error_metadata else None,
            "commit_sha": self.commit_sha,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunManifestEntry:
        """Deserialize run manifest entry from dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data).__name__}")
        return cls(
            run_id=str(data["run_id"]),
            trading_date=str(data["trading_date"]),
            generated_at=str(data["generated_at"]),
            status=str(data["status"]).strip().upper(),
            run_type=str(data.get("run_type", "SCHEDULED")).strip().upper(),
            error_metadata=data.get("error_metadata"),
            commit_sha=data.get("commit_sha"),
            schema_version=int(data.get("schema_version", 1)),
        )


@dataclass(frozen=True)
class HistoryDirectoryConventions:
    """Authoritative storage contracts and directory paths for historical subsystems."""

    base_generated_dir: str

    @property
    def history_reports_dir(self) -> str:
        """Directory containing historical daily report files."""
        return os.path.join(self.base_generated_dir, "history")

    @property
    def history_index_path(self) -> str:
        """Path to canonical history index file."""
        return os.path.join(self.history_reports_dir, "index.json")

    @property
    def recommendation_ledger_dir(self) -> str:
        """Directory containing partitioned recommendation ledger records."""
        return os.path.join(self.base_generated_dir, "recommendation-ledger")

    @property
    def run_manifest_dir(self) -> str:
        """Directory containing partitioned pipeline execution run manifest records."""
        return os.path.join(self.base_generated_dir, "run-manifest")

    @property
    def evaluations_dir(self) -> str:
        """Directory reserved for future Evaluation Engine partitioned evaluation records (PR 2)."""
        return os.path.join(self.base_generated_dir, "evaluations")

    @property
    def evaluation_summary_dir(self) -> str:
        """Directory reserved for future Evaluation Engine summaries (PR 2)."""
        return os.path.join(self.base_generated_dir, "evaluation-summary")

    @property
    def evaluation_summary_latest_path(self) -> str:
        """Path to future evaluation summary file (PR 2)."""
        return os.path.join(self.evaluation_summary_dir, "latest.json")

    def get_ledger_partition_path(self, trading_date: str) -> str:
        return get_partition_path(self.recommendation_ledger_dir, trading_date, ".jsonl")

    def get_manifest_partition_path(self, trading_date: str) -> str:
        return get_partition_path(self.run_manifest_dir, trading_date, ".jsonl")

    def get_evaluations_partition_path(self, trading_date: str) -> str:
        return get_partition_path(self.evaluations_dir, trading_date, ".jsonl")


__all__ = [
    "MAX_RETAINED_REPORTS",
    "HistoryDirectoryConventions",
    "RecommendationLedgerEntry",
    "RunManifestEntry",
    "generate_recommendation_id",
    "get_partition_path",
    "is_valid_date_string",
]
