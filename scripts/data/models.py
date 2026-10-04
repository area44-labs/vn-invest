"""Canonical market data models for VN Invest data boundary.

Defines the authoritative canonical market data model and metadata representations.
Canonical models are strictly decoupled from external data providers and forbid
provider-specific attributes or raw provider responses.
"""

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Self

import pandas as pd

from scripts.domain.data_quality import DataQuality
from scripts.domain.ohlcv import OHLCVData

CANONICAL_OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FORBIDDEN_PROVIDER_FIELDS: set[str] = {
    "vnstock",
    "quote",
    "kbs",
    "msn",
    "ticker",
    "board",
    "provider_raw",
    "raw_response",
    "source_provider",
    "provider_data",
    "provider_payload",
}


def _validate_date_string(date_str: str | None, field_name: str) -> str | None:
    """Validate YYYY-MM-DD date string or return None if None."""
    if date_str is None:
        return None
    if not isinstance(date_str, str):
        raise TypeError(f"Field '{field_name}' must be a string, got {type(date_str).__name__}")
    s = date_str.strip()
    if not s:
        return None
    if not DATE_REGEX.match(s):
        raise ValueError(f"Field '{field_name}' must be formatted as YYYY-MM-DD, got '{date_str}'")
    return s


@dataclass(frozen=True)
class CanonicalMarketData:
    """Immutable canonical representation of market OHLCV data and data_as_of metadata.

    Authoritative location for market data date ('data_as_of') and clean OHLCV records.
    Strictly forbids provider-specific attributes or raw provider payloads.
    """

    symbol: str
    records: tuple[OHLCVData, ...] = ()
    data_as_of: str | None = None
    source_tag: str | None = None
    data_quality: DataQuality | None = None
    df: pd.DataFrame | None = field(default=None, repr=False, compare=False)

    FORBIDDEN_ATTRS: ClassVar[set[str]] = FORBIDDEN_PROVIDER_FIELDS

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("Field 'symbol' must be a non-empty string")

        sym_clean = self.symbol.strip().upper()
        object.__setattr__(self, "symbol", sym_clean)

        validated_as_of = _validate_date_string(self.data_as_of, "data_as_of")
        object.__setattr__(self, "data_as_of", validated_as_of)

        if isinstance(self.records, (list, set)):
            object.__setattr__(self, "records", tuple(self.records))
        elif not isinstance(self.records, tuple):
            raise TypeError(
                f"Field 'records' must be a tuple or list of OHLCVData, got {type(self.records).__name__}"
            )

        for idx, rec in enumerate(self.records):
            if not isinstance(rec, OHLCVData):
                raise TypeError(
                    f"Record at index {idx} must be an OHLCVData instance, got {type(rec).__name__}"
                )

        if self.data_quality is not None and not isinstance(self.data_quality, DataQuality):
            raise TypeError(
                f"Field 'data_quality' must be a DataQuality instance or None, got {type(self.data_quality).__name__}"
            )

        # Check for provider-specific attributes
        for forbidden in self.FORBIDDEN_ATTRS:
            if hasattr(self, forbidden):
                raise ValueError(
                    f"CanonicalMarketData forbids provider-specific attribute '{forbidden}'"
                )

    def to_df(self) -> pd.DataFrame:
        """Convert canonical market records into a pandas DataFrame."""
        if self.df is not None and isinstance(self.df, pd.DataFrame):
            return self.df.copy()

        if not self.records:
            return pd.DataFrame(columns=CANONICAL_OHLCV_COLUMNS)

        records_dicts = [rec.to_dict() for rec in self.records]
        df = pd.DataFrame(records_dicts)
        return df[CANONICAL_OHLCV_COLUMNS]

    @classmethod
    def from_df(
        cls,
        symbol: str,
        df: pd.DataFrame | None,
        data_as_of: str | None = None,
        source_tag: str | None = None,
        data_quality: DataQuality | None = None,
    ) -> Self:
        """Construct CanonicalMarketData from a canonical pandas DataFrame."""
        if df is None or df.empty:
            return cls(
                symbol=symbol,
                records=(),
                data_as_of=data_as_of,
                source_tag=source_tag,
                data_quality=data_quality,
                df=pd.DataFrame(columns=CANONICAL_OHLCV_COLUMNS) if df is not None else None,
            )

        # Determine date column ('date' or 'time')
        cols_lower = [str(c).lower() for c in df.columns]
        col_map = {str(c).lower(): c for c in df.columns}

        date_col = None
        for candidate in ["date", "time"]:
            if candidate in cols_lower:
                date_col = col_map[candidate]
                break

        if not date_col:
            raise ValueError("DataFrame missing date/time column for canonical conversion")

        missing_cols = [
            c for c in ["open", "high", "low", "close", "volume"] if c not in cols_lower
        ]
        if missing_cols:
            return cls(
                symbol=symbol,
                records=(),
                data_as_of=data_as_of,
                source_tag="PROVIDER_FAILURE",
                data_quality=data_quality,
                df=df,
            )

        records = []
        has_record_error = False
        for _, row in df.iterrows():
            d_str = str(row[date_col]).split(" ")[0].split("T")[0]
            open_v = row[col_map["open"]] if "open" in col_map else 0.0
            high_v = row[col_map["high"]] if "high" in col_map else 0.0
            low_v = row[col_map["low"]] if "low" in col_map else 0.0
            close_v = row[col_map["close"]] if "close" in col_map else 0.0
            vol_v = row[col_map["volume"]] if "volume" in col_map else 0.0

            try:
                rec = OHLCVData(
                    date=d_str,
                    open=open_v,
                    high=high_v,
                    low=low_v,
                    close=close_v,
                    volume=vol_v,
                )
                records.append(rec)
            except ValueError, TypeError:
                has_record_error = True
                break

        if has_record_error:
            return cls(
                symbol=symbol,
                records=(),
                data_as_of=data_as_of,
                source_tag=source_tag or "EXPLICITLY_INVALID",
                data_quality=data_quality,
                df=df,
            )

        # Authoritative data_as_of from max record date if not explicitly supplied
        derived_as_of = data_as_of
        if not derived_as_of and records:
            derived_as_of = max(rec.date for rec in records)

        df_canonical = df.copy()
        # Rename date column to 'date' if named 'time'
        if date_col and date_col.lower() == "time" and "date" not in df_canonical.columns:
            df_canonical = df_canonical.rename(columns={date_col: "date"})

        return cls(
            symbol=symbol,
            records=tuple(records),
            data_as_of=derived_as_of,
            source_tag=source_tag,
            data_quality=data_quality,
            df=df_canonical,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert CanonicalMarketData to dictionary representation without provider fields."""
        return {
            "symbol": self.symbol,
            "records": [rec.to_dict() for rec in self.records],
            "data_as_of": self.data_as_of,
            "source_tag": self.source_tag,
            "data_quality": self.data_quality.to_dict() if self.data_quality else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Construct CanonicalMarketData from dictionary representation.

        Fails closed if data contains provider-specific fields.
        """
        if not isinstance(data, dict):
            raise TypeError(f"Input data must be a dict, got {type(data).__name__}")

        # Reject forbidden provider fields
        found_forbidden = [f for f in FORBIDDEN_PROVIDER_FIELDS if f in data]
        if found_forbidden:
            raise ValueError(
                f"Cannot construct CanonicalMarketData: forbidden provider keys present: {found_forbidden}"
            )

        symbol = data.get("symbol", "")
        records_raw = data.get("records", [])
        records = tuple(OHLCVData.from_dict(r) for r in records_raw)

        dq_raw = data.get("data_quality")
        dq = DataQuality.from_dict(dq_raw) if isinstance(dq_raw, dict) else None

        return cls(
            symbol=symbol,
            records=records,
            data_as_of=data.get("data_as_of"),
            source_tag=data.get("source_tag"),
            data_quality=dq,
        )
