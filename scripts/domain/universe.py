"""Domain contract for Market Universe definitions, candidates, and scan results."""

from dataclasses import dataclass, field
from typing import Any, Self

VALID_EXCHANGES = {"HOSE", "HNX", "UPCOM"}
DEFAULT_BENCHMARKS = ("VNINDEX", "VN30")


@dataclass(frozen=True)
class UniverseCandidate:
    """Immutable domain representation of a candidate stock in the universe."""

    symbol: str
    company_name: str
    sector: str
    exchange: str

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("Field 'symbol' must be a non-empty string")

        sym_u = self.symbol.strip().upper()
        object.__setattr__(self, "symbol", sym_u)

        if not isinstance(self.company_name, str) or not self.company_name.strip():
            raise ValueError(f"Candidate [{sym_u}] field 'company_name' must be a non-empty string")
        object.__setattr__(self, "company_name", self.company_name.strip())

        if not isinstance(self.sector, str) or not self.sector.strip():
            raise ValueError(f"Candidate [{sym_u}] field 'sector' must be a non-empty string")
        object.__setattr__(self, "sector", self.sector.strip())

        if not isinstance(self.exchange, str) or not self.exchange.strip():
            raise ValueError(f"Candidate [{sym_u}] field 'exchange' must be a non-empty string")
        ex_u = self.exchange.strip().upper()
        if ex_u not in VALID_EXCHANGES:
            raise ValueError(
                f"Candidate [{sym_u}] invalid exchange '{self.exchange}'. Must be one of {sorted(VALID_EXCHANGES)}"
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
            exchange=data.get("exchange", ""),
        )


@dataclass(frozen=True)
class Universe:
    """Immutable domain representation of a stock market candidate universe."""

    universe_type: str
    candidates: tuple[UniverseCandidate, ...] = ()
    benchmarks: tuple[str, ...] = ()
    scanned_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.universe_type, str) or not self.universe_type.strip():
            raise ValueError("Field 'universe_type' must be a non-empty string")

        bmarks = []
        if isinstance(self.benchmarks, (list, tuple, set, dict)):
            for idx, bm in enumerate(self.benchmarks):
                if not isinstance(bm, str) or not bm.strip():
                    raise ValueError(f"Benchmark symbol at index {idx} must be a non-empty string")
                bmarks.append(bm.strip().upper())
        else:
            raise TypeError(
                f"Field 'benchmarks' must be a tuple, list, or set, got {type(self.benchmarks).__name__}"
            )

        cands = []
        seen_symbols = set()
        if isinstance(self.candidates, (list, tuple, set)):
            for idx, item in enumerate(self.candidates):
                if isinstance(item, UniverseCandidate):
                    cand = item
                elif isinstance(item, dict):
                    item_norm = dict(item)
                    ex = item_norm.get("exchange")
                    if not ex or not isinstance(ex, str) or not ex.strip():
                        item_norm["exchange"] = "HOSE"
                    cand = UniverseCandidate.from_dict(item_norm)
                else:
                    raise TypeError(
                        f"Candidate item at index {idx} must be UniverseCandidate or dict, got {type(item).__name__}"
                    )
                if cand.symbol not in seen_symbols:
                    seen_symbols.add(cand.symbol)
                    cands.append(cand)
        else:
            raise TypeError(
                f"Field 'candidates' must be a tuple or list, got {type(self.candidates).__name__}"
            )

        object.__setattr__(self, "benchmarks", tuple(bmarks))
        object.__setattr__(self, "candidates", tuple(cands))

    @property
    def universe_size(self) -> int:
        """Returns the total number of unique candidate stocks in the universe."""
        return len(self.candidates)

    @property
    def candidate_symbols(self) -> tuple[str, ...]:
        """Returns tuple of candidate stock symbols."""
        return tuple(c.symbol for c in self.candidates)

    @property
    def candidate_symbols_set(self) -> frozenset[str]:
        """Returns frozenset of candidate stock symbols."""
        return frozenset(c.symbol for c in self.candidates)

    @property
    def expected_symbols(self) -> frozenset[str]:
        """Returns frozenset of all expected symbols including benchmarks and candidates."""
        return frozenset(self.benchmarks) | self.candidate_symbols_set

    @property
    def candidate_metadata(self) -> list[dict[str, str]]:
        """Returns candidate metadata list of dictionaries."""
        return [c.to_dict() for c in self.candidates]

    def to_dict(self) -> dict[str, Any]:
        """Convert Universe contract to dictionary representation with all candidates preserved for lossless round-trip."""
        res: dict[str, Any] = {
            "universe_type": self.universe_type,
            "universe_size": self.universe_size,
            "benchmarks": list(self.benchmarks),
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
    def from_candidates(
        cls,
        candidates: Any,
        universe_type: str = "CUSTOM",
        benchmarks: tuple[str, ...] = (),
        scanned_at: str | None = None,
    ) -> Self:
        """Construct Universe from candidates sequence."""
        return cls(
            universe_type=universe_type,
            candidates=tuple(candidates) if isinstance(candidates, (list, tuple, set)) else (),
            benchmarks=tuple(benchmarks) if isinstance(benchmarks, (list, tuple, set)) else (),
            scanned_at=scanned_at,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Construct Universe contract from dictionary representation."""
        if not isinstance(data, dict):
            raise TypeError(f"Input data must be a dict, got {type(data).__name__}")
        candidates_raw = data.get("candidates") or data.get("universe") or []
        bmarks_raw = data.get("benchmarks")
        bmarks = tuple(bmarks_raw) if isinstance(bmarks_raw, (list, tuple, set)) else ()
        return cls(
            universe_type=data.get("universe_type", "CUSTOM"),
            candidates=tuple(candidates_raw),
            benchmarks=bmarks,
            scanned_at=data.get("scanned_at"),
        )


@dataclass(frozen=True)
class UniverseScanResult:
    """Canonical domain representation of a universe scan and completeness coverage evaluation."""

    universe: Universe
    processed_symbols: tuple[str, ...] = ()
    invalid_symbols: tuple[str, ...] = ()
    insufficient_symbols: tuple[str, ...] = ()
    failed_symbols: tuple[str, ...] = ()
    missing_symbols: tuple[str, ...] = ()
    exclusions_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    status: str = "SUCCESS"
    failed_stage: str | None = None
    data_as_of: str | None = None
    source_date: str | None = None
    data_source: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.universe, Universe):
            if isinstance(self.universe, dict):
                object.__setattr__(self, "universe", Universe.from_dict(self.universe))
            else:
                raise TypeError(
                    f"Field 'universe' must be a Universe or dict, got {type(self.universe).__name__}"
                )

        def _clean_syms(syms: Any) -> tuple[str, ...]:
            if isinstance(syms, (list, tuple, set, frozenset)):
                out = []
                for s in syms:
                    if isinstance(s, str) and s.strip():
                        out.append(s.strip().upper())
                return tuple(sorted(set(out)))
            return ()

        object.__setattr__(self, "processed_symbols", _clean_syms(self.processed_symbols))
        object.__setattr__(self, "invalid_symbols", _clean_syms(self.invalid_symbols))
        object.__setattr__(self, "insufficient_symbols", _clean_syms(self.insufficient_symbols))
        object.__setattr__(self, "failed_symbols", _clean_syms(self.failed_symbols))
        object.__setattr__(self, "missing_symbols", _clean_syms(self.missing_symbols))

        ex_map = dict(self.exclusions_map) if isinstance(self.exclusions_map, dict) else {}
        object.__setattr__(self, "exclusions_map", ex_map)

        if not isinstance(self.status, str) or not self.status.strip():
            object.__setattr__(self, "status", "SUCCESS")
        else:
            object.__setattr__(self, "status", self.status.strip().upper())

    @property
    def insufficient_history_symbols(self) -> tuple[str, ...]:
        """Alias for insufficient_symbols for pipeline/audit compatibility."""
        return self.insufficient_symbols

    @property
    def expected_symbols(self) -> frozenset[str]:
        """Returns expected symbols set from universe."""
        return self.universe.expected_symbols

    @property
    def expected_count(self) -> int:
        """Total expected symbol count."""
        return len(self.expected_symbols)

    @property
    def processed_count(self) -> int:
        """Processed symbol count."""
        return len(self.processed_symbols)

    @property
    def invalid_count(self) -> int:
        """Invalid symbol count."""
        return len(self.invalid_symbols)

    @property
    def insufficient_count(self) -> int:
        """Insufficient history symbol count."""
        return len(self.insufficient_symbols)

    @property
    def insufficient_history_count(self) -> int:
        """Alias for insufficient_count."""
        return self.insufficient_count

    @property
    def failed_count(self) -> int:
        """Failed symbol count."""
        return len(self.failed_symbols)

    @property
    def missing_count(self) -> int:
        """Missing symbol count."""
        return len(self.missing_symbols)

    @property
    def processed_ratio(self) -> float:
        """Ratio of processed symbols to expected symbols."""
        return self.processed_count / self.expected_count if self.expected_count > 0 else 0.0

    @property
    def is_complete(self) -> bool:
        """Returns True if expected symbols equal processed + invalid with zero failed/insufficient/missing."""
        if not self.processed_symbols:
            return False
        return (
            set(self.processed_symbols) | set(self.invalid_symbols) == set(self.expected_symbols)
            and not self.failed_symbols
            and not self.insufficient_symbols
            and not self.missing_symbols
        )

    def to_audit_dict(
        self, update_data: bool = False, performance_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Convert scan result to production 'universe_audit' dictionary payload."""
        from scripts.pipeline.audit import build_universe_audit

        return build_universe_audit(
            expected_symbols=self.expected_symbols,
            processed_symbols=self.processed_symbols,
            invalid_symbols=self.invalid_symbols,
            insufficient_history_symbols=self.insufficient_symbols,
            failed_symbols=self.failed_symbols,
            missing_symbols=self.missing_symbols,
            exclusions_map=self.exclusions_map,
            update_data=update_data,
            performance_data=performance_data,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert UniverseScanResult to lossless dictionary representation."""
        res = {
            "universe": self.universe.to_dict(),
            "status": self.status,
            "failed_stage": self.failed_stage,
            "expected_symbols": sorted(self.expected_symbols),
            "processed_symbols": list(self.processed_symbols),
            "invalid_symbols": list(self.invalid_symbols),
            "insufficient_symbols": list(self.insufficient_symbols),
            "failed_symbols": list(self.failed_symbols),
            "missing_symbols": list(self.missing_symbols),
            "exclusions_map": dict(self.exclusions_map),
            "counts": {
                "expected_count": self.expected_count,
                "processed_count": self.processed_count,
                "invalid_count": self.invalid_count,
                "insufficient_count": self.insufficient_count,
                "failed_count": self.failed_count,
                "missing_count": self.missing_count,
                "processed_ratio": self.processed_ratio,
            },
        }
        if self.data_as_of:
            res["data_as_of"] = self.data_as_of
        if self.source_date:
            res["source_date"] = self.source_date
        if self.data_source:
            res["data_source"] = self.data_source
        return res

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Construct UniverseScanResult from dictionary representation."""
        if not isinstance(data, dict):
            raise TypeError(f"Input data must be a dict, got {type(data).__name__}")
        u_raw = data.get("universe") or {}
        u_obj = Universe.from_dict(u_raw) if isinstance(u_raw, dict) else u_raw
        return cls(
            universe=u_obj,
            processed_symbols=tuple(data.get("processed_symbols") or ()),
            invalid_symbols=tuple(data.get("invalid_symbols") or ()),
            insufficient_symbols=tuple(
                data.get("insufficient_symbols") or data.get("insufficient_history_symbols") or ()
            ),
            failed_symbols=tuple(data.get("failed_symbols") or ()),
            missing_symbols=tuple(data.get("missing_symbols") or ()),
            exclusions_map=dict(data.get("exclusions_map") or {}),
            status=data.get("status", "SUCCESS"),
            failed_stage=data.get("failed_stage"),
            data_as_of=data.get("data_as_of"),
            source_date=data.get("source_date"),
            data_source=data.get("data_source"),
        )
