"""Domain contract for Data Quality evaluation."""

from dataclasses import dataclass
from typing import Any, Self

VALID_DATA_QUALITY_STATUSES = {"SUFFICIENT", "PARTIAL", "INSUFFICIENT"}


@dataclass(frozen=True)
class DataQuality:
    """Immutable domain representation of data quality status for symbol or benchmark.

    Validates status against allowed enum values {"SUFFICIENT", "PARTIAL", "INSUFFICIENT"}.
    """

    status: str
    issues: tuple[str, ...] = ()
    valid_row_count: int = 0
    latest_date: str | None = None
    data_as_of: str | None = None
    data_source: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or self.status not in VALID_DATA_QUALITY_STATUSES:
            raise ValueError(
                f"Invalid data quality status '{self.status}'. Must be one of {sorted(VALID_DATA_QUALITY_STATUSES)}"
            )

        if isinstance(self.issues, (list, set)):
            object.__setattr__(self, "issues", tuple(str(i) for i in self.issues))
        elif not isinstance(self.issues, tuple):
            raise TypeError(
                f"Field 'issues' must be a tuple or list, got {type(self.issues).__name__}"
            )

        if isinstance(self.valid_row_count, bool) or not isinstance(self.valid_row_count, int):
            raise TypeError(
                f"Field 'valid_row_count' must be an integer, got {type(self.valid_row_count).__name__}"
            )

        if self.valid_row_count < 0:
            raise ValueError(
                f"Field 'valid_row_count' must be non-negative (>= 0), got {self.valid_row_count}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert DataQuality contract to dictionary representation."""
        return {
            "status": self.status,
            "issues": list(self.issues),
            "valid_row_count": self.valid_row_count,
            "latest_date": self.latest_date,
            "data_as_of": self.data_as_of,
            "data_source": self.data_source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Construct DataQuality contract from dictionary representation."""
        if not isinstance(data, dict):
            raise TypeError(f"Input data must be a dict, got {type(data).__name__}")
        return cls(
            status=data.get("status", "INSUFFICIENT"),
            issues=tuple(data.get("issues", [])),
            valid_row_count=data.get("valid_row_count", 0),
            latest_date=data.get("latest_date"),
            data_as_of=data.get("data_as_of"),
            data_source=data.get("data_source"),
        )
