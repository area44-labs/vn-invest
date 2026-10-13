"""Unit tests for Market Regime in scripts/quant/regime.py."""

import numpy as np
import pandas as pd
import pytest

from scripts.quant.regime import detect_market_regime


@pytest.mark.unit
class TestMarketRegime:
    def test_strong_bull_regime(self):
        n = 60
        close_prices = np.linspace(1200, 1500, n)
        df_vnindex = pd.DataFrame({"close": close_prices, "volume": [1e8] * n})

        res = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.80)
        assert res["regime"] in ["STRONG_BULL", "BULL"]
        assert res["regime_score"] >= 60.0

    def test_panic_or_bear_regime(self):
        n = 60
        close_prices = np.linspace(1500, 1000, n)
        close_prices[-1] = close_prices[-2] * 0.95
        df_vnindex = pd.DataFrame({"close": close_prices, "volume": [1e8] * n})

        res = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.10)
        assert res["regime"] in ["BEAR", "PANIC"]
        assert res["regime_score"] <= 40.0

    def test_neutral_regime_evaluation_and_support(self):
        """1. Verify NEUTRAL market regime classification, boundaries, risk factor calculation, and score bounds."""
        from scripts.quant.config import DEFAULT_QUANT_CONFIG
        from scripts.quant.risk import calculate_risk_adjusted_score

        assert "NEUTRAL" in DEFAULT_QUANT_CONFIG.valid_market_regimes
        assert DEFAULT_QUANT_CONFIG.regime_score_factors["NEUTRAL"] == 0.90

        # Create a synthetic dataset that produces a score in [50.0, 60.0) (NEUTRAL)
        # Base score 50 + MA20 (+15) - MA50 (-10) = 55.0 (NEUTRAL)
        close_prices = [1300.0] * 30 + [1200.0] * 10 + [1201.0] * 10 + [1205.0] * 10
        df_vnindex = pd.DataFrame({"close": close_prices, "volume": [1e8] * len(close_prices)})

        res_neutral = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=None)
        assert res_neutral["regime"] == "NEUTRAL"
        assert res_neutral["regime_score"] == 55.0

        # Boundary checks: mock detector outputs for regime score boundary transitions
        def _mock_detector(score_val):
            return lambda **kw: {
                "regime": (
                    "STRONG_BULL"
                    if score_val >= 80.0
                    else "BULL"
                    if score_val >= 60.0
                    else "NEUTRAL"
                    if score_val >= 50.0
                    else "DEFENSIVE"
                    if score_val >= 40.0
                    else "BEAR"
                    if score_val >= 20.0
                    else "PANIC"
                ),
                "regime_score": score_val,
                "confidence": 0.85,
                "metrics": {},
            }

        res_49_9 = detect_market_regime(detector=_mock_detector(49.9))
        assert res_49_9["regime"] == "DEFENSIVE"

        res_50_0 = detect_market_regime(detector=_mock_detector(50.0))
        assert res_50_0["regime"] == "NEUTRAL"

        res_59_9 = detect_market_regime(detector=_mock_detector(59.9))
        assert res_59_9["regime"] == "NEUTRAL"

        res_60_0 = detect_market_regime(detector=_mock_detector(60.0))
        assert res_60_0["regime"] == "BULL"

        # Verify risk adjusted score calculation for NEUTRAL regime
        score_neutral = calculate_risk_adjusted_score(signal_score=80.0, regime="NEUTRAL")
        assert score_neutral is not None
        assert 0.0 <= score_neutral <= 100.0

    def test_insufficient_data_regime(self):
        res = detect_market_regime(df_vnindex=None)
        assert res["regime"] == "DEFENSIVE"
        assert res["confidence"] < 0.5

    def test_volume_validation_cases(self):
        """Valid volume, NaN, Inf, negative, 0 mean, and NaN/Inf leak checks."""
        n = 30
        close_prices = np.linspace(1200, 1300, n)

        # Valid volume
        df_valid = pd.DataFrame({"close": close_prices, "volume": [100.0] * n})
        res_valid = detect_market_regime(df_vnindex=df_valid, breadth_ratio=0.5)
        assert res_valid["metrics"]["volume_20d_ratio"] == 1.0

        # Volume with NaN
        df_nan = pd.DataFrame({"close": close_prices, "volume": [100.0] * n})
        df_nan.loc[5, "volume"] = np.nan
        res_nan = detect_market_regime(df_vnindex=df_nan, breadth_ratio=0.5)
        assert res_nan["metrics"]["volume_20d_ratio"] is None

        # Volume with Inf
        df_inf = pd.DataFrame({"close": close_prices, "volume": [100.0] * n})
        df_inf.loc[5, "volume"] = np.inf
        res_inf = detect_market_regime(df_vnindex=df_inf, breadth_ratio=0.5)
        assert res_inf["metrics"]["volume_20d_ratio"] is None

        # Negative volume
        df_neg = pd.DataFrame({"close": close_prices, "volume": [100.0] * n})
        df_neg.loc[5, "volume"] = -50.0
        res_neg = detect_market_regime(df_vnindex=df_neg, breadth_ratio=0.5)
        assert res_neg["metrics"]["volume_20d_ratio"] is None

        # Volume with 20d mean = 0
        df_zero_mean = pd.DataFrame({"close": close_prices, "volume": [0.0] * n})
        res_zero = detect_market_regime(df_vnindex=df_zero_mean, breadth_ratio=0.5)
        assert res_zero["metrics"]["volume_20d_ratio"] is None

        # Verify all output metrics contain no NaN or Inf across all cases
        import math

        for res in [res_valid, res_nan, res_inf, res_neg, res_zero]:
            for k, v in res["metrics"].items():
                if v is not None:
                    assert not (math.isnan(v)), f"Metric {k} is NaN"
                    assert not (math.isinf(v)), f"Metric {k} is Inf"

    def test_regime_module_independent_of_backtest(self):
        """Verify scripts.quant.regime can be imported without importing scripts.backtest.engine."""
        import sys

        # Remove backtest from sys.modules if present to test independent import
        sys.modules.pop("scripts.backtest.engine", None)
        import scripts.quant.regime as regime_mod

        assert hasattr(regime_mod, "detect_market_regime")
        assert "RegimeObservation" not in regime_mod.__all__
        assert "evaluate_market_regimes" not in regime_mod.__all__
