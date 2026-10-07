"""Unit tests for validation boundary in scripts/data/validation.py."""

import pytest

import pandas as pd

from scripts.data.models import CanonicalMarketData
from scripts.data.validation import validate_canonical_market_data


@pytest.mark.unit
class TestMarketDataValidationBoundary:
    """Test CanonicalMarketValidator invariant and temporal rules."""

    def test_valid_canonical_data(self):
        df_valid = pd.DataFrame(
            {
                "date": [f"2025-01-{i:02d}" for i in range(1, 25)],
                "open": [100.0] * 24,
                "high": [105.0] * 24,
                "low": [99.0] * 24,
                "close": [102.0] * 24,
                "volume": [1000.0] * 24,
            }
        )
        cmd = CanonicalMarketData.from_df("FPT", df_valid, data_as_of="2025-01-24")

        validated = validate_canonical_market_data(cmd, reference_date="2025-01-24")

        assert validated.data_quality.status == "SUFFICIENT"
        assert validated.source_tag == "REAL_DATA"
        assert validated.data_quality.valid_row_count == 24

    def test_invalid_ohlc_relationship_fails_closed(self):
        df_invalid = pd.DataFrame(
            {
                "date": ["2025-01-02"],
                "open": [100.0],
                "high": [90.0],  # Invalid: high < open
                "low": [99.0],
                "close": [102.0],
                "volume": [1000.0],
            }
        )
        cmd = CanonicalMarketData.from_df("FPT", df_invalid, data_as_of="2025-01-02")

        validated = validate_canonical_market_data(cmd)

        assert validated.data_quality.status == "INSUFFICIENT"
        assert validated.source_tag == "EXPLICITLY_INVALID"
        assert len(validated.records) == 0

    def test_future_dated_record_fails_closed(self):
        df_future = pd.DataFrame(
            {
                "date": ["2025-01-10"],  # record date > reference date (2025-01-05)
                "open": [100.0],
                "high": [105.0],
                "low": [99.0],
                "close": [102.0],
                "volume": [1000.0],
            }
        )
        cmd = CanonicalMarketData.from_df("FPT", df_future, data_as_of="2025-01-10")

        validated = validate_canonical_market_data(cmd, reference_date="2025-01-05")

        assert validated.source_tag == "EXPLICITLY_INVALID"
        assert any("future_dated" in iss for iss in validated.data_quality.issues)
