"""Market data normalization boundary for VN Invest data layer.

Transforms raw provider response payloads into clean CanonicalMarketData instances.
Enforces price unit normalization, standardizes column schemas, strips provider-specific
metadata, and establishes the authoritative 'data_as_of' location.
"""

import logging
from typing import ClassVar

import pandas as pd

from scripts.data.acquisition import RawMarketDataPayload
from scripts.data.models import CanonicalMarketData

logger = logging.getLogger(__name__)

INDEX_SYMBOLS: set[str] = {"VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX", "VN30INDEX"}
CANONICAL_COLUMNS: list[str] = ["date", "open", "high", "low", "close", "volume"]

# Explicit internal unit contract constants
PRICE_UNIT = "VND/share"
VOLUME_UNIT = "shares"
TRADING_VALUE_UNIT = "VND"
AVG_TRADING_VALUE_UNIT = "billion_VND"

# Source unit contracts for upstream data providers:
SOURCE_PRICE_UNIT_VNSTOCK = "thousand_VND/share"
SOURCE_VOLUME_UNIT_VNSTOCK = "shares"
VALID_PRICE_UNITS = {"VND/share", "thousand_VND/share"}
VALID_VOLUME_UNITS = {"shares", "thousand_shares"}


def normalize_symbol(symbol: str) -> str:
    """Normalize Vietnam stock symbol format (e.g. 'fpt' -> 'FPT')."""
    if not symbol:
        return ""
    return str(symbol).strip().upper()


def normalize_ohlcv_units(
    df: pd.DataFrame,
    source_price_unit: str = SOURCE_PRICE_UNIT_VNSTOCK,
    source_volume_unit: str = SOURCE_VOLUME_UNIT_VNSTOCK,
) -> pd.DataFrame:
    """Normalize OHLCV DataFrame from declared source units to canonical internal units."""
    if source_price_unit not in VALID_PRICE_UNITS:
        raise ValueError(
            f"Unsupported price unit '{source_price_unit}'. Must be one of {sorted(VALID_PRICE_UNITS)}"
        )
    if source_volume_unit not in VALID_VOLUME_UNITS:
        raise ValueError(
            f"Unsupported volume unit '{source_volume_unit}'. Must be one of {sorted(VALID_VOLUME_UNITS)}"
        )

    if df is None or df.empty:
        return df

    df_norm = df.copy()

    if source_price_unit == "thousand_VND/share":
        price_cols = [c for c in ["open", "high", "low", "close", "vwap"] if c in df_norm.columns]
        for col in price_cols:
            df_norm[col] = df_norm[col] * 1000.0

    if source_volume_unit == "thousand_shares" and "volume" in df_norm.columns:
        df_norm["volume"] = df_norm["volume"] * 1000.0

    return df_norm


class MarketDataNormalizer:
    """Normalizer converting raw provider market data into CanonicalMarketData."""

    INDEX_SYMBOLS: ClassVar[set[str]] = INDEX_SYMBOLS

    def normalize(
        self,
        payload: RawMarketDataPayload,
        explicit_data_as_of: str | None = None,
        source_price_unit: str = "thousand_VND/share",
    ) -> CanonicalMarketData:
        """Normalize raw market payload into canonical market data model."""
        sym = payload.symbol.strip().upper()
        raw_df = payload.raw_df

        if raw_df is None or raw_df.empty:
            src_tag = (
                payload.source_tag
                if payload.source_tag
                in ("INVALID_SYMBOL", "EXPLICITLY_INVALID", "PROVIDER_FAILURE")
                else (payload.failure_type or "PROVIDER_FAILURE")
            )
            return CanonicalMarketData(
                symbol=sym,
                records=(),
                data_as_of=explicit_data_as_of,
                source_tag=src_tag,
            )

        df_norm = raw_df.copy()
        # Lowercase column names
        df_norm.columns = [str(c).lower().strip() for c in df_norm.columns]

        # Identify date column ('date' or 'time')
        date_col = None
        for candidate in ["date", "time"]:
            if candidate in df_norm.columns:
                date_col = candidate
                break

        if not date_col:
            logger.warning("Normalizer: missing date/time column in raw DataFrame for %s", sym)
            return CanonicalMarketData(
                symbol=sym,
                records=(),
                data_as_of=explicit_data_as_of,
                source_tag="PROVIDER_FAILURE",
            )

        # Standardize date column name to 'date'
        if date_col != "date":
            df_norm = df_norm.rename(columns={date_col: "date"})

        # Standardize date string values (strip time components)
        df_norm["date"] = df_norm["date"].astype(str).str.split(" ").str[0].str.split("T").str[0]

        # Convert numeric columns
        numeric_cols = [
            c for c in ["open", "high", "low", "close", "volume", "vwap"] if c in df_norm.columns
        ]
        for col in numeric_cols:
            df_norm[col] = pd.to_numeric(df_norm[col], errors="coerce")

        # Price unit normalization (stocks in thousand_VND/share -> VND/share)
        if source_price_unit == "thousand_VND/share" and sym not in self.INDEX_SYMBOLS:
            price_cols = [
                c for c in ["open", "high", "low", "close", "vwap"] if c in df_norm.columns
            ]
            for col in price_cols:
                # Check if prices appear to be in thousand VND (< 5000 average) to prevent double scaling
                mean_p = df_norm[col].dropna().mean()
                if pd.notna(mean_p) and mean_p < 5000.0:
                    df_norm[col] = df_norm[col] * 1000.0

        # Filter columns to only canonical columns (and vwap if present)
        available_cols = [c for c in CANONICAL_COLUMNS if c in df_norm.columns]
        if "vwap" in df_norm.columns:
            available_cols.append("vwap")
        df_canonical = df_norm[available_cols].copy()

        # Authoritative data_as_of determination
        derived_as_of = explicit_data_as_of
        if not derived_as_of and "date" in df_canonical.columns and not df_canonical["date"].empty:
            valid_dates = df_canonical["date"].dropna().astype(str)
            if not valid_dates.empty:
                derived_as_of = valid_dates.max()

        return CanonicalMarketData.from_df(
            symbol=sym,
            df=df_canonical,
            data_as_of=derived_as_of,
            source_tag=payload.source_tag,
        )


def normalize_raw_market_data(
    payload: RawMarketDataPayload,
    explicit_data_as_of: str | None = None,
    source_price_unit: str = "thousand_VND/share",
) -> CanonicalMarketData:
    """Convenience entry point for market data normalization."""
    normalizer = MarketDataNormalizer()
    return normalizer.normalize(
        payload=payload,
        explicit_data_as_of=explicit_data_as_of,
        source_price_unit=source_price_unit,
    )


__all__ = [
    "AVG_TRADING_VALUE_UNIT",
    "INDEX_SYMBOLS",
    "PRICE_UNIT",
    "SOURCE_PRICE_UNIT_VNSTOCK",
    "SOURCE_VOLUME_UNIT_VNSTOCK",
    "TRADING_VALUE_UNIT",
    "VALID_PRICE_UNITS",
    "VALID_VOLUME_UNITS",
    "VOLUME_UNIT",
    "MarketDataNormalizer",
    "normalize_ohlcv_units",
    "normalize_raw_market_data",
    "normalize_symbol",
]
