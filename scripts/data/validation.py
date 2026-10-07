"""Market data validation boundary for VN Invest data layer.

Validates canonical market data against required field schemas, price/volume OHLCV invariants,
and temporal consistency contracts. Invalid canonical market data fails closed.
"""

import logging
from datetime import UTC, datetime
from typing import ClassVar

import numpy as np
import pandas as pd

from scripts.data.models import CanonicalMarketData
from scripts.domain.data_quality import DataQuality

logger = logging.getLogger(__name__)


class CanonicalDataValidationError(ValueError):
    """Exception raised when canonical market data fails validation."""


REQUIRED_OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]

# Temporal Data Consistency & Staleness Threshold Parameters
MAX_STOCK_STALENESS_DAYS = 7
MAX_BENCHMARK_FUTURE_DAYS = 0


class CanonicalMarketValidator:
    """Validator inspecting CanonicalMarketData for invariant & temporal compliance."""

    REQUIRED_COLUMNS: ClassVar[list[str]] = REQUIRED_OHLCV_COLUMNS

    def validate(
        self,
        canonical_data: CanonicalMarketData,
        reference_date: str | None = None,
        max_staleness_days: int = MAX_STOCK_STALENESS_DAYS,
    ) -> CanonicalMarketData:
        """Validate canonical market data. Returns validated CanonicalMarketData with DataQuality attached.

        Fails closed on corrupt, malformed, or temporally inconsistent data.
        """
        sym = canonical_data.symbol
        issues: list[str] = []

        df = canonical_data.to_df()

        if df is None or df.empty:
            issues.append("empty_dataset")
            src_tag = (
                canonical_data.source_tag
                if canonical_data.source_tag in ("INVALID_SYMBOL", "EXPLICITLY_INVALID")
                else "PROVIDER_FAILURE"
            )
            dq = DataQuality(
                status="INSUFFICIENT",
                issues=tuple(issues),
                valid_row_count=0,
                latest_date=canonical_data.data_as_of,
                data_as_of=canonical_data.data_as_of,
                data_source=src_tag,
            )
            return CanonicalMarketData(
                symbol=sym,
                records=(),
                data_as_of=canonical_data.data_as_of,
                source_tag=src_tag,
                data_quality=dq,
            )

        cols_lower = [str(c).lower() for c in df.columns]

        missing_cols = [c for c in self.REQUIRED_COLUMNS if c not in cols_lower]
        if missing_cols:
            issues.append("missing_required_columns")

        # Date column check
        date_col = "date" if "date" in df.columns else ("time" if "time" in df.columns else None)
        if not date_col:
            issues.append("missing_date_column")
            dates_parsed = pd.Series(dtype="datetime64[ns]")
        else:
            dates_parsed = pd.to_datetime(df[date_col], errors="coerce")
            if dates_parsed.isna().any():
                issues.append("invalid_date_values")

            if dates_parsed.duplicated().any():
                issues.append("duplicate_dates")

            if not dates_parsed.is_monotonic_increasing:
                issues.append("unsorted_dates")

        # Numeric column checks
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                series = pd.to_numeric(df[col], errors="coerce")
                if series.isna().any():
                    issues.append(f"nan_values_in_{col}")
                arr = series.dropna().to_numpy()
                if np.isinf(arr).any():
                    issues.append(f"inf_values_in_{col}")

        # Invariant checks on valid numeric data
        if all(col in df.columns for col in ["open", "high", "low", "close", "volume"]):
            open_s = pd.to_numeric(df["open"], errors="coerce")
            high_s = pd.to_numeric(df["high"], errors="coerce")
            low_s = pd.to_numeric(df["low"], errors="coerce")
            close_s = pd.to_numeric(df["close"], errors="coerce")
            vol_s = pd.to_numeric(df["volume"], errors="coerce")

            if (
                (open_s <= 0).any()
                or (high_s <= 0).any()
                or (low_s <= 0).any()
                or (close_s <= 0).any()
            ):
                issues.append("non_positive_prices")

            if (vol_s < 0).any():
                issues.append("negative_volume")

            invalid_ohlc = (
                (high_s < low_s)
                | (open_s > high_s)
                | (open_s < low_s)
                | (close_s > high_s)
                | (close_s < low_s)
            )
            if invalid_ohlc.any():
                issues.append("invalid_ohlc_relationship")

        # Temporal integrity relative to reference_date
        latest_record_date = (
            dates_parsed.max().strftime("%Y-%m-%d")
            if not dates_parsed.empty and not dates_parsed.isna().all()
            else None
        )

        if reference_date and latest_record_date:
            try:
                ref_dt = datetime.strptime(reference_date, "%Y-%m-%d").replace(tzinfo=UTC)
                lat_dt = datetime.strptime(latest_record_date, "%Y-%m-%d").replace(tzinfo=UTC)
                if lat_dt > ref_dt:
                    issues.append(f"future_dated_record: {latest_record_date} > {reference_date}")
                elif (ref_dt - lat_dt).days > max_staleness_days:
                    issues.append(f"stale_data: {latest_record_date} vs {reference_date}")
            except ValueError:
                issues.append("unparseable_reference_date")

        provider_failure_issues = {
            "empty_dataset",
            "missing_required_columns",
            "missing_date_column",
        }
        corruption_issues = {
            "invalid_date_values",
            "duplicate_dates",
            "unsorted_dates",
            "non_positive_prices",
            "negative_volume",
            "invalid_ohlc_relationship",
        }

        has_provider_failure = any(iss in provider_failure_issues for iss in issues)
        has_corruption = any(iss in corruption_issues for iss in issues) or any(
            "future_dated" in iss or "nan_values" in iss or "inf_values" in iss for iss in issues
        )

        if canonical_data.source_tag == "INVALID_SYMBOL":
            source_tag = "INVALID_SYMBOL"
            dq_status = "INSUFFICIENT"
        elif has_provider_failure or canonical_data.source_tag == "PROVIDER_FAILURE":
            source_tag = "PROVIDER_FAILURE"
            dq_status = "INSUFFICIENT"
        elif has_corruption or canonical_data.source_tag == "EXPLICITLY_INVALID":
            source_tag = "EXPLICITLY_INVALID"
            dq_status = "INSUFFICIENT"
        elif len(df) < 20:
            source_tag = "INSUFFICIENT_HISTORICAL_DATA"
            dq_status = "INSUFFICIENT"
            issues.append("insufficient_history")
        else:
            source_tag = canonical_data.source_tag or "REAL_DATA"
            dq_status = "SUFFICIENT"

        dq = DataQuality(
            status=dq_status,
            issues=tuple(issues),
            valid_row_count=len(df)
            if dq_status == "SUFFICIENT" or source_tag == "INSUFFICIENT_HISTORICAL_DATA"
            else 0,
            latest_date=latest_record_date,
            data_as_of=canonical_data.data_as_of or latest_record_date,
            data_source=source_tag,
        )

        is_valid = dq_status == "SUFFICIENT" or source_tag == "INSUFFICIENT_HISTORICAL_DATA"

        return CanonicalMarketData(
            symbol=sym,
            records=canonical_data.records if is_valid else (),
            data_as_of=canonical_data.data_as_of or latest_record_date,
            source_tag=source_tag,
            data_quality=dq,
        )


def validate_canonical_market_data(
    canonical_data: CanonicalMarketData,
    reference_date: str | None = None,
    max_staleness_days: int = MAX_STOCK_STALENESS_DAYS,
) -> CanonicalMarketData:
    """Convenience entry point for canonical market data validation."""
    validator = CanonicalMarketValidator()
    return validator.validate(
        canonical_data=canonical_data,
        reference_date=reference_date,
        max_staleness_days=max_staleness_days,
    )
