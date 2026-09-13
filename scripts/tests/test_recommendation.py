"""Unit tests for VN Invest Signal Engine in scripts/lib/recommendation.py."""

import math
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts.lib.recommendation import (
    SIGNAL_WEIGHTS,
    calculate_divergence_score,
    calculate_momentum_score,
    calculate_relative_strength_score,
    calculate_risk_adjusted_alpha,
    calculate_signal_score,
    calculate_trend_score,
    calculate_volume_score,
    classify_action,
    generate_recommendation,
)
from scripts.lib.risk import normalize_universe_liquidity_scores


class TestVNInvestSignalEngine(unittest.TestCase):
    def test_signal_weights_sum_to_one(self):
        """Verify centralized signal weights sum to 1.0."""
        weight_sum = sum(SIGNAL_WEIGHTS.values())
        self.assertAlmostEqual(weight_sum, 1.0, places=5)

    def test_component_scores_bounded(self):
        """Verify component scores return values in [0, 100] or None."""
        # Trend
        self.assertEqual(calculate_trend_score(35.0, 30.0, 25.0), 100.0)
        self.assertEqual(calculate_trend_score(20.0, 30.0, 35.0), 0.0)
        self.assertIsNone(calculate_trend_score(None, 30.0, 25.0))
        self.assertIsNone(calculate_trend_score(float("nan"), 30.0, 25.0))

        # Momentum
        self.assertEqual(calculate_momentum_score(55.0, 0.5, 0.2), 95.0)
        self.assertEqual(calculate_momentum_score(72.0, -0.5, -0.2), 10.0)
        self.assertEqual(calculate_momentum_score(80.0, -0.5, -0.2), 0.0)
        self.assertIsNone(calculate_momentum_score(None, None, None))

        # Volume
        self.assertEqual(calculate_volume_score(2.5), 100.0)
        self.assertEqual(calculate_volume_score(0.2), 20.0)
        self.assertIsNone(calculate_volume_score(None))

        # Relative Strength
        self.assertEqual(calculate_relative_strength_score(0.12), 100.0)
        self.assertEqual(calculate_relative_strength_score(-0.08), 15.0)
        self.assertIsNone(calculate_relative_strength_score(None))

        # Divergence
        tf_summary_bullish = {
            "1d": {"available": True, "divergence": {"rsi_bullish": True, "macd_bullish": False}},
            "1w": {"available": True, "divergence": {"rsi_bullish": False, "macd_bullish": False}},
            "1m": {"available": True, "divergence": {"rsi_bullish": False, "macd_bullish": False}},
        }
        self.assertEqual(calculate_divergence_score(tf_summary_bullish), 65.0)
        self.assertIsNone(calculate_divergence_score(None))

    def test_missing_data_renormalizes_weights(self):
        """Verify missing data excludes unavailable components and renormalizes weights without distorting scores."""
        score, components, data_quality = calculate_signal_score(
            trend_score=100.0,
            momentum_score=80.0,
            volume_score=None,
            relative_strength_score=90.0,
            divergence_score=None,
        )
        self.assertIsNotNone(score)
        self.assertEqual(data_quality, "PARTIAL")
        self.assertIsNone(components["volume"])
        self.assertIsNone(components["divergence"])

        # Expected: weighted across trend (0.30), momentum (0.25), relative_strength (0.15) -> total = 0.70
        expected = round((100.0 * 0.30 + 80.0 * 0.25 + 90.0 * 0.15) / 0.70, 1)
        self.assertEqual(score, expected)

    def test_action_classification_boundary_conditions(self):
        """Test action thresholds deterministically at precise boundaries: 34.9, 35.0, 44.9, 45.0, 54.9, 55.0, 64.9, 65.0, 74.9, 75.0."""
        regime = "BULL"
        raw_close = 30.0
        raw_ma20 = 25.0

        self.assertEqual(classify_action(34.9, regime, raw_close, raw_ma20), "SELL")
        self.assertEqual(classify_action(35.0, regime, raw_close, raw_ma20), "SELL")
        self.assertEqual(classify_action(44.9, regime, raw_close, raw_ma20), "SELL")
        self.assertEqual(classify_action(45.0, regime, raw_close, raw_ma20), "HOLD")
        self.assertEqual(classify_action(54.9, regime, raw_close, raw_ma20), "HOLD")
        self.assertEqual(classify_action(55.0, regime, raw_close, raw_ma20), "WATCH")
        self.assertEqual(classify_action(64.9, regime, raw_close, raw_ma20), "WATCH")
        self.assertEqual(classify_action(65.0, regime, raw_close, raw_ma20), "BUY")
        self.assertEqual(classify_action(74.9, regime, raw_close, raw_ma20), "BUY")
        self.assertEqual(classify_action(75.0, regime, raw_close, raw_ma20), "BUY")

        # DEFENSIVE regime action boundary check
        self.assertEqual(classify_action(65.0, "DEFENSIVE", raw_close, raw_ma20), "BUY")
        self.assertEqual(classify_action(75.0, "DEFENSIVE", raw_close, raw_ma20), "WATCH")

    def test_generate_recommendation_output_structure(self):
        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        close_bull = np.linspace(20.0, 35.0, n)
        df_bull = pd.DataFrame(
            {
                "time": dates,
                "open": close_bull - 0.2,
                "high": close_bull + 0.5,
                "low": close_bull - 0.5,
                "close": close_bull,
                "volume": [500000] * n,
            }
        )

        regime_bull = {"regime": "STRONG_BULL", "regime_score": 85.0}

        rec = generate_recommendation(
            symbol="FPT",
            company_name="Công ty FPT",
            sector="Công nghệ",
            exchange="HOSE",
            df_stock=df_bull,
            market_regime_info=regime_bull,
        )

        self.assertIn(rec["action"], ["BUY", "WATCH", "HOLD", "SELL", "AVOID"])
        self.assertEqual(rec["symbol"], "FPT")
        self.assertEqual(rec["model_version"], "2.0")
        self.assertIn(rec["data_quality"], ["SUFFICIENT", "PARTIAL", "INSUFFICIENT"])
        self.assertIsNotNone(rec["signal_score"])
        self.assertEqual(rec["signal_score"], rec["alpha_score"])
        self.assertIsNotNone(rec["risk_adjusted_score"])
        self.assertEqual(rec["risk_adjusted_score"], rec["risk_adjusted_alpha"])
        self.assertIsNotNone(rec["confidence"])
        self.assertGreaterEqual(rec["confidence"], 0.10)
        self.assertLessEqual(rec["confidence"], 0.95)
        self.assertIsInstance(rec["score_components"], dict)
        self.assertIsInstance(rec["invalidation"], list)
        self.assertIn("1H", rec["divergence"])

    def test_risk_adjusted_alpha_formula(self):
        """Verify risk-adjusted alpha deterministic calculation."""
        score = calculate_risk_adjusted_alpha(
            alpha_score=80.0,
            regime="STRONG_BULL",
            volatility_60d=0.15,
            max_drawdown=-0.10,
            liquidity_score=90.0,
        )
        self.assertGreaterEqual(score, 70.0)
        self.assertLessEqual(score, 100.0)

        # High volatility and drawdown penalty check
        score_high_risk = calculate_risk_adjusted_alpha(
            alpha_score=80.0,
            regime="BEAR",
            volatility_60d=0.45,
            max_drawdown=-0.35,
            liquidity_score=20.0,
        )
        self.assertLess(score_high_risk, score)

    def test_trade_plan_invariants(self):
        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        close_bull = np.linspace(20.0, 35.0, n)
        df_bull = pd.DataFrame(
            {
                "time": dates,
                "open": close_bull - 0.2,
                "high": close_bull + 0.5,
                "low": close_bull - 0.5,
                "close": close_bull,
                "volume": [500000] * n,
            }
        )

        regime_bull = {"regime": "STRONG_BULL", "regime_score": 85.0}
        rec = generate_recommendation(
            symbol="FPT",
            company_name="Công ty FPT",
            sector="Công nghệ",
            exchange="HOSE",
            df_stock=df_bull,
            market_regime_info=regime_bull,
        )

        tp = rec["trade_plan"]
        if rec["action"] in ["BUY", "WATCH"]:
            self.assertLessEqual(tp["entry_low"], tp["entry_high"])
            self.assertLess(tp["stop_loss"], tp["entry_low"])
            self.assertGreaterEqual(tp["tp1"], tp["entry_high"])
            self.assertGreaterEqual(tp["tp2"], tp["tp1"])
            self.assertGreaterEqual(tp["position_percent"], 0.0)
            self.assertLessEqual(tp["position_percent"], 100.0)
        else:
            self.assertIsNone(tp["entry_low"])
            self.assertIsNone(tp["stop_loss"])

    def test_anti_lookahead_bias_extended(self):
        """Verify recommendation at day T does not change when future crash, price spike, volume spike, or volatility spike occurs at T+1."""
        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        close_bull = np.linspace(20.0, 35.0, n)
        df_base = pd.DataFrame(
            {
                "time": dates,
                "open": close_bull - 0.2,
                "high": close_bull + 0.5,
                "low": close_bull - 0.5,
                "close": close_bull,
                "volume": [500000] * n,
            }
        )

        regime = {"regime": "BULL", "regime_score": 75.0}
        rec_t = generate_recommendation(
            symbol="FPT",
            company_name="FPT",
            sector="Tech",
            exchange="HOSE",
            df_stock=df_base.iloc[:50],  # up to day 50
            market_regime_info=regime,
        )

        scenarios = [
            # Future crash
            pd.DataFrame(
                {
                    "time": [pd.Timestamp("2026-03-01")],
                    "open": [10.0],
                    "high": [10.0],
                    "low": [1.0],
                    "close": [1.0],
                    "volume": [10000000],
                }
            ),
            # Future price spike
            pd.DataFrame(
                {
                    "time": [pd.Timestamp("2026-03-01")],
                    "open": [100.0],
                    "high": [200.0],
                    "low": [95.0],
                    "close": [190.0],
                    "volume": [500000],
                }
            ),
            # Future volume spike
            pd.DataFrame(
                {
                    "time": [pd.Timestamp("2026-03-01")],
                    "open": [35.0],
                    "high": [36.0],
                    "low": [34.0],
                    "close": [35.5],
                    "volume": [50000000],
                }
            ),
            # Future volatility spike
            pd.DataFrame(
                {
                    "time": [pd.Timestamp("2026-03-01")],
                    "open": [35.0],
                    "high": [50.0],
                    "low": [10.0],
                    "close": [25.0],
                    "volume": [100000],
                }
            ),
        ]

        for future_row in scenarios:
            df_future = pd.concat([df_base.iloc[:50], future_row], ignore_index=True)
            rec_t_sliced = generate_recommendation(
                symbol="FPT",
                company_name="FPT",
                sector="Tech",
                exchange="HOSE",
                df_stock=df_future.iloc[:50],  # sliced back to day 50
                market_regime_info=regime,
            )

            self.assertEqual(rec_t["signal_score"], rec_t_sliced["signal_score"])
            self.assertEqual(rec_t["alpha_score"], rec_t_sliced["alpha_score"])
            self.assertEqual(
                rec_t["trade_plan"]["current_price"], rec_t_sliced["trade_plan"]["current_price"]
            )

    def test_extreme_and_invalid_inputs(self):
        """Verify engine does not produce NaN, Inf, or crash on extreme/abnormal inputs."""
        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        df_extreme = pd.DataFrame(
            {
                "time": dates,
                "open": [10.0] * n,
                "high": [100.0] * n,
                "low": [0.001] * n,
                "close": [10.0] * n,
                "volume": [0] * n,  # Zero volume
            }
        )

        regime = {"regime": "BULL", "regime_score": 75.0}
        rec = generate_recommendation(
            symbol="TEST",
            company_name="Test Corp",
            sector="Test",
            exchange="HOSE",
            df_stock=df_extreme,
            market_regime_info=regime,
        )

        self.assertIsNotNone(rec["signal_score"])
        self.assertFalse(math.isnan(rec["signal_score"]))
        self.assertFalse(math.isinf(rec["signal_score"]))
        self.assertGreaterEqual(rec["signal_score"], 0.0)
        self.assertLessEqual(rec["signal_score"], 100.0)

    def test_avoid_action_in_panic(self):
        n = 30
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        df_stock = pd.DataFrame(
            {
                "time": dates,
                "open": [10.0] * n,
                "high": [10.5] * n,
                "low": [9.5] * n,
                "close": [10.0] * n,
                "volume": [100000] * n,
            }
        )

        regime_panic = {"regime": "PANIC", "regime_score": 10.0}

        rec = generate_recommendation(
            symbol="HPG",
            company_name="Hòa Phát",
            sector="Thép",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=regime_panic,
        )

        self.assertEqual(rec["action"], "AVOID")

    def test_missing_data_returns_avoid_with_nulls(self):
        rec = generate_recommendation(
            symbol="VCB",
            company_name="Vietcombank",
            sector="Ngân hàng",
            exchange="HOSE",
            df_stock=None,
            market_regime_info={"regime": "DEFENSIVE"},
        )

        self.assertEqual(rec["action"], "AVOID")
        self.assertEqual(rec["data_quality"], "INSUFFICIENT")
        self.assertIsNone(rec["signal_score"])
        self.assertIsNone(rec["alpha_score"])
        self.assertIsNone(rec["risk_metrics"]["var_t25"])
        self.assertIsNone(rec["trade_plan"]["current_price"])

    def test_market_regime_propagation_across_regimes(self):
        """Verify normalization uses explicitly supplied market regime across all regimes."""
        regimes = ["STRONG_BULL", "BULL", "NEUTRAL", "BEAR", "PANIC"]
        scores = {}

        for regime in regimes:
            recs = [
                {
                    "alpha_score": 80.0,
                    "risk_metrics": {
                        "avg_value_20d": 10.0,
                        "volatility_60d": 0.20,
                        "max_drawdown": -0.15,
                        "liquidity_score": None,
                    },
                }
            ]
            norm = normalize_universe_liquidity_scores(recs, market_regime=regime)
            scores[regime] = norm[0]["risk_adjusted_alpha"]

        self.assertGreater(scores["STRONG_BULL"], scores["BULL"])
        self.assertGreater(scores["BULL"], scores["NEUTRAL"])
        self.assertGreater(scores["NEUTRAL"], scores["BEAR"])
        self.assertGreater(scores["BEAR"], scores["PANIC"])

    def test_individual_recommendation_regime_cannot_override_explicit_regime(self):
        """Verify recommendation's inner 'market_regime' key cannot override explicit parameter."""
        recs = [
            {
                "market_regime": "DEFENSIVE",  # Inner regime attempts to override
                "alpha_score": 80.0,
                "risk_metrics": {
                    "avg_value_20d": 10.0,
                    "volatility_60d": 0.20,
                    "max_drawdown": -0.15,
                    "liquidity_score": None,
                },
            }
        ]

        norm = normalize_universe_liquidity_scores(recs, market_regime="STRONG_BULL")
        expected_score = calculate_risk_adjusted_alpha(
            alpha_score=80.0,
            regime="STRONG_BULL",
            volatility_60d=0.20,
            max_drawdown=-0.15,
            liquidity_score=100.0,
        )

        self.assertEqual(norm[0]["risk_adjusted_alpha"], expected_score)
        self.assertNotEqual(
            norm[0]["risk_adjusted_alpha"],
            calculate_risk_adjusted_alpha(
                alpha_score=80.0,
                regime="DEFENSIVE",
                volatility_60d=0.20,
                max_drawdown=-0.15,
                liquidity_score=100.0,
            ),
        )

    def test_invalid_market_regime_raises_error(self):
        recs = [
            {
                "alpha_score": 80.0,
                "risk_metrics": {
                    "avg_value_20d": 10.0,
                },
            }
        ]

        with self.assertRaises(ValueError):
            normalize_universe_liquidity_scores(recs, market_regime="INVALID_REGIME")

        with self.assertRaises(ValueError):
            normalize_universe_liquidity_scores(recs, market_regime=None)

        with self.assertRaises(ValueError):
            calculate_risk_adjusted_alpha(alpha_score=80.0, regime="UNKNOWN")

    @patch("scripts.generate_report.get_historical_data")
    @patch("scripts.generate_report.detect_market_regime")
    def test_run_pipeline_market_regime_propagation(self, mock_detect, mock_get_hist):
        """Integration test verifying canonical market regime flow in run_pipeline().

        Flow: detect_market_regime() -> generate_recommendation() -> normalize_universe_liquidity_scores() -> risk_adjusted_alpha.
        Ensures top-level market regime is propagated and used for final risk_adjusted_alpha without falling back to DEFENSIVE.
        """
        from scripts.generate_report import run_pipeline

        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        close_prices = np.linspace(20.0, 35.0, n)
        df_sample = pd.DataFrame(
            {
                "time": dates,
                "open": close_prices - 0.2,
                "high": close_prices + 0.5,
                "low": close_prices - 0.5,
                "close": close_prices,
                "volume": [500000] * n,
            }
        )
        mock_get_hist.return_value = (df_sample, "OK", [])

        # Test case A: Market regime detected as STRONG_BULL
        mock_detect.return_value = {
            "regime": "STRONG_BULL",
            "regime_score": 85.0,
            "confidence": 0.85,
            "metrics": {"vnindex_value": 1200.0, "vnindex_change_pct": 1.5},
        }

        recs_data_bull, _, _ = run_pipeline(update_data=False)
        self.assertEqual(recs_data_bull["market"]["regime"], "STRONG_BULL")

        rec_fpt_bull = next(r for r in recs_data_bull["recommendations"] if r["symbol"] == "FPT")
        self.assertIsNotNone(rec_fpt_bull["risk_adjusted_alpha"])

        expected_strong_bull_alpha = calculate_risk_adjusted_alpha(
            alpha_score=rec_fpt_bull["alpha_score"],
            regime="STRONG_BULL",
            volatility_60d=rec_fpt_bull["risk_metrics"]["volatility_60d"],
            max_drawdown=rec_fpt_bull["risk_metrics"]["max_drawdown"],
            liquidity_score=rec_fpt_bull["risk_metrics"]["liquidity_score"],
        )
        defensive_fallback_alpha = calculate_risk_adjusted_alpha(
            alpha_score=rec_fpt_bull["alpha_score"],
            regime="DEFENSIVE",
            volatility_60d=rec_fpt_bull["risk_metrics"]["volatility_60d"],
            max_drawdown=rec_fpt_bull["risk_metrics"]["max_drawdown"],
            liquidity_score=rec_fpt_bull["risk_metrics"]["liquidity_score"],
        )

        self.assertEqual(rec_fpt_bull["risk_adjusted_alpha"], expected_strong_bull_alpha)
        self.assertNotEqual(rec_fpt_bull["risk_adjusted_alpha"], defensive_fallback_alpha)

        # Test case B: Market regime detected as BEAR
        mock_detect.return_value = {
            "regime": "BEAR",
            "regime_score": 30.0,
            "confidence": 0.70,
            "metrics": {"vnindex_value": 1100.0, "vnindex_change_pct": -2.0},
        }

        recs_data_bear, _, _ = run_pipeline(update_data=False)
        self.assertEqual(recs_data_bear["market"]["regime"], "BEAR")

        rec_fpt_bear = next(r for r in recs_data_bear["recommendations"] if r["symbol"] == "FPT")
        expected_bear_alpha = calculate_risk_adjusted_alpha(
            alpha_score=rec_fpt_bear["alpha_score"],
            regime="BEAR",
            volatility_60d=rec_fpt_bear["risk_metrics"]["volatility_60d"],
            max_drawdown=rec_fpt_bear["risk_metrics"]["max_drawdown"],
            liquidity_score=rec_fpt_bear["risk_metrics"]["liquidity_score"],
        )

        self.assertEqual(rec_fpt_bear["risk_adjusted_alpha"], expected_bear_alpha)
        self.assertLess(rec_fpt_bear["risk_adjusted_alpha"], rec_fpt_bull["risk_adjusted_alpha"])


if __name__ == "__main__":
    unittest.main()
