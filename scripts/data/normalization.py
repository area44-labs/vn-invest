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
            src_tag = payload.source_tag
            if payload.error:
                err_upper = payload.error.upper()
                if "INVALID_SYMBOL" in err_upper or "INVALID SYMBOL" in err_upper:
                    src_tag = "INVALID_SYMBOL"
                elif "EXPLICITLY_INVALID" in err_upper:
                    src_tag = "EXPLICITLY_INVALID"
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
