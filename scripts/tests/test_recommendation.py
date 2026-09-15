"""Unit tests for VN Invest Signal Engine in scripts/lib/recommendation.py."""

import math
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts.lib.features import calculate_single_tf_indicators, detect_divergence
from scripts.lib.recommendation import (
    DIVERGENCE_TIMEFRAME_WEIGHTS,
    SIGNAL_WEIGHTS,
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
from scripts.lib.risk import normalize_universe_liquidity_scores


class TestVNInvestSignalEngine(unittest.TestCase):
    def test_signal_weights_sum_to_one(self):
        """Verify centralized signal weights sum to 1.0."""
        weight_sum = sum(SIGNAL_WEIGHTS.values())
        self.assertAlmostEqual(weight_sum, 1.0, places=5)

    def test_divergence_weights_sum_to_one(self):
        """Verify divergence timeframe weights sum to 1.0."""
        weight_sum = sum(DIVERGENCE_TIMEFRAME_WEIGHTS.values())
        self.assertAlmostEqual(weight_sum, 1.0, places=5)

    def test_zero_and_missing_volume_handling(self):
        """Regression test P0: Invalid/zero/missing volume must produce volume_score = None."""
        # Zero volume ratio -> None
        self.assertIsNone(calculate_volume_score(0.0))
        # Negative volume ratio -> None
        self.assertIsNone(calculate_volume_score(-0.5))
        # NaN / Inf -> None
        self.assertIsNone(calculate_volume_score(float("nan")))
        self.assertIsNone(calculate_volume_score(float("inf")))
        # None -> None
        self.assertIsNone(calculate_volume_score(None))

        # Valid volume ratio -> score in [0, 100]
        self.assertEqual(calculate_volume_score(1.5), 85.0)

    def test_missing_and_invalid_previous_macd_handling(self):
        """Regression test P0: Missing/invalid previous MACD must NOT be treated as 0.0."""
        # Current hist valid, previous hist missing -> uses fallback +15.0 for positive hist
        score_no_prev = calculate_momentum_score(rsi=50.0, macd_hist=0.5, prev_macd_hist=None)
        score_prev_zero = calculate_momentum_score(rsi=50.0, macd_hist=0.5, prev_macd_hist=0.0)

        # previous_macd_hist = None must NOT behave as previous_macd_hist = 0.0 (which would give +25.0)
        self.assertNotEqual(score_no_prev, score_prev_zero)
        self.assertEqual(score_no_prev, 85.0)  # 50 + 20 (RSI) + 15 (hist > 0)
        self.assertEqual(score_prev_zero, 95.0)  # 50 + 20 (RSI) + 25 (hist > prev_hist)

        # Invalid NaN / Inf previous MACD
        score_nan_prev = calculate_momentum_score(
            rsi=50.0, macd_hist=0.5, prev_macd_hist=float("nan")
        )
        self.assertEqual(score_nan_prev, score_no_prev)

    def test_insufficient_data_semantics(self):
        """Regression test P1: Less than 3 components must produce data_quality = INSUFFICIENT, signal_score = None, action = AVOID."""
        # 0 components available
        score, _components, dq = calculate_signal_score(None, None, None, None, None)
        self.assertIsNone(score)
        self.assertEqual(dq, "INSUFFICIENT")

        # 1 component available
        score, _components, dq = calculate_signal_score(100.0, None, None, None, None)
        self.assertIsNone(score)
        self.assertEqual(dq, "INSUFFICIENT")

        # 2 components available
        score, _components, dq = calculate_signal_score(100.0, 90.0, None, None, None)
        self.assertIsNone(score)
        self.assertEqual(dq, "INSUFFICIENT")

        # Action classification check for None score
        self.assertEqual(classify_action(None, "STRONG_BULL"), "AVOID")

        # Risk-adjusted score for None score
        self.assertIsNone(calculate_risk_adjusted_score(None, "STRONG_BULL"))

        # 3 components available -> PARTIAL
        score, _components, dq = calculate_signal_score(100.0, 90.0, 80.0, None, None)
        self.assertIsNotNone(score)
        self.assertEqual(dq, "PARTIAL")

        # 5 components available -> SUFFICIENT
        score, _components, dq = calculate_signal_score(100.0, 90.0, 80.0, 70.0, 60.0)
        self.assertIsNotNone(score)
        self.assertEqual(dq, "SUFFICIENT")

    def test_confidence_reflects_signal_agreement(self):
        """Test P1: Confidence increases with high signal agreement and decreases with strong signal conflict/dispersion."""
        from scripts.lib.recommendation import calculate_confidence

        risk_metrics = {"volatility_60d": 0.15, "max_drawdown": -0.10}

        # High agreement: std dev < 12 (e.g., 80, 82, 78, 84, 81)
        high_agreement_comp = {
            "trend": 80.0,
            "momentum": 82.0,
            "volume": 78.0,
            "relative_strength": 84.0,
            "divergence": 81.0,
        }
        conf_agree = calculate_confidence("SUFFICIENT", high_agreement_comp, risk_metrics, rsi=50.0)

        # Strong disagreement / dispersion: e.g., 100, 0, 100, 0, 100
        conflict_comp = {
            "trend": 100.0,
            "momentum": 0.0,
            "volume": 100.0,
            "relative_strength": 0.0,
            "divergence": 100.0,
        }
        conf_conflict = calculate_confidence("SUFFICIENT", conflict_comp, risk_metrics, rsi=50.0)

        self.assertGreater(conf_agree, conf_conflict)
        self.assertGreaterEqual(conf_agree, 0.10)
        self.assertLessEqual(conf_agree, 0.95)
        self.assertGreaterEqual(conf_conflict, 0.10)
        self.assertLessEqual(conf_conflict, 0.95)

    def test_divergence_timeframe_weighting_and_conflict(self):
        """Test P1: Divergence timeframe weighting hierarchy (1D > 1W > 1M) and conflict handling."""
        # 1D Bullish only
        tf_1d_bull = {
            "1d": {"available": True, "divergence": {"rsi_bullish": True, "macd_bullish": False}},
            "1w": {"available": True, "divergence": {"rsi_bullish": False, "macd_bullish": False}},
            "1m": {"available": True, "divergence": {"rsi_bullish": False, "macd_bullish": False}},
        }
        score_1d = calculate_divergence_score(tf_1d_bull)

        # 1M Bullish only
        tf_1m_bull = {
            "1d": {"available": True, "divergence": {"rsi_bullish": False, "macd_bullish": False}},
            "1w": {"available": True, "divergence": {"rsi_bullish": False, "macd_bullish": False}},
            "1m": {"available": True, "divergence": {"rsi_bullish": True, "macd_bullish": False}},
        }
        score_1m = calculate_divergence_score(tf_1m_bull)

        # 1D should have higher impact than 1M
        self.assertGreater(score_1d, score_1m)

        # Conflict on same timeframe (both bullish and bearish)
        tf_conflict = {
            "1d": {"available": True, "divergence": {"rsi_bullish": True, "rsi_bearish": True}},
            "1w": {"available": True, "divergence": {"rsi_bullish": False, "macd_bullish": False}},
            "1m": {"available": True, "divergence": {"rsi_bullish": False, "macd_bullish": False}},
        }
        score_conflict = calculate_divergence_score(tf_conflict)
        self.assertEqual(score_conflict, 45.0)  # 90 * 0.5 * 0.40 + 50 * 0.30 + 50 * 0.20 = 45.0

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
        close_bull = np.linspace(20000.0, 35000.0, n)
        df_bull = pd.DataFrame(
            {
                "time": dates,
                "open": close_bull - 200.0,
                "high": close_bull + 500.0,
                "low": close_bull - 500.0,
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
        self.assertIsNotNone(rec["risk_adjusted_score"])
        self.assertIsNotNone(rec["confidence"])
        self.assertGreaterEqual(rec["confidence"], 0.10)
        self.assertLessEqual(rec["confidence"], 0.95)
        self.assertIsInstance(rec["score_components"], dict)
        self.assertIsInstance(rec["invalidation"], list)
        self.assertIn("1H", rec["divergence"])

    def test_risk_adjusted_score_formula(self):
        """Verify risk-adjusted score deterministic calculation."""
        score = calculate_risk_adjusted_score(
            signal_score=80.0,
            regime="STRONG_BULL",
            volatility_60d=0.15,
            max_drawdown=-0.10,
            liquidity_score=90.0,
        )
        self.assertGreaterEqual(score, 70.0)
        self.assertLessEqual(score, 100.0)

        # High volatility and drawdown penalty check
        score_high_risk = calculate_risk_adjusted_score(
            signal_score=80.0,
            regime="BEAR",
            volatility_60d=0.45,
            max_drawdown=-0.35,
            liquidity_score=20.0,
        )
        self.assertLess(score_high_risk, score)

    def test_risk_adjusted_score_across_regimes(self):
        """Verify risk_adjusted_score calculation across all market regimes and after universe normalization."""
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

        regimes = ["STRONG_BULL", "BULL", "NEUTRAL", "DEFENSIVE", "BEAR", "PANIC"]
        for r_str in regimes:
            rec = generate_recommendation(
                symbol="FPT",
                company_name="FPT",
                sector="Tech",
                exchange="HOSE",
                df_stock=df_bull,
                market_regime_info={"regime": r_str, "regime_score": 50.0},
            )

            self.assertIsNotNone(rec["risk_adjusted_score"])

            norm_recs = normalize_universe_liquidity_scores([rec], market_regime=r_str)
            self.assertIsNotNone(norm_recs[0]["risk_adjusted_score"])

    def test_missing_atr_trade_plan_behavior(self):
        """Regression test P1: Missing ATR does not raise error and produces valid trade plan bounds."""
        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        close_bull = np.linspace(20000.0, 35000.0, n)
        df_bull = pd.DataFrame(
            {
                "time": dates,
                "open": close_bull - 200.0,
                "high": close_bull + 500.0,
                "low": close_bull - 500.0,
                "close": close_bull,
                "volume": [500000] * n,
                "atr": [None] * n,  # Explicitly missing ATR
            }
        )

        rec = generate_recommendation(
            symbol="FPT",
            company_name="FPT",
            sector="Tech",
            exchange="HOSE",
            df_stock=df_bull,
            market_regime_info={"regime": "STRONG_BULL"},
        )

        tp = rec["trade_plan"]
        if rec["action"] in ["BUY", "WATCH"]:
            self.assertIsNotNone(tp["stop_loss"])
            self.assertLess(tp["stop_loss"], tp["entry_low"])
            self.assertGreater(tp["tp1"], tp["entry_high"])
            self.assertGreaterEqual(tp["tp2"], tp["tp1"])

    def test_trade_plan_invariants(self):
        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        close_bull = np.linspace(20000.0, 35000.0, n)
        df_bull = pd.DataFrame(
            {
                "time": dates,
                "open": close_bull - 200.0,
                "high": close_bull + 500.0,
                "low": close_bull - 500.0,
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
            self.assertGreater(tp["tp1"], tp["entry_high"])
            self.assertGreaterEqual(tp["tp2"], tp["tp1"])
            self.assertGreater(tp["risk_reward"], 0.0)
            self.assertGreaterEqual(tp["position_percent"], 0.0)
            self.assertLessEqual(tp["position_percent"], 100.0)
        else:
            self.assertIsNone(tp["entry_low"])
            self.assertIsNone(tp["stop_loss"])

    def test_anti_lookahead_module_level_regression(self):
        """Module-level regression test for anti-lookahead bias (PR #83).

        Note on Pipeline Entry Point & Temporal Isolation Scope:
        The repository's current report generation pipeline (`run_pipeline` in `scripts/generate_report.py`
        and `generate_recommendation` in `scripts/lib/recommendation.py`) evaluates the latest state of
        supplied DataFrames without a native temporal `as_of` date cutoff parameter.
        Therefore, this regression test operates at the highest available module-level boundaries
        (`calculate_single_tf_indicators` and `generate_recommendation`).

        Test Logic:
        1. Dataset A: Clean historical dataset ending at date T.
        2. Dataset B: Dataset A + future sessions (T+1, T+2) containing an extreme market crash.
        3. Indicator Causality: Computes indicators on full Dataset B and asserts that indicator values
           extracted at date T match Dataset A exactly.
        4. Recommendation Output at T: Asserts identity between Dataset A and Dataset B (sliced at T)
           across key quantitative fields:
           - indicators (ma20, ma50, rsi, macd, hist, atr, daily_return)
           - action / direction
           - signal score & risk_adjusted_score
           - score components
           - market regime & regime_score
           - risk metrics (var_t25, es_t25, volatility_60d, max_drawdown, avg_value_20d)
           - trade plan (entry_low, entry_high, stop_loss, tp1, tp2, risk_reward, position_percent)
        """
        n = 50
        dates_a = pd.date_range("2026-01-01", periods=n, freq="D")
        close_a = np.linspace(20000.0, 35000.0, n)

        df_stock_a = pd.DataFrame(
            {
                "time": dates_a,
                "open": close_a - 200.0,
                "high": close_a + 500.0,
                "low": close_a - 500.0,
                "close": close_a,
                "volume": [500000] * n,
            }
        )

        close_vn_a = np.linspace(1200.0, 1300.0, n)
        df_vnindex_a = pd.DataFrame(
            {
                "time": dates_a,
                "open": close_vn_a - 5.0,
                "high": close_vn_a + 10.0,
                "low": close_vn_a - 10.0,
                "close": close_vn_a,
                "volume": [10000000] * n,
            }
        )
        df_vn30_a = df_vnindex_a.copy()

        date_t = dates_a[-1]

        # Calculate baseline results on Dataset A (data up to date T)
        ind_a = calculate_single_tf_indicators(df_stock_a)
        ind_a_at_t = ind_a.iloc[-1]

        regime_a = detect_market_regime(
            df_vnindex=df_vnindex_a, df_vn30=df_vn30_a, breadth_ratio=0.60
        )

        rec_a = generate_recommendation(
            symbol="FPT",
            company_name="Công ty FPT",
            sector="Công nghệ",
            exchange="HOSE",
            df_stock=df_stock_a,
            market_regime_info=regime_a,
            df_vnindex=df_vnindex_a,
        )

        # Construct Dataset B: Dataset A + future rows T+1, T+2 (extreme future crash)
        future_rows = pd.DataFrame(
            {
                "time": [pd.Timestamp("2026-02-20"), pd.Timestamp("2026-02-21")],
                "open": [25000.0, 20000.0],
                "high": [25000.0, 20000.0],
                "low": [20000.0, 15000.0],
                "close": [20000.0, 15000.0],
                "volume": [5000000, 8000000],
            }
        )

        df_stock_b = pd.concat([df_stock_a, future_rows], ignore_index=True)
        df_vnindex_b = pd.concat([df_vnindex_a, future_rows], ignore_index=True)
        df_vn30_b = df_vnindex_b.copy()

        # 1. Verify Indicator Causality: Indicator values at row T in full Dataset B match Dataset A at T
        ind_b_full = calculate_single_tf_indicators(df_stock_b)
        ind_b_at_t = ind_b_full[ind_b_full["time"] == date_t].iloc[0]

        for field in ["ma20", "ma50", "rsi", "macd", "hist", "atr", "daily_return"]:
            val_a = ind_a_at_t[field]
            val_b = ind_b_at_t[field]
            if pd.isna(val_a):
                self.assertTrue(pd.isna(val_b))
            else:
                self.assertAlmostEqual(
                    val_a,
                    val_b,
                    places=5,
                    msg=f"Indicator '{field}' at date T changed when future rows were added!",
                )

        # 2. Slice Dataset B at date T and verify recommendation identity
        df_stock_b_sliced = df_stock_b[df_stock_b["time"] <= date_t]
        df_vnindex_b_sliced = df_vnindex_b[df_vnindex_b["time"] <= date_t]
        df_vn30_b_sliced = df_vn30_b[df_vn30_b["time"] <= date_t]

        regime_b = detect_market_regime(
            df_vnindex=df_vnindex_b_sliced,
            df_vn30=df_vn30_b_sliced,
            breadth_ratio=0.60,
        )

        rec_b = generate_recommendation(
            symbol="FPT",
            company_name="Công ty FPT",
            sector="Công nghệ",
            exchange="HOSE",
            df_stock=df_stock_b_sliced,
            market_regime_info=regime_b,
            df_vnindex=df_vnindex_b_sliced,
        )

        # 3. Assert equality across key quantitative fields at date T
        self.assertEqual(regime_a["regime"], regime_b["regime"])
        self.assertEqual(regime_a["regime_score"], regime_b["regime_score"])

        self.assertEqual(rec_a["action"], rec_b["action"])
        self.assertEqual(rec_a["signal_score"], rec_b["signal_score"])
        self.assertEqual(rec_a["risk_adjusted_score"], rec_b["risk_adjusted_score"])
        self.assertEqual(rec_a["score_components"], rec_b["score_components"])
        self.assertEqual(rec_a["risk_metrics"], rec_b["risk_metrics"])
        self.assertEqual(rec_a["trade_plan"], rec_b["trade_plan"])

    def test_divergence_requires_future_pivot_confirmation(self):
        """Targeted temporal-causality regression test for divergence pivot confirmation.

        CONFIRMED TEMPORAL DEPENDENCY IN PIVOT DETECTION:
        `detect_divergence()` in `scripts/lib/features.py` identifies local troughs and peaks
        using a 5-bar window check (`i - 2`, `i - 1`, `i`, `i + 1`, `i + 2`).
        Consequently, confirming a pivot at historical timestamp T requires two subsequent bars (`i + 1` and `i + 2`).

        Technical Interpretation & Scope Boundary:
        - This test demonstrates that `detect_divergence()` has a non-causal temporal dependency at the
          pivot timestamp itself due to pivot-confirmation lag.
        - This test alone does NOT prove that live production recommendations at time T leak future market
          data, because live recommendations are evaluated on historical data available up to time T.
        - The test exercises `detect_divergence` directly on Dataset B (keeping future rows T+1, T+2 present
          during calculation) vs Dataset A (ending at T).

        Test Logic:
        1. Dataset A: Deterministic OHLCV dataset ending at date T (index 28).
           At date T, trough 2 cannot be confirmed because subsequent bars T+1 and T+2 do not exist in Dataset A.
           `detect_divergence(df_a)` returns `macd_bullish = False`.
        2. Dataset B: Dataset A + future sessions T+1 (index 29) and T+2 (index 30) with rising prices.
           Passing full Dataset B (with future rows present during execution) allows `detect_divergence`
           to evaluate index 28 using bars T+1 and T+2, confirming trough 2 and returning `macd_bullish = True`.
        3. Assertion: `div_a["macd_bullish"] != div_b["macd_bullish"]` accurately captures the temporal dependency.

        Per PR #83 scope restrictions, production quantitative logic is intentionally NOT modified in this PR.
        """
        n = 29  # Rows 0..28 (date T is index 28)
        dates_a = pd.date_range("2026-01-01", periods=n, freq="D")

        close_a = np.linspace(30000.0, 26000.0, n)
        low_a = close_a - 500.0
        high_a = close_a + 500.0

        # Dip 1 at index 10 (trough 1)
        close_a[10] = 23000.0
        low_a[10] = 22000.0

        # Dip 2 at index 28 (date T, trough 2 candidate)
        close_a[28] = 25000.0
        low_a[28] = 22100.0

        df_a = pd.DataFrame(
            {
                "time": dates_a,
                "open": close_a,
                "high": high_a,
                "low": low_a,
                "close": close_a,
                "volume": [500000] * n,
            }
        )
        df_a = calculate_single_tf_indicators(df_a)
        div_a = detect_divergence(df_a)

        # Baseline on Dataset A: date T cannot confirm trough 2 -> macd_bullish is False
        self.assertFalse(div_a["macd_bullish"])

        # Dataset B: Dataset A + future rows T+1 (index 29) and T+2 (index 30)
        dates_b = pd.date_range("2026-01-01", periods=n + 2, freq="D")
        close_b = list(close_a) + [27000.0, 28000.0]
        low_b = list(low_a) + [26000.0, 27000.0]
        high_b = list(high_a) + [28000.0, 29000.0]

        df_b = pd.DataFrame(
            {
                "time": dates_b,
                "open": close_b,
                "high": high_b,
                "low": low_b,
                "close": close_b,
                "volume": [500000] * (n + 2),
            }
        )
        df_b = calculate_single_tf_indicators(df_b)
        div_b = detect_divergence(df_b)

        # On full Dataset B (including future rows T+1, T+2): date T is now confirmed as trough 2 -> macd_bullish is True
        self.assertTrue(div_b["macd_bullish"])

        # Proves future rows T+1, T+2 change historical divergence outputs evaluated at T
        self.assertNotEqual(
            div_a["macd_bullish"],
            div_b["macd_bullish"],
            "Confirmed lookahead dependency: detect_divergence() outputs differ at date T when future rows T+1, T+2 are present!",
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

        # Volume score should be None due to 0 volume, leaving 4 available components -> PARTIAL data quality
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
        self.assertIsNone(rec["risk_metrics"]["var_t25"])
        self.assertIsNone(rec["trade_plan"]["current_price"])

    def test_market_regime_propagation_across_regimes(self):
        """Verify normalization uses explicitly supplied market regime across all regimes."""
        regimes = ["STRONG_BULL", "BULL", "NEUTRAL", "BEAR", "PANIC"]
        scores = {}

        for regime in regimes:
            recs = [
                {
                    "signal_score": 80.0,
                    "risk_metrics": {
                        "avg_value_20d": 10.0,
                        "volatility_60d": 0.20,
                        "max_drawdown": -0.15,
                        "liquidity_score": None,
                    },
                }
            ]
            norm = normalize_universe_liquidity_scores(recs, market_regime=regime)
            scores[regime] = norm[0]["risk_adjusted_score"]

        self.assertGreater(scores["STRONG_BULL"], scores["BULL"])
        self.assertGreater(scores["BULL"], scores["NEUTRAL"])
        self.assertGreater(scores["NEUTRAL"], scores["BEAR"])
        self.assertGreater(scores["BEAR"], scores["PANIC"])

    def test_individual_recommendation_regime_cannot_override_explicit_regime(self):
        """Verify recommendation's inner 'market_regime' key cannot override explicit parameter."""
        recs = [
            {
                "market_regime": "DEFENSIVE",  # Inner regime attempts to override
                "signal_score": 80.0,
                "risk_metrics": {
                    "avg_value_20d": 10.0,
                    "volatility_60d": 0.20,
                    "max_drawdown": -0.15,
                    "liquidity_score": None,
                },
            }
        ]

        norm = normalize_universe_liquidity_scores(recs, market_regime="STRONG_BULL")
        expected_score = calculate_risk_adjusted_score(
            signal_score=80.0,
            regime="STRONG_BULL",
            volatility_60d=0.20,
            max_drawdown=-0.15,
            liquidity_score=100.0,
        )

        self.assertEqual(norm[0]["risk_adjusted_score"], expected_score)
        self.assertNotEqual(
            norm[0]["risk_adjusted_score"],
            calculate_risk_adjusted_score(
                signal_score=80.0,
                regime="DEFENSIVE",
                volatility_60d=0.20,
                max_drawdown=-0.15,
                liquidity_score=100.0,
            ),
        )

    def test_invalid_market_regime_raises_error(self):
        recs = [
            {
                "signal_score": 80.0,
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
            calculate_risk_adjusted_score(signal_score=80.0, regime="UNKNOWN")

    @patch("scripts.generate_report.get_historical_data")
    @patch("scripts.generate_report.detect_market_regime")
    def test_run_pipeline_market_regime_propagation(self, mock_detect, mock_get_hist):
        """Integration test verifying canonical market regime flow in run_pipeline().

        Flow: detect_market_regime() -> generate_recommendation() -> normalize_universe_liquidity_scores() -> risk_adjusted_score.
        Ensures top-level market regime is propagated and used for final risk_adjusted_score without falling back to DEFENSIVE.
        """
        from scripts.generate_report import run_pipeline

        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        close_prices = np.linspace(20000.0, 35000.0, n)
        df_sample = pd.DataFrame(
            {
                "time": dates,
                "open": close_prices - 200.0,
                "high": close_prices + 500.0,
                "low": close_prices - 500.0,
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
        self.assertIsNotNone(rec_fpt_bull["risk_adjusted_score"])

        expected_strong_bull_score = calculate_risk_adjusted_score(
            signal_score=rec_fpt_bull["signal_score"],
            regime="STRONG_BULL",
            volatility_60d=rec_fpt_bull["risk_metrics"]["volatility_60d"],
            max_drawdown=rec_fpt_bull["risk_metrics"]["max_drawdown"],
            liquidity_score=rec_fpt_bull["risk_metrics"]["liquidity_score"],
        )
        defensive_fallback_score = calculate_risk_adjusted_score(
            signal_score=rec_fpt_bull["signal_score"],
            regime="DEFENSIVE",
            volatility_60d=rec_fpt_bull["risk_metrics"]["volatility_60d"],
            max_drawdown=rec_fpt_bull["risk_metrics"]["max_drawdown"],
            liquidity_score=rec_fpt_bull["risk_metrics"]["liquidity_score"],
        )

        self.assertEqual(rec_fpt_bull["risk_adjusted_score"], expected_strong_bull_score)
        self.assertNotEqual(rec_fpt_bull["risk_adjusted_score"], defensive_fallback_score)

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
        expected_bear_score = calculate_risk_adjusted_score(
            signal_score=rec_fpt_bear["signal_score"],
            regime="BEAR",
            volatility_60d=rec_fpt_bear["risk_metrics"]["volatility_60d"],
            max_drawdown=rec_fpt_bear["risk_metrics"]["max_drawdown"],
            liquidity_score=rec_fpt_bear["risk_metrics"]["liquidity_score"],
        )

        self.assertEqual(rec_fpt_bear["risk_adjusted_score"], expected_bear_score)
        self.assertLess(rec_fpt_bear["risk_adjusted_score"], rec_fpt_bull["risk_adjusted_score"])


if __name__ == "__main__":
    unittest.main()
