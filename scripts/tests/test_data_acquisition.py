"""Unit tests for acquisition boundary in scripts/data/acquisition.py."""

import pytest
from unittest.mock import MagicMock, patch

import pandas as pd

from scripts.data.acquisition import (
    ExplicitlyInvalidDataError,
    InvalidSymbolError,
    MarketDataAcquirer,
    RawMarketDataPayload,
    acquire_raw_market_data,
)
from scripts.data.providers.base import MarketDataProvider
from scripts.data_provider import ProviderRateLimitError


class DummyFakeProvider(MarketDataProvider):
    """Fake provider for acquisition testing without vnstock."""

    @property
    def provider_name(self) -> str:
        return "custom_fake"

    def fetch_ohlcv(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        max_retries: int = 2,
        target_date: str | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "time": ["2025-01-02"],
                "open": [100.0],
                "high": [105.0],
                "low": [99.0],
                "close": [102.0],
                "volume": [1000.0],
            }
        )


@pytest.mark.unit
class TestMarketDataAcquisitionBoundary:
    """Test MarketDataAcquirer and acquisition boundary contracts."""

    def test_successful_raw_data_acquisition(self):
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock_provider"
        mock_provider.fetch_ohlcv.return_value = pd.DataFrame(
            {
                "time": ["2025-01-02", "2025-01-03"],
                "open": [100.0, 102.0],
                "high": [105.0, 107.0],
                "low": [99.0, 101.0],
                "close": [102.0, 106.0],
                "volume": [1000.0, 1500.0],
            }
        )

        payload = acquire_raw_market_data("FPT", provider=mock_provider)

        assert isinstance(payload, RawMarketDataPayload)
        assert payload.symbol == "FPT"
        assert payload.source_tag == "REAL_DATA"
        assert payload.provider_name == "mock_provider"
        assert payload.error is None
        assert not payload.raw_df.empty

    def test_acquisition_with_custom_fake_provider(self):
        provider = DummyFakeProvider()
        payload = acquire_raw_market_data("VCB", provider=provider)

        assert payload.symbol == "VCB"
        assert payload.provider_name == "custom_fake"
        assert payload.source_tag == "REAL_DATA"
        assert not payload.raw_df.empty

    def test_acquisition_failure_tagging(self):
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock_provider"
        mock_provider.fetch_ohlcv.side_effect = RuntimeError("Provider offline")

        payload = acquire_raw_market_data("FPT", provider=mock_provider)

        assert payload.symbol == "FPT"
        assert payload.source_tag == "PROVIDER_FAILURE"
        assert payload.failure_type == "PROVIDER_FAILURE"
        assert payload.raw_df.empty
        assert "Provider offline" in payload.error

    def test_client_auth_and_unstructured_exceptions_classified_as_provider_failure(self):
        """Client auth errors and generic exceptions evaluate as PROVIDER_FAILURE (not INVALID_SYMBOL)."""
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock_provider"

        auth_err = Exception("HTTP 401 Unauthorized")
        res_mock = MagicMock()
        res_mock.status_code = 401
        auth_err.response = res_mock

        mock_provider.fetch_ohlcv.side_effect = auth_err
        payload = acquire_raw_market_data("FPT", provider=mock_provider)

        assert payload.failure_type == "PROVIDER_FAILURE"
        assert payload.source_tag == "PROVIDER_FAILURE"

    def test_unstructured_exception_message_does_not_infer_invalid_symbol(self):
        """Regression test: An exception containing string 'INVALID_SYMBOL' without structured failure_type is classified as PROVIDER_FAILURE."""
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock_provider"
        mock_provider.fetch_ohlcv.side_effect = RuntimeError(
            "Fetch failed with INVALID_SYMBOL error message"
        )

        payload = acquire_raw_market_data("FPT", provider=mock_provider)

        assert payload.failure_type == "PROVIDER_FAILURE"
        assert payload.source_tag == "PROVIDER_FAILURE"

    def test_unstructured_exception_message_does_not_infer_explicitly_invalid(self):
        """Regression test: An exception containing string 'EXPLICITLY_INVALID' without structured failure_type is classified as PROVIDER_FAILURE."""
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock_provider"
        mock_provider.fetch_ohlcv.side_effect = RuntimeError(
            "Fetch failed with EXPLICITLY_INVALID error message"
        )

        payload = acquire_raw_market_data("FPT", provider=mock_provider)

        assert payload.failure_type == "PROVIDER_FAILURE"
        assert payload.source_tag == "PROVIDER_FAILURE"

    def test_structured_exceptions_classified_correctly(self):
        """Structured InvalidSymbolError and ExplicitlyInvalidDataError are classified accurately."""
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock_provider"

        mock_provider.fetch_ohlcv.side_effect = InvalidSymbolError("Symbol ABC not found")
        payload_invalid_sym = acquire_raw_market_data("ABC", provider=mock_provider)
        assert payload_invalid_sym.failure_type == "INVALID_SYMBOL"
        assert payload_invalid_sym.source_tag == "INVALID_SYMBOL"

        mock_provider.fetch_ohlcv.side_effect = ExplicitlyInvalidDataError("Corrupted payload")
        payload_exp_invalid = acquire_raw_market_data("XYZ", provider=mock_provider)
        assert payload_exp_invalid.failure_type == "EXPLICITLY_INVALID"
        assert payload_exp_invalid.source_tag == "EXPLICITLY_INVALID"

    @patch("scripts.data.acquisition.can_recover_rate_limit", return_value=False)
    def test_rate_limit_exceeded_raises(self, _mock_can_rec):
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock_provider"
        mock_provider.fetch_ohlcv.side_effect = ProviderRateLimitError(
            "Rate limit exceeded", cooldown_seconds=5
        )

        acquirer = MarketDataAcquirer(provider=mock_provider)
        with pytest.raises(ProviderRateLimitError):
            acquirer.acquire("FPT", max_rate_limit_retries=0)
