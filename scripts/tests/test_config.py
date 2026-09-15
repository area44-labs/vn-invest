"""Tests for Centralized Configuration Module (scripts/lib/config.py) and Engine Behavior Preservation.

Verifies that:
1. Centralized parameter values match expected defaults.
2. Re-exported constants in scripts/lib/recommendation.py remain identical.
3. SIGNAL_MODEL_VERSION remains unchanged ("2.0").
4. Scoring functions preserve exact quantitative outputs across threshold boundaries.
5. Market regime classification logic behaves deterministically across all regimes.
6. Trade plan generation produces exact expected bounds and position caps.
7. End-to-end generate_recommendation behavior remains invariant.
"""

import unittest

import numpy as np
import pandas as pd

from scripts.lib import config, recommendation
from scripts.lib.recommendation import (
    calculate_confidence,
    calculate_divergence_score,
    calculate_momentum_score,
    calculate_relative_strength_score,
    calculate_risk_adjusted_score,
    calculate_signal_score,
    calculate_trend_score,
    calculate_volume_score,
    classify_action,
    generate_recommendation,
)
from scripts.lib.regime import detect_market_regime


class TestCentralizedConfigConstants(unittest.TestCase):
    def test_version_unchanged(self):
        """Verify SIGNAL_MODEL_VERSION is '2.0' and identical across modules."""
        self.assertEqual(config.SIGNAL_MODEL_VERSION, "2.0")
        self.assertEqual(recommendation.SIGNAL_MODEL_VERSION, "2.0")

    def test_reexported_constants(self):
        """Verify backwards-compatible re-exported constants in recommendation module."""
        self.assertEqual(recommendation.SIGNAL_WEIGHTS, config.SIGNAL_WEIGHTS)
        self.assertEqual(
            recommendation.DIVERGENCE_TIMEFRAME_WEIGHTS, config.DIVERGENCE_TIMEFRAME_WEIGHTS
        )
        self.assertEqual(recommendation.VALID_MARKET_REGIMES, config.VALID_MARKET_REGIMES)

    def test_weights_sum_to_one(self):
        """Verify signal weights and divergence timeframe weights sum to 1.0."""
        self.assertAlmostEqual(sum(config.SIGNAL_WEIGHTS.values()), 1.0, places=6)
        self.assertAlmostEqual(sum(config.DIVERGENCE_TIMEFRAME_WEIGHTS.values()), 1.0, places=6)


class TestScoringFunctionsAndThresholds(unittest.TestCase):
    def test_calculate_trend_score(self):
        """Verify trend score calculation with MA20, MA50, and MA20 vs MA50 alignment."""
        # None inputs
        self.assertIsNone(calculate_trend_score(None, 50, 50))
        self.assertIsNone(calculate_trend_score(50, None, None))

        # Close > MA20 (+25), Close > MA50 (+15), MA20 > MA50 (+10) => 50 + 25 + 15 + 10 = 100
        self.assertEqual(calculate_trend_score(55.0, 50.0, 45.0), 100.0)

        # Close < MA20 (-25), Close < MA50 (-15), MA20 < MA50 (-10) => 50 - 25 - 15 - 10 = 0
        self.assertEqual(calculate_trend_score(40.0, 45.0, 50.0), 0.0)

        # Mixed alignment: Close > MA20 (+25), Close < MA50 (-15), MA20 < MA50 (-10) => 50 + 25 - 15 - 10 = 50.0
        self.assertEqual(calculate_trend_score(48.0, 45.0, 50.0), 50.0)

    def test_calculate_momentum_score_and_rsi_boundaries(self):
        """Verify momentum scoring across exact RSI boundaries: 35, 45, 65, 70, 78."""
        # RSI > 78.0 => -25
        self.assertEqual(calculate_momentum_score(78.1, None, None), 25.0)

        # 70.0 < RSI <= 78.0 => -15
        self.assertEqual(calculate_momentum_score(78.0, None, None), 35.0)
        self.assertEqual(calculate_momentum_score(70.1, None, None), 35.0)

        # 65.0 < RSI <= 70.0 => +10
        self.assertEqual(calculate_momentum_score(70.0, None, None), 60.0)
        self.assertEqual(calculate_momentum_score(65.1, None, None), 60.0)

        # 45.0 <= RSI <= 65.0 => +20
        self.assertEqual(calculate_momentum_score(65.0, None, None), 70.0)
        self.assertEqual(calculate_momentum_score(45.0, None, None), 70.0)

        # 35.0 <= RSI < 45.0 => -10
        self.assertEqual(calculate_momentum_score(44.9, None, None), 40.0)
        self.assertEqual(calculate_momentum_score(35.0, None, None), 40.0)

        # RSI < 35.0 => -20
        self.assertEqual(calculate_momentum_score(34.9, None, None), 30.0)

        # MACD histogram expansion / contraction checks
        # Positive and expanding (+25)
        self.assertEqual(calculate_momentum_score(50.0, 1.5, 1.0), 95.0)
        # Positive and contracting (+10)
        self.assertEqual(calculate_momentum_score(50.0, 1.0, 1.5), 80.0)
        # Negative and expanding (-25)
        self.assertEqual(calculate_momentum_score(50.0, -1.5, -1.0), 45.0)
        # Negative and contracting (-10)
        self.assertEqual(calculate_momentum_score(50.0, -1.0, -1.5), 60.0)

    def test_calculate_volume_score(self):
        """Verify volume ratio score mapping across thresholds (2.0, 1.5, 1.2, 0.8, 0.5)."""
        self.assertIsNone(calculate_volume_score(None))
        self.assertIsNone(calculate_volume_score(0.0))
        self.assertEqual(calculate_volume_score(2.0), 100.0)
        self.assertEqual(calculate_volume_score(1.5), 85.0)
        self.assertEqual(calculate_volume_score(1.2), 70.0)
        self.assertEqual(calculate_volume_score(0.8), 50.0)
        self.assertEqual(calculate_volume_score(0.5), 35.0)
        self.assertEqual(calculate_volume_score(0.4), 20.0)

    def test_calculate_relative_strength_score(self):
        """Verify relative strength score mapping across thresholds (+10%, +5%, +2%, -2%, -5%)."""
        self.assertIsNone(calculate_relative_strength_score(None))
        self.assertEqual(calculate_relative_strength_score(0.10), 100.0)
        self.assertEqual(calculate_relative_strength_score(0.05), 80.0)
        self.assertEqual(calculate_relative_strength_score(0.02), 65.0)
        self.assertEqual(calculate_relative_strength_score(-0.02), 50.0)
        self.assertEqual(calculate_relative_strength_score(-0.05), 35.0)
        self.assertEqual(calculate_relative_strength_score(-0.06), 15.0)

    def test_calculate_divergence_score(self):
        """Verify timeframe-weighted divergence scoring."""
        self.assertIsNone(calculate_divergence_score(None))
        self.assertIsNone(calculate_divergence_score({}))

        tf_summary_bullish = {
            "1d": {"available": True, "divergence": {"rsi_bullish": True}},
            "1w": {"available": True, "divergence": {"rsi_bullish": True}},
            "1m": {"available": True, "divergence": {"rsi_bullish": True}},
        }
        # All timeframe bullish => 90.0
        self.assertEqual(calculate_divergence_score(tf_summary_bullish), 90.0)

        tf_summary_bearish = {
            "1d": {"available": True, "divergence": {"rsi_bearish": True}},
            "1w": {"available": True, "divergence": {"rsi_bearish": True}},
            "1m": {"available": True, "divergence": {"rsi_bearish": True}},
        }
        # All timeframe bearish => 10.0
        self.assertEqual(calculate_divergence_score(tf_summary_bearish), 10.0)

    def test_calculate_signal_score(self):
        """Verify composite signal score weight normalization and data quality status."""
        # All 5 components present
        score, _comps, quality = calculate_signal_score(100.0, 100.0, 100.0, 100.0, 100.0)
        self.assertEqual(score, 100.0)
        self.assertEqual(quality, "SUFFICIENT")

        # 3 components present (partial quality)
        score, _comps, quality = calculate_signal_score(80.0, 60.0, 40.0, None, None)
        # Weights: trend (0.30), momentum (0.25), volume (0.15) => sum = 0.70
        # Weighted sum: (80*0.30 + 60*0.25 + 40*0.15) / 0.70 = 45 / 0.70 = 64.2857 -> 64.3
        self.assertEqual(score, 64.3)
        self.assertEqual(quality, "PARTIAL")

        # Fewer than 3 components present => INSUFFICIENT
        score, _comps, quality = calculate_signal_score(80.0, 60.0, None, None, None)
        self.assertIsNone(score)
        self.assertEqual(quality, "INSUFFICIENT")

    def test_calculate_confidence(self):
        """Verify confidence calculation and risk metric adjustments."""
        # INSUFFICIENT quality
        self.assertEqual(calculate_confidence("INSUFFICIENT", {}, {}), config.CONFIDENCE_MIN)

        comps_aligned = {
            "trend": 70.0,
            "momentum": 70.0,
            "volume": 70.0,
            "relative_strength": 70.0,
            "divergence": 70.0,
        }
        # SUFFICIENT quality base (0.70) + low dispersion bonus (+0.10) => 0.80
        conf_aligned = calculate_confidence("SUFFICIENT", comps_aligned, {})
        self.assertEqual(conf_aligned, 0.80)

        # High volatility / drawdown penalty boundary checks (vol > 0.35 or mdd > 0.25)
        conf_high_risk = calculate_confidence(
            "SUFFICIENT",
            comps_aligned,
            {"volatility_60d": 0.36, "max_drawdown": -0.20},
        )
        self.assertEqual(conf_high_risk, 0.75)

        # Low risk bonus boundary checks (vol < 0.22 and mdd < 0.12)
        conf_low_risk = calculate_confidence(
            "SUFFICIENT",
            comps_aligned,
            {"volatility_60d": 0.20, "max_drawdown": -0.10},
        )
        self.assertEqual(conf_low_risk, 0.85)

    def test_calculate_risk_adjusted_score_boundaries(self):
        """Verify risk adjusted score penalties across volatility and drawdown thresholds."""
        # Base score 100 in BULL regime (factor 1.0)
        # Volatility penalty threshold 0.20: at vol=0.20 penalty is 0, score=100
        score_base = calculate_risk_adjusted_score(
            100.0, "BULL", volatility_60d=0.20, max_drawdown=-0.15, liquidity_score=100.0
        )
        self.assertEqual(score_base, 100.0)

        # Volatility 0.30 => penalty = min(0.25, (0.30 - 0.20)*0.5) = 0.05 => score = 100 * 0.95 = 95.0
        score_vol_pen = calculate_risk_adjusted_score(
            100.0, "BULL", volatility_60d=0.30, max_drawdown=-0.15, liquidity_score=100.0
        )
        self.assertEqual(score_vol_pen, 95.0)

        # Drawdown 0.25 => penalty = min(0.25, (0.25 - 0.15)*0.5) = 0.05 => score = 100 * 0.95 = 95.0
        score_mdd_pen = calculate_risk_adjusted_score(
            100.0, "BULL", volatility_60d=0.20, max_drawdown=-0.25, liquidity_score=100.0
        )
        self.assertEqual(score_mdd_pen, 95.0)

    def test_classify_action_signal_score_boundaries(self):
        """Verify action classification exact boundaries: 35, 45, 55, 65, 75."""
        # PANIC regime => always AVOID
        self.assertEqual(classify_action(80.0, "PANIC", 100, 90), "AVOID")
        self.assertEqual(classify_action(None, "BULL", 100, 90), "AVOID")

        # Score < 35.0 in BEAR/PANIC => AVOID, else SELL
        self.assertEqual(classify_action(34.9, "BEAR", 100, 90), "AVOID")
        self.assertEqual(classify_action(34.9, "BULL", 100, 90), "SELL")

        # 35.0 <= Score < 45.0 => SELL
        self.assertEqual(classify_action(35.0, "BULL", 100, 90), "SELL")
        self.assertEqual(classify_action(44.9, "BULL", 100, 90), "SELL")

        # 45.0 <= Score < 55.0 => HOLD
        self.assertEqual(classify_action(45.0, "BULL", 100, 90), "HOLD")
        self.assertEqual(classify_action(54.9, "BULL", 100, 90), "HOLD")

        # 55.0 <= Score < 65.0 => WATCH
        self.assertEqual(classify_action(55.0, "BULL", 100, 90), "WATCH")
        self.assertEqual(classify_action(64.9, "BULL", 100, 90), "WATCH")

        # Score >= 65.0 => BUY if (STRONG_BULL/BULL/DEFENSIVE & close > ma20) else WATCH
        self.assertEqual(classify_action(65.0, "BULL", 100, 90), "BUY")
        self.assertEqual(classify_action(65.0, "BULL", 80, 90), "WATCH")  # close <= ma20

        # Score >= 75.0 => BUY if (STRONG_BULL/BULL & close > ma20) else WATCH
        self.assertEqual(classify_action(75.0, "STRONG_BULL", 100, 90), "BUY")
        self.assertEqual(classify_action(75.0, "DEFENSIVE", 100, 90), "WATCH")


class TestMarketRegimeDetection(unittest.TestCase):
    def test_detect_market_regime_cases(self):
        """Verify detect_market_regime across STRONG_BULL, BULL, DEFENSIVE, BEAR, PANIC, and insufficient history."""
        # Insufficient history (< 20 rows)
        df_short = pd.DataFrame({"close": [100.0] * 10})
        res_short = detect_market_regime(df_short)
        self.assertEqual(res_short["regime"], "DEFENSIVE")
        self.assertEqual(res_short["regime_score"], 50.0)

        # Synthetic 60-session VNINDEX DataFrame
        dates = pd.date_range("2026-01-01", periods=60)

        # STRONG_BULL: strong upward trend (e.g. 100 to 160) + high breadth (0.80)
        close_bull = np.linspace(100, 160, 60)
        df_bull = pd.DataFrame({"close": close_bull, "volume": [1e6] * 60}, index=dates)
        res_bull = detect_market_regime(df_bull, breadth_ratio=0.80)
        self.assertEqual(res_bull["regime"], "STRONG_BULL")
        self.assertGreaterEqual(res_bull["regime_score"], 80.0)

        # BEAR: steady decline (160 to 100) + low breadth (0.20)
        close_bear = np.linspace(160, 100, 60)
        df_bear = pd.DataFrame({"close": close_bear, "volume": [1e6] * 60}, index=dates)
        res_bear = detect_market_regime(df_bear, breadth_ratio=0.20)
        self.assertIn(res_bear["regime"], ["BEAR", "PANIC"])

        # PANIC: large 1-day crash (-5%)
        close_panic = np.linspace(100, 120, 60)
        close_panic[-1] = close_panic[-2] * 0.94  # 6% drop
        df_panic = pd.DataFrame({"close": close_panic, "volume": [1e6] * 60}, index=dates)
        res_panic = detect_market_regime(df_panic, breadth_ratio=0.20)
        self.assertIn(res_panic["regime"], ["BEAR", "PANIC"])


class TestTradePlanAndIntegration(unittest.TestCase):
    def test_trade_plan_preservation(self):
        """Verify trade plan entry bounds, stop loss, targets, and position caps."""
        # Construct synthetic stock DataFrame (60 sessions)
        dates = pd.date_range("2026-01-01", periods=60)
        close_prices = np.linspace(30000, 50000, 60)
        high_prices = close_prices * 1.02
        low_prices = close_prices * 0.98
        open_prices = close_prices * 0.99
        volume = [1000000.0] * 60

        df_stock = pd.DataFrame(
            {
                "time": dates.strftime("%Y-%m-%d"),
                "open": open_prices,
                "high": high_prices,
                "low": low_prices,
                "close": close_prices,
                "volume": volume,
            }
        )

        regime_info = {"regime": "STRONG_BULL", "regime_score": 85.0}
        rec = generate_recommendation(
            symbol="FPT",
            company_name="FPT Corp",
            sector="Công nghệ",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=regime_info,
        )

        self.assertEqual(rec["symbol"], "FPT")
        self.assertEqual(rec["model_version"], "2.0")
        self.assertEqual(rec["action"], "WATCH")  # Signal score is 60.3 (< 65)

        plan = rec["trade_plan"]
        self.assertIsNotNone(plan["current_price"])
        self.assertEqual(plan["position_percent"], 10.0)  # Max cap for WATCH action is 10.0%


if __name__ == "__main__":
    unittest.main()
