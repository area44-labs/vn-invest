"""Domain contract for Risk Assessment metrics and risk levels."""

import math
from dataclasses import dataclass
from typing import Any, Self

VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}


def _validate_float_or_none(value: Any, name: str) -> float | None:
    """Validate that value can be float or None, and is non-NaN and non-Inf."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"Field '{name}' must be numeric or None, got bool")
    try:
        f = float(value)
    except (ValueError, TypeError) as err:
        raise TypeError(
            f"Field '{name}' must be numeric or None, got {type(value).__name__}"
        ) from err
    if math.isnan(f) or math.isinf(f):
        raise ValueError(f"Field '{name}' cannot be NaN or Inf, got {f}")
    return f


@dataclass(frozen=True)
class RiskAssessment:
    """Immutable domain representation of stock risk metrics and risk classification.

    Validates liquidity scores (0-100) and risk levels {"LOW", "MEDIUM", "HIGH", None}.
    """

    var_t25: float | None = None
    es_t25: float | None = None
    volatility_60d: float | None = None
    max_drawdown: float | None = None
    liquidity_score: float | None = None
    avg_value_20d: float | None = None
    risk_level: str | None = None

    def __post_init__(self) -> None:
        var_v = _validate_float_or_none(self.var_t25, "var_t25")
        es_v = _validate_float_or_none(self.es_t25, "es_t25")
        vol_v = _validate_float_or_none(self.volatility_60d, "volatility_60d")
        mdd_v = _validate_float_or_none(self.max_drawdown, "max_drawdown")
        liq_v = _validate_float_or_none(self.liquidity_score, "liquidity_score")
        avg_v = _validate_float_or_none(self.avg_value_20d, "avg_value_20d")

        if liq_v is not None and (liq_v < 0.0 or liq_v > 100.0):
            raise ValueError(f"Field 'liquidity_score' must be between 0.0 and 100.0, got {liq_v}")

        rl = self.risk_level
        if rl is not None:
            if not isinstance(rl, str):
                raise TypeError(
                    f"Field 'risk_level' must be a string or None, got {type(rl).__name__}"
                )
            rl_u = rl.strip().upper()
            if rl_u not in VALID_RISK_LEVELS:
                raise ValueError(
                    f"Invalid risk_level '{rl}'. Must be one of {sorted(VALID_RISK_LEVELS)} or None"
                )
            object.__setattr__(self, "risk_level", rl_u)

        object.__setattr__(self, "var_t25", var_v)
        object.__setattr__(self, "es_t25", es_v)
        object.__setattr__(self, "volatility_60d", vol_v)
        object.__setattr__(self, "max_drawdown", mdd_v)
        object.__setattr__(self, "liquidity_score", liq_v)
        object.__setattr__(self, "avg_value_20d", avg_v)

    def to_metrics_dict(self) -> dict[str, Any]:
        """Convert RiskAssessment metrics fields to dictionary matching schema 'risk_metrics' object.

        Preserves exact legacy JSON output semantics: omits 'avg_value_20d' when None.
        """
        res: dict[str, Any] = {
            "var_t25": self.var_t25,
            "es_t25": self.es_t25,
            "volatility_60d": self.volatility_60d,
            "max_drawdown": self.max_drawdown,
            "liquidity_score": self.liquidity_score,
        }
        if self.avg_value_20d is not None:
            res["avg_value_20d"] = self.avg_value_20d
        return res

    def to_dict(self) -> dict[str, Any]:
        """Convert RiskAssessment contract to full dictionary representation."""
        res = self.to_metrics_dict()
        res["risk_level"] = self.risk_level
        return res

    @classmethod
    def from_dict(cls, data: dict[str, Any], risk_level: str | None = None) -> Self:
        """Construct RiskAssessment contract from dictionary representation."""
        if not isinstance(data, dict):
            raise TypeError(f"Input data must be a dict, got {type(data).__name__}")
        rl = risk_level if risk_level is not None else data.get("risk_level")
        return cls(
            var_t25=data.get("var_t25"),
            es_t25=data.get("es_t25"),
            volatility_60d=data.get("volatility_60d"),
            max_drawdown=data.get("max_drawdown"),
            liquidity_score=data.get("liquidity_score"),
            avg_value_20d=data.get("avg_value_20d"),
            risk_level=rl,
        )
