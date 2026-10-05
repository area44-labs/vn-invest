"""Vnstock market data provider implementation."""

import pandas as pd

from scripts.data.providers.base import (
    AcquisitionError,
    ExplicitlyInvalidDataError,
    MarketDataProvider,
)
from scripts.data_provider import (
    CanonicalOHLCVError,
    ProviderRateLimitError,
    VnstockDataProvider,
)


class VnstockMarketProvider(MarketDataProvider):
    """Provider implementation adapting external VnstockDataProvider."""

    def __init__(self, provider_instance: VnstockDataProvider | None = None):
        self._provider = (
            provider_instance if provider_instance is not None else VnstockDataProvider()
        )

    @property
    def provider_name(self) -> str:
        return "vnstock"

    @classmethod
    def reset_global_call_history(cls) -> None:
        """Reset process-wide provider call history and rate-limit state."""
        VnstockDataProvider.reset_global_call_history()

    def fetch_ohlcv(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        max_retries: int = 2,
        target_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch raw OHLCV market data from VnstockDataProvider and map provider errors to structured acquisition errors."""
        try:
            return self._provider.fetch_ohlcv(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                max_retries=max_retries,
                target_date=target_date,
            )
        except ProviderRateLimitError:
            raise
        except AcquisitionError:
            raise
        except CanonicalOHLCVError as exc:
            raise ExplicitlyInvalidDataError(
                f"Provider market data for symbol '{symbol}' is corrupt or explicitly invalid: {exc}"
            ) from exc
