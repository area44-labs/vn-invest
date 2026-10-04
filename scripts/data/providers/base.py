"""Base contract for market data providers."""

import abc

import pandas as pd


class AcquisitionError(Exception):
    """Base exception for market data acquisition and provider errors."""

    failure_type: str = "PROVIDER_FAILURE"


class InvalidSymbolError(AcquisitionError):
    """Exception raised when a symbol is invalid or not found by market data provider."""

    failure_type: str = "INVALID_SYMBOL"


class ExplicitlyInvalidDataError(AcquisitionError):
    """Exception raised when provider market data is corrupt or explicitly invalid."""

    failure_type: str = "EXPLICITLY_INVALID"


class MarketDataProvider(abc.ABC):
    """Abstract interface defining external market data provider contract."""

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Return the unique name identifier of the provider."""

    @abc.abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        max_retries: int = 2,
        target_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch raw OHLCV market data for a symbol from provider source."""
