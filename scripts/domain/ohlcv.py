"""Domain contract for OHLCV candlestick market data."""

import math
from dataclasses import dataclass
from typing import Any, Self


def _validate_finite_float(value: Any, field_name: str) -> float:
    """Validate that value can be float and is non-NaN and non-Inf."""
    if value is None or isinstance(value, bool):
        raise TypeError(f"Field '{field_name}' must be a finite float, got {type(value).__name__}")
    try:
        f = float(value)
    except (ValueError, TypeError) as err:
        raise TypeError(
            f"Field '{field_name}' must be numeric, got {type(value).__name__}"
        ) from err
    if math.isnan(f) or math.isinf(f):
        raise ValueError(f"Field '{field_name}' cannot be NaN or Inf, got {f}")
    return f


@dataclass(frozen=True)
class OHLCVData:
    """Immutable domain representation of a single OHLCV candlestick data record.

    Validates canonical price and volume relationships:
    - Price values must be strictly positive (> 0.0).
    - Volume must be non-negative (>= 0.0).
    - High must be >= Low, High >= max(Open, Close), Low <= min(Open, Close).
    """

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if not isinstance(self.date, str) or not self.date.strip():
            raise ValueError("Field 'date' must be a non-empty string")

        val_open = _validate_finite_float(self.open, "open")
        val_high = _validate_finite_float(self.high, "high")
        val_low = _validate_finite_float(self.low, "low")
        val_close = _validate_finite_float(self.close, "close")
        val_vol = _validate_finite_float(self.volume, "volume")

        if val_open <= 0.0 or val_high <= 0.0 or val_low <= 0.0 or val_close <= 0.0:
            raise ValueError(
                f"OHLCV price values must be strictly positive (> 0.0), got open={val_open}, high={val_high}, low={val_low}, close={val_close}"
            )

        if val_vol < 0.0:
            raise ValueError(f"OHLCV volume must be non-negative (>= 0.0), got volume={val_vol}")

        if val_high < val_low:
            raise ValueError(f"Invalid OHLC relationship: high ({val_high}) < low ({val_low})")

        if val_high < val_open or val_high < val_close:
            raise ValueError(
                f"Invalid OHLC relationship: high ({val_high}) must be >= open ({val_open}) and close ({val_close})"
            )

        if val_low > val_open or val_low > val_close:
            raise ValueError(
                f"Invalid OHLC relationship: low ({val_low}) must be <= open ({val_open}) and close ({val_close})"
            )

        # Ensure exact float types stored in dataclass fields
        object.__setattr__(self, "date", self.date.strip())
        object.__setattr__(self, "open", val_open)
        object.__setattr__(self, "high", val_high)
        object.__setattr__(self, "low", val_low)
        object.__setattr__(self, "close", val_close)
        object.__setattr__(self, "volume", val_vol)

    def to_dict(self) -> dict[str, Any]:
        """Convert OHLCVData contract to dictionary representation."""
        return {
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }

    @classmethod
    def from_dict(cls, data_dict: dict[str, Any]) -> Self:
        """Construct OHLCVData contract from dictionary representation."""
        if not isinstance(data_dict, dict):
            raise TypeError(f"Input data must be a dict, got {type(data_dict).__name__}")
        return cls(
            date=data_dict.get("date") or data_dict.get("time") or "",
            open=data_dict.get("open"),
            high=data_dict.get("high"),
            low=data_dict.get("low"),
            close=data_dict.get("close"),
            volume=data_dict.get("volume"),
        )
