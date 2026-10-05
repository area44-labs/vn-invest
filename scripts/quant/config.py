"""Canonical Quantitative Configuration and Version Contract for VN Invest quant layer."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class QuantConfig:
    """Canonical, single authoritative quantitative configuration and version contract."""

    # Model and Configuration Versions
    quant_version: str = "1.0.0"
    model_version: str = "2.0"

    # Signal weights
    signal_weights: dict[str, float] = field(
        default_factory=lambda: {
            "trend": 0.30,
            "momentum": 0.25,
            "volume": 0.15,
            "relative_strength": 0.15,
            "divergence": 0.15,
        }
    )

    divergence_timeframe_weights: dict[str, float] = field(
        default_factory=lambda: {
            "1D": 0.50,
            "1W": 0.30,
            "1M": 0.20,
        }
    )

    valid_market_regimes: tuple[str, ...] = (
        "STRONG_BULL",
        "BULL",
        "NEUTRAL",
        "DEFENSIVE",
        "BEAR",
        "PANIC",
    )

    # Technical Indicator Parameters
    atr_period: int = 14
    ma_short_period: int = 20
    ma_long_period: int = 50
    rsi_period: int = 14
    macd_fast_period: int = 12
    macd_slow_period: int = 26
    macd_signal_period: int = 9

    # Trend Scoring Parameters
    trend_base_score: float = 50.0
    trend_ma20_weight: float = 25.0
    trend_ma50_weight: float = 15.0
    trend_ma20_vs_ma50_weight: float = 10.0

    # Momentum Scoring Parameters
    momentum_base_score: float = 50.0
    rsi_overbought_extreme: float = 78.0
    rsi_overbought: float = 70.0
    rsi_strong_momentum_lower: float = 65.0
    rsi_safe_lower: float = 45.0
    rsi_safe_upper: float = 65.0
    rsi_weak_lower: float = 35.0

    rsi_score_overbought_extreme_penalty: float = 25.0
    rsi_score_overbought_penalty: float = 15.0
    rsi_score_strong_momentum_bonus: float = 10.0
    rsi_score_safe_bonus: float = 20.0
    rsi_score_weak_penalty: float = 10.0
    rsi_score_oversold_penalty: float = 20.0

    macd_score_pos_expanding: float = 25.0
    macd_score_pos_contracting: float = 10.0
    macd_score_neg_expanding: float = 25.0
    macd_score_neg_contracting: float = 10.0
    macd_score_pos_single: float = 15.0
    macd_score_neg_single: float = 15.0

    # Volume Scoring Parameters
    volume_ratio_very_high: float = 2.0
    volume_ratio_high: float = 1.5
    volume_ratio_above_avg: float = 1.2
    volume_ratio_normal: float = 0.8
    volume_ratio_low: float = 0.5

    volume_score_very_high: float = 100.0
    volume_score_high: float = 85.0
    volume_score_above_avg: float = 70.0
    volume_score_normal: float = 50.0
    volume_score_low: float = 35.0
    volume_score_very_low: float = 20.0

    # Relative Strength Parameters
    rs_diff_strong_outperform: float = 0.10
    rs_diff_outperform: float = 0.05
    rs_diff_mild_outperform: float = 0.02
    rs_diff_neutral: float = -0.02
    rs_diff_underperform: float = -0.05

    rs_score_strong_outperform: float = 100.0
    rs_score_outperform: float = 80.0
    rs_score_mild_outperform: float = 65.0
    rs_score_neutral: float = 50.0
    rs_score_underperform: float = 35.0
    rs_score_strong_underperform: float = 15.0

    # Divergence Scoring Parameters
    divergence_score_bullish: float = 90.0
    divergence_score_bearish: float = 10.0
    divergence_score_conflict: float = 40.0
    divergence_score_neutral: float = 50.0

    divergence_min_history: int = 15
    divergence_lookback_1d: int = 40
    divergence_lookback_1w: int = 30
    divergence_lookback_1m: int = 24
    divergence_trough_price_tolerance: float = 1.01
    divergence_peak_price_tolerance: float = 0.99
    divergence_rsi_delta: float = 1.5
    divergence_macd_delta: float = 0.05
    divergence_fallback_rsi_delta: float = 3.0
    divergence_fallback_rsi_max: float = 40.0

    # Component Thresholds
    min_components_for_signal: int = 3
    min_components_for_sufficient_quality: int = 5

    # Action Classification Thresholds
    score_threshold_strong_buy: float = 75.0
    score_threshold_buy: float = 65.0
    score_threshold_watch: float = 55.0
    score_threshold_hold: float = 45.0
    score_threshold_sell: float = 35.0

    regimes_strong_buy: tuple[str, ...] = ("STRONG_BULL", "BULL")
    regimes_buy: tuple[str, ...] = ("STRONG_BULL", "BULL", "DEFENSIVE")

    # Confidence Parameters
    confidence_min: float = 0.10
    confidence_max: float = 0.95
    confidence_base_sufficient: float = 0.70
    confidence_base_partial: float = 0.55

    dispersion_std_very_low: float = 12.0
    dispersion_std_low: float = 18.0
    dispersion_std_high: float = 30.0
    dispersion_std_moderate_high: float = 22.0

    confidence_adj_very_low_dispersion: float = 0.10
    confidence_adj_low_dispersion: float = 0.05
    confidence_adj_high_dispersion: float = -0.15
    confidence_adj_moderate_high_dispersion: float = -0.08

    risk_volatility_high: float = 0.35
    risk_drawdown_high: float = 0.25
    risk_volatility_low: float = 0.22
    risk_drawdown_low: float = 0.12

    confidence_adj_high_risk: float = -0.05
    confidence_adj_low_risk: float = 0.05
    confidence_adj_extreme_rsi: float = -0.05

    # Risk-Adjusted Score Parameters
    regime_score_factors: dict[str, float] = field(
        default_factory=lambda: {
            "STRONG_BULL": 1.05,
            "BULL": 1.00,
            "NEUTRAL": 0.90,
            "DEFENSIVE": 0.90,
            "BEAR": 0.75,
            "PANIC": 0.50,
        }
    )

    volatility_penalty_threshold: float = 0.20
    volatility_penalty_factor: float = 0.5
    volatility_penalty_max: float = 0.25

    drawdown_penalty_threshold: float = 0.15
    drawdown_penalty_factor: float = 0.5
    drawdown_penalty_max: float = 0.25

    liquidity_factor_base: float = 0.85
    liquidity_factor_scale: float = 0.15

    # Trade Plan Generation Parameters
    trade_plan_stop_atr_mult: float = 1.8
    trade_plan_default_stop_pct: float = 0.95
    trade_plan_ma20_stop_pct: float = 0.98
    trade_plan_max_stop_pct: float = 0.93
    trade_plan_stop_clamp_cap: float = 0.99
    trade_plan_min_risk_pct: float = 0.03
    trade_plan_entry_high_mult: float = 1.02
    trade_plan_tp1_rr_mult: float = 2.0
    trade_plan_tp2_rr_mult: float = 3.0
    trade_plan_default_rr: float = 1.0
    trade_plan_default_stop_dist_pct: float = 0.05
    trade_plan_portfolio_risk_budget_pct: float = 1.0
    trade_plan_max_position_buy_pct: float = 20.0
    trade_plan_max_position_watch_pct: float = 10.0

    # Market Regime Detection Parameters
    regime_min_history: int = 20
    regime_base_score: float = 50.0

    regime_trend_ma20_weight: float = 15.0
    regime_trend_ma50_weight: float = 10.0

    regime_ret_20d_strong_bull: float = 5.0
    regime_ret_20d_bull: float = 1.0
    regime_ret_20d_strong_bear: float = -5.0
    regime_ret_20d_bear: float = -1.0

    regime_ret_20d_strong_bull_score: float = 15.0
    regime_ret_20d_bull_score: float = 8.0
    regime_ret_20d_strong_bear_score: float = -15.0
    regime_ret_20d_bear_score: float = -8.0

    regime_breadth_high: float = 0.65
    regime_breadth_med: float = 0.50
    regime_breadth_low: float = 0.35

    regime_breadth_high_score: float = 10.0
    regime_breadth_med_score: float = 5.0
    regime_breadth_low_score: float = -10.0

    regime_panic_volatility: float = 0.35
    regime_panic_daily_drop_pct: float = -3.0
    regime_panic_penalty: float = -15.0

    regime_threshold_strong_bull: float = 80.0
    regime_threshold_bull: float = 60.0
    regime_threshold_defensive: float = 40.0
    regime_threshold_bear: float = 20.0

    regime_confidence_sufficient: float = 0.85
    regime_confidence_partial: float = 0.60
    regime_confidence_insufficient: float = 0.40
    regime_confidence_history_threshold: int = 50

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to a dictionary representation."""
        raw_dict = asdict(self)
        # Ensure tuples/lists/dicts are JSON serializable and detached
        cleaned: dict[str, Any] = {}
        for k, v in raw_dict.items():
            if isinstance(v, tuple):
                cleaned[k] = list(v)
            elif isinstance(v, dict):
                cleaned[k] = dict(v)
            else:
                cleaned[k] = v
        return cleaned

    def get_config_hash(self) -> str:
        """Calculate deterministic SHA-256 fingerprint hash of configuration state."""
        dict_repr = self.to_dict()
        canonical_json = json.dumps(dict_repr, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:12]

    @property
    def version_contract(self) -> dict[str, str]:
        """Authoritative quantitative version contract."""
        return {
            "quant_version": self.quant_version,
            "model_version": self.model_version,
            "config_hash": self.get_config_hash(),
        }


DEFAULT_QUANT_CONFIG = QuantConfig()

__all__ = [
    "DEFAULT_QUANT_CONFIG",
    "QuantConfig",
]
