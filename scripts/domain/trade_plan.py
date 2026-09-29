"""Domain contract for Trade Plan bounds and sizing."""

import math
from dataclasses import dataclass
from typing import Any, Self


def _validate_float_or_none(val: Any, name: str) -> float | None:
    """Validate that val can be float or None, and is non-NaN and non-Inf."""
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
    return f


def _validate_price_or_none(val: Any, name: str) -> float | None:
    """Validate that val can be float or None, and is non-NaN, non-Inf, and non-negative."""
    f = _validate_float_or_none(val, name)
    if f is not None and f < 0.0:
        raise ValueError(f"Field '{name}' must be non-negative (>= 0.0), got {f}")
    return f


@dataclass(frozen=True)
class TradePlan:
    """Immutable domain representation of a stock trade plan.

    Validates price bounds, risk-reward ratios, and position sizing percentages.
    """

    current_price: float | None = None
    entry_low: float | None = None
    entry_high: float | None = None
    stop_loss: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    risk_reward: float | None = None
    position_percent: float = 0.0

    def __post_init__(self) -> None:
        cp = _validate_price_or_none(self.current_price, "current_price")
        el = _validate_price_or_none(self.entry_low, "entry_low")
        eh = _validate_price_or_none(self.entry_high, "entry_high")
        sl = _validate_price_or_none(self.stop_loss, "stop_loss")
        t1 = _validate_price_or_none(self.tp1, "tp1")
        t2 = _validate_price_or_none(self.tp2, "tp2")
        rr = _validate_float_or_none(self.risk_reward, "risk_reward")

        pos = _validate_float_or_none(self.position_percent, "position_percent")
        if pos is None:
            pos = 0.0

        if pos < 0.0 or pos > 100.0:
            raise ValueError(f"Field 'position_percent' must be between 0.0 and 100.0, got {pos}")

        object.__setattr__(self, "current_price", cp)
        object.__setattr__(self, "entry_low", el)
        object.__setattr__(self, "entry_high", eh)
        object.__setattr__(self, "stop_loss", sl)
        object.__setattr__(self, "tp1", t1)
        object.__setattr__(self, "tp2", t2)
        object.__setattr__(self, "risk_reward", rr)
        object.__setattr__(self, "position_percent", pos)

    def to_dict(self) -> dict[str, Any]:
        """Convert TradePlan contract to dictionary representation matching schema."""
        return {
            "current_price": self.current_price,
            "entry_low": self.entry_low,
            "entry_high": self.entry_high,
            "stop_loss": self.stop_loss,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "risk_reward": self.risk_reward,
            "position_percent": self.position_percent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Construct TradePlan contract from dictionary representation."""
        if not isinstance(data, dict):
            raise TypeError(f"Input data must be a dict, got {type(data).__name__}")
        return cls(
            current_price=data.get("current_price"),
            entry_low=data.get("entry_low"),
            entry_high=data.get("entry_high"),
            stop_loss=data.get("stop_loss"),
            tp1=data.get("tp1"),
            tp2=data.get("tp2"),
            risk_reward=data.get("risk_reward"),
            position_percent=data.get("position_percent", 0.0),
        )
