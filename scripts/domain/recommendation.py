"""Domain contract for Stock Recommendations."""

import math
from dataclasses import dataclass, replace
from typing import Any, Self

from scripts.domain.data_quality import VALID_DATA_QUALITY_STATUSES
from scripts.domain.risk_assessment import RiskAssessment
from scripts.domain.trade_plan import TradePlan
from scripts.domain.universe import VALID_EXCHANGES

VALID_ACTIONS = {"BUY", "WATCH", "HOLD", "SELL", "AVOID"}


def _validate_score_or_none(val: Any, name: str) -> float | None:
    """Validate that val can be float or None in range [0.0, 100.0]."""
    if val is None:
        return None
    if isinstance(val, bool):
        raise TypeError(f"Field '{name}' must be numeric or None, got bool")
    try:
        f = float(val)
    except (ValueError, TypeError) as err:
        raise TypeError(
            f"Field '{name}' must be numeric or None, got {type(val).__name__}"
        ) from err
    if math.isnan(f) or math.isinf(f):
        raise ValueError(f"Field '{name}' cannot be NaN or Inf, got {f}")
    if f < 0.0 or f > 100.0:
        raise ValueError(f"Field '{name}' must be between 0.0 and 100.0, got {f}")
    return f


def _validate_confidence(val: Any) -> float:
    """Validate that val is a float in range [0.0, 1.0]."""
    if val is None or isinstance(val, bool):
        raise TypeError(f"Field 'confidence' must be float, got {type(val).__name__}")
    try:
        f = float(val)
    except (ValueError, TypeError) as err:
        raise TypeError(f"Field 'confidence' must be numeric, got {type(val).__name__}") from err
    if math.isnan(f) or math.isinf(f):
        raise ValueError(f"Field 'confidence' cannot be NaN or Inf, got {f}")
    if f < 0.0 or f > 1.0:
        raise ValueError(f"Field 'confidence' must be between 0.0 and 1.0, got {f}")
    return f


@dataclass(frozen=True)
class Recommendation:
    """Immutable domain representation of a stock recommendation output.

    Maintains 100% field semantics with existing production schema while enforcing
    type safety, score bounds, allowed actions, and dict-like backward compatibility.
    """

    symbol: str
    company_name: str
    exchange: str
    sector: str
    action: str
    model_version: str
    data_quality: str
    data_quality_issues: tuple[str, ...] = ()
    data_as_of: str | None = None
    data_source: str | None = None
    signal_score: float | None = None
    risk_adjusted_score: float | None = None
    score_components: dict[str, float | None] | None = None
    confidence: float = 0.10
    risk_level: str | None = None
    expected_return: dict[str, float | None] | None = None
    risk_metrics: RiskAssessment | dict[str, Any] | None = None
    trade_plan: TradePlan | dict[str, Any] | None = None
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    invalidation: tuple[str, ...] = ()
    divergence: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("Field 'symbol' must be a non-empty string")
        sym_u = self.symbol.strip().upper()
        object.__setattr__(self, "symbol", sym_u)

        if not isinstance(self.company_name, str) or not self.company_name.strip():
            raise ValueError(f"Recommendation [{sym_u}] 'company_name' must be a non-empty string")
        object.__setattr__(self, "company_name", self.company_name.strip())

        if not isinstance(self.sector, str) or not self.sector.strip():
            raise ValueError(f"Recommendation [{sym_u}] 'sector' must be a non-empty string")
        object.__setattr__(self, "sector", self.sector.strip())

        if not isinstance(self.exchange, str) or not self.exchange.strip():
            raise ValueError(f"Recommendation [{sym_u}] 'exchange' must be a non-empty string")
        ex_u = self.exchange.strip().upper()
        if ex_u not in VALID_EXCHANGES:
            raise ValueError(
                f"Recommendation [{sym_u}] invalid exchange '{ex_u}'. Must be one of {sorted(VALID_EXCHANGES)}"
            )
        object.__setattr__(self, "exchange", ex_u)

        if not isinstance(self.action, str) or self.action not in VALID_ACTIONS:
            raise ValueError(
                f"Recommendation [{sym_u}] invalid action '{self.action}'. Must be one of {sorted(VALID_ACTIONS)}"
            )

        if (
            not isinstance(self.data_quality, str)
            or self.data_quality not in VALID_DATA_QUALITY_STATUSES
        ):
            raise ValueError(
                f"Recommendation [{sym_u}] invalid data_quality '{self.data_quality}'. Must be one of {sorted(VALID_DATA_QUALITY_STATUSES)}"
            )

        sig_score = _validate_score_or_none(self.signal_score, "signal_score")
        ra_score = _validate_score_or_none(self.risk_adjusted_score, "risk_adjusted_score")
        conf = _validate_confidence(self.confidence)

        object.__setattr__(self, "signal_score", sig_score)
        object.__setattr__(self, "risk_adjusted_score", ra_score)
        object.__setattr__(self, "confidence", conf)

        # Ensure tuple types for sequence fields
        for field_name in ("data_quality_issues", "reasons", "warnings", "invalidation"):
            val = getattr(self, field_name)
            if isinstance(val, (list, set)):
                object.__setattr__(self, field_name, tuple(str(x) for x in val))
            elif not isinstance(val, tuple):
                raise TypeError(
                    f"Recommendation [{sym_u}] field '{field_name}' must be tuple or list"
                )

        # Normalize score_components
        if self.score_components is None:
            object.__setattr__(
                self,
                "score_components",
                {
                    "trend": None,
                    "momentum": None,
                    "volume": None,
                    "relative_strength": None,
                    "divergence": None,
                },
            )

        # Normalize expected_return
        if self.expected_return is None:
            object.__setattr__(
                self,
                "expected_return",
                {
                    "expected_return_5d": None,
                    "expected_return_10d": None,
                    "expected_return_20d": None,
                },
            )

        # Normalize divergence
        if self.divergence is None:
            object.__setattr__(
                self,
                "divergence",
                {"1H": "NONE", "1D": "NONE", "1W": "NONE", "1M": "NONE"},
            )

        # Coerce risk_metrics to RiskAssessment instance if dict passed
        if isinstance(self.risk_metrics, dict):
            object.__setattr__(
                self,
                "risk_metrics",
                RiskAssessment.from_dict(self.risk_metrics, risk_level=self.risk_level),
            )
        elif self.risk_metrics is None:
            object.__setattr__(self, "risk_metrics", RiskAssessment(risk_level=self.risk_level))

        # Synchronize risk_level from risk_metrics if present
        if isinstance(self.risk_metrics, RiskAssessment) and self.risk_metrics.risk_level:
            object.__setattr__(self, "risk_level", self.risk_metrics.risk_level)

        # Coerce trade_plan to TradePlan instance if dict passed
        if isinstance(self.trade_plan, dict):
            object.__setattr__(self, "trade_plan", TradePlan.from_dict(self.trade_plan))
        elif self.trade_plan is None:
            object.__setattr__(self, "trade_plan", TradePlan())

    def with_liquidity_score(
        self, liquidity_score: float | None, risk_adjusted_score: float | None
    ) -> Self:
        """Return a new immutable Recommendation instance with updated liquidity and risk-adjusted scores."""
        current_rm = (
            self.risk_metrics if isinstance(self.risk_metrics, RiskAssessment) else RiskAssessment()
        )
        updated_rm = replace(current_rm, liquidity_score=liquidity_score)
        return replace(
            self,
            risk_metrics=updated_rm,
            risk_adjusted_score=risk_adjusted_score,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert Recommendation contract to dictionary representation matching schema."""
        rm_dict = (
            self.risk_metrics.to_metrics_dict()
            if isinstance(self.risk_metrics, RiskAssessment)
            else (self.risk_metrics or {})
        )
        tp_dict = (
            self.trade_plan.to_dict()
            if isinstance(self.trade_plan, TradePlan)
            else (self.trade_plan or {})
        )

        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "exchange": self.exchange,
            "sector": self.sector,
            "action": self.action,
            "model_version": self.model_version,
            "data_quality": self.data_quality,
            "data_quality_issues": list(self.data_quality_issues),
            "data_as_of": self.data_as_of,
            "data_source": self.data_source,
            "signal_score": self.signal_score,
            "risk_adjusted_score": self.risk_adjusted_score,
            "score_components": dict(self.score_components) if self.score_components else {},
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "expected_return": dict(self.expected_return) if self.expected_return else {},
            "risk_metrics": rm_dict,
            "trade_plan": tp_dict,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "invalidation": list(self.invalidation),
            "divergence": dict(self.divergence) if self.divergence else {},
        }

    # Dict-like subscripting and methods for backward compatibility
    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def keys(self):
        return self.to_dict().keys()

    def items(self):
        return self.to_dict().items()

    def values(self):
        return self.to_dict().values()

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()

    def __iter__(self):
        return iter(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Construct Recommendation contract from dictionary representation."""
        if not isinstance(data, dict):
            raise TypeError(f"Input data must be a dict, got {type(data).__name__}")
        return cls(
            symbol=data.get("symbol", ""),
            company_name=data.get("company_name") or data.get("companyName", ""),
            exchange=data.get("exchange", "HOSE"),
            sector=data.get("sector", ""),
            action=data.get("action", "AVOID"),
            model_version=data.get("model_version", "2.0"),
            data_quality=data.get("data_quality", "INSUFFICIENT"),
            data_quality_issues=tuple(data.get("data_quality_issues", [])),
            data_as_of=data.get("data_as_of"),
            data_source=data.get("data_source"),
            signal_score=data.get("signal_score"),
            risk_adjusted_score=data.get("risk_adjusted_score"),
            score_components=data.get("score_components"),
            confidence=data.get("confidence", 0.10),
            risk_level=data.get("risk_level"),
            expected_return=data.get("expected_return"),
            risk_metrics=data.get("risk_metrics"),
            trade_plan=data.get("trade_plan"),
            reasons=tuple(data.get("reasons", [])),
            warnings=tuple(data.get("warnings", [])),
            invalidation=tuple(data.get("invalidation", [])),
            divergence=data.get("divergence"),
        )
