"""Domain contract for Market Universe definitions and candidates."""

from dataclasses import dataclass
from typing import Any, Self

VALID_EXCHANGES = {"HOSE", "HNX", "UPCOM"}


@dataclass(frozen=True)
class UniverseCandidate:
    """Immutable domain representation of a candidate stock in the universe."""

    symbol: str
    company_name: str
    sector: str
    exchange: str = "HOSE"

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("Field 'symbol' must be a non-empty string")

        sym_u = self.symbol.strip().upper()
        object.__setattr__(self, "symbol", sym_u)

        if not isinstance(self.company_name, str) or not self.company_name.strip():
            raise ValueError(f"Candidate [{sym_u}] field 'company_name' must be a non-empty string")

        if not isinstance(self.sector, str) or not self.sector.strip():
            raise ValueError(f"Candidate [{sym_u}] field 'sector' must be a non-empty string")

        ex_u = self.exchange.strip().upper() if isinstance(self.exchange, str) else "HOSE"
        if ex_u not in VALID_EXCHANGES:
            raise ValueError(
                f"Candidate [{sym_u}] invalid exchange '{ex_u}'. Must be one of {sorted(VALID_EXCHANGES)}"
            )
        object.__setattr__(self, "exchange", ex_u)

    def to_dict(self) -> dict[str, str]:
        """Convert UniverseCandidate contract to dictionary representation."""
        return {
            "symbol": self.symbol,
            "companyName": self.company_name,
            "company_name": self.company_name,
            "sector": self.sector,
            "exchange": self.exchange,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Construct UniverseCandidate contract from dictionary representation."""
        if not isinstance(data, dict):
            raise TypeError(f"Input data must be a dict, got {type(data).__name__}")
        return cls(
            symbol=data.get("symbol", ""),
            company_name=data.get("companyName") or data.get("company_name", ""),
            sector=data.get("sector", ""),
            exchange=data.get("exchange", "HOSE"),
        )


@dataclass(frozen=True)
class Universe:
    """Immutable domain representation of a stock market candidate universe."""

    universe_type: str
    candidates: tuple[UniverseCandidate, ...] = ()
    scanned_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.universe_type, str) or not self.universe_type.strip():
            raise ValueError("Field 'universe_type' must be a non-empty string")

        cands = []
        if isinstance(self.candidates, (list, tuple, set)):
            for idx, item in enumerate(self.candidates):
                if isinstance(item, UniverseCandidate):
                    cands.append(item)
                elif isinstance(item, dict):
                    cands.append(UniverseCandidate.from_dict(item))
                else:
                    raise TypeError(
                        f"Candidate item at index {idx} must be UniverseCandidate or dict, got {type(item).__name__}"
                    )
        else:
            raise TypeError(
                f"Field 'candidates' must be a tuple or list, got {type(self.candidates).__name__}"
            )

        object.__setattr__(self, "candidates", tuple(cands))

    @property
    def universe_size(self) -> int:
        """Returns the total number of candidate stocks in the universe."""
        return len(self.candidates)

    def to_dict(self) -> dict[str, Any]:
        """Convert Universe contract to dictionary representation with all candidates preserved for lossless round-trip."""
        res: dict[str, Any] = {
            "universe_type": self.universe_type,
            "universe_size": self.universe_size,
            "candidates": [c.to_dict() for c in self.candidates],
        }
        if self.scanned_at:
            res["scanned_at"] = self.scanned_at
        return res

    def to_info_dict(self) -> dict[str, Any]:
        """Convert Universe metadata to dictionary matching report payload 'universe_info' schema."""
        res: dict[str, Any] = {
            "universe_type": self.universe_type,
            "universe_size": self.universe_size,
        }
        if self.scanned_at:
            res["scanned_at"] = self.scanned_at
        return res

    def to_candidate_list(self) -> list[dict[str, str]]:
        """Return candidate stocks as list of dictionaries."""
        return [c.to_dict() for c in self.candidates]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Construct Universe contract from dictionary representation."""
        if not isinstance(data, dict):
            raise TypeError(f"Input data must be a dict, got {type(data).__name__}")
        candidates_raw = data.get("candidates") or data.get("universe") or []
        return cls(
            universe_type=data.get("universe_type", "CUSTOM"),
            candidates=tuple(candidates_raw),
            scanned_at=data.get("scanned_at"),
        )
