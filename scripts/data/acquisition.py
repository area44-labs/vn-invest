"""Market data acquisition boundary for VN Invest data layer.

Responsible for retrieving raw market data from external market providers.
Encapsulates all provider interaction, retry, circuit-breaker, and rate-limiting logic
within the acquisition layer without inspecting exception strings or classifying data quality.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pandas as pd

from scripts.data.providers import (
    AcquisitionError,
    ExplicitlyInvalidDataError,
    InvalidSymbolError,
    MarketDataProvider,
    VnstockMarketProvider,
)
from scripts.data_provider import (
    ProviderRateLimitError,
    can_recover_rate_limit,
    increment_rate_limit_recovery_count,
    reset_circuit_breaker,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawMarketDataPayload:
    """Container for raw market data acquired from external providers before normalization."""

    symbol: str
    raw_df: pd.DataFrame | None = None
    provider_name: str = "vnstock"
    source_tag: str = "REAL_DATA"
    failure_type: str | None = None
    warnings: tuple[str, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.warnings, (list, set)):
            object.__setattr__(self, "warnings", tuple(str(w) for w in self.warnings))


class MarketDataAcquirer:
    """Acquirer for raw market data.

    Manages provider interaction, rate-limit recovery loops, and raw payload capture.
    Strictly decoupled from data-quality classification logic.
    """

    def __init__(self, provider: MarketDataProvider | None = None):
        self._provider = provider

    def _get_provider(self) -> MarketDataProvider:
        return self._provider if self._provider is not None else VnstockMarketProvider()

    def acquire(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        max_retries: int = 2,
        throttle_delay: float = 0.0,
        max_rate_limit_retries: int = 3,
        target_date: str | None = None,
    ) -> RawMarketDataPayload:
        """Acquire raw market data for a symbol across provider boundaries."""
        sym = symbol.strip().upper()
        if not start_date or not end_date:
            now_dt = datetime.now(UTC)
            end_date = now_dt.strftime("%Y-%m-%d")
            start_date = (now_dt - timedelta(days=365)).strftime("%Y-%m-%d")

        provider = self._get_provider()
        provider_name = provider.provider_name

        for rate_limit_attempt in range(max_rate_limit_retries + 1):
            if throttle_delay > 0:
                time.sleep(throttle_delay)

            try:
                df_out = provider.fetch_ohlcv(
                    symbol=sym,
                    start_date=start_date,
                    end_date=end_date,
                    max_retries=max_retries,
                    target_date=target_date,
                )
                return RawMarketDataPayload(
                    symbol=sym,
                    raw_df=df_out,
                    provider_name=provider_name,
                    source_tag="REAL_DATA",
                )
            except ProviderRateLimitError as exc:
                if can_recover_rate_limit() and rate_limit_attempt < max_rate_limit_retries:
                    cooldown = exc.cooldown_seconds if exc.cooldown_seconds is not None else 30
                    increment_rate_limit_recovery_count()
                    logger.warning(
                        "Provider rate limit encountered for '%s'. Waiting %d seconds (attempt %d/%d)...",
                        sym,
                        cooldown,
                        rate_limit_attempt + 1,
                        max_rate_limit_retries,
                    )
                    time.sleep(cooldown)
                    reset_circuit_breaker()
                    continue

                logger.error(
                    "Provider rate-limit error encountered for '%s' and recovery budget exhausted.",
                    sym,
                )
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning("Data fetch failed for '%s' via acquisition boundary: %s", sym, e)
                err_msg = str(e)
                exc_failure_type = getattr(e, "failure_type", None) or "PROVIDER_FAILURE"
                src_tag = (
                    "INVALID_SYMBOL"
                    if exc_failure_type == "INVALID_SYMBOL"
                    else (
                        "EXPLICITLY_INVALID"
                        if exc_failure_type == "EXPLICITLY_INVALID"
                        else "PROVIDER_FAILURE"
                    )
                )

                return RawMarketDataPayload(
                    symbol=sym,
                    raw_df=pd.DataFrame(),
                    provider_name=provider_name,
                    source_tag=src_tag,
                    failure_type=exc_failure_type,
                    warnings=(f"[{sym}] Failed to acquire market data from provider: {e}",),
                    error=err_msg,
                )

        return RawMarketDataPayload(
            symbol=sym,
            raw_df=pd.DataFrame(),
            provider_name=provider_name,
            source_tag="PROVIDER_FAILURE",
            error="Rate limit retries exhausted",
        )


def acquire_raw_market_data(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    max_retries: int = 2,
    throttle_delay: float = 0.0,
    max_rate_limit_retries: int = 3,
    target_date: str | None = None,
    provider: MarketDataProvider | None = None,
) -> RawMarketDataPayload:
    """Convenience entry point to acquire raw market data via MarketDataAcquirer."""
    acquirer = MarketDataAcquirer(provider=provider)
    return acquirer.acquire(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        max_retries=max_retries,
        throttle_delay=throttle_delay,
        max_rate_limit_retries=max_rate_limit_retries,
        target_date=target_date,
    )


__all__ = [
    "AcquisitionError",
    "ExplicitlyInvalidDataError",
    "InvalidSymbolError",
    "MarketDataAcquirer",
    "RawMarketDataPayload",
    "acquire_raw_market_data",
]
