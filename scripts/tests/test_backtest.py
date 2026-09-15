"""Unit Test Suite for Deterministic No-Lookahead Backtesting Framework."""

import unittest

import pandas as pd

from scripts.lib.backtest import (
    BacktestResult,
    BacktestSignal,
    ForwardOutcome,
    aggregate_backtest_results,
    evaluate_forward_outcomes,
    get_as_of_dataset,
    run_backtest_for_symbol,
)


def generate_synthetic_ohlcv(
    num_days: int = 100,
    start_date: str = "2025-01-01",
    base_price: float = 50.0,
    daily_trend: float = 0.001,
) -> pd.DataFrame:
    """Generate deterministic synthetic OHLCV DataFrame for testing."""
    dates = pd.date_range(start=start_date, periods=num_days, freq="B")
    data = []

    price = base_price
    for i, dt in enumerate(dates):
        # Deterministic price curve
        price = price * (1.0 + daily_trend + 0.005 * math_sin(i))
        close = round(price, 2)
        open_p = round(close * 0.995, 2)
        high = round(close * 1.01, 2)
        low = round(close * 0.99, 2)
        volume = 1_000_000 + (i % 10) * 50_000

        data.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

    return pd.DataFrame(data)


def math_sin(x: float) -> float:
    """Simple deterministic sine helper using Taylor series expansion to avoid random noise."""
    import math

    return math.sin(x)


class TestBacktestFramework(unittest.TestCase):
    """Test suite verifying backtesting framework requirements."""

    def setUp(self):
        self.df_stock = generate_synthetic_ohlcv(
            num_days=100, start_date="2025-01-01", base_price=50.0, daily_trend=0.002
        )
        self.evaluation_date = self.df_stock["date"].iloc[50]  # T = day 50

    def test_a_basic_forward_return(self):
        """Test A: Basic forward return calculation (T = 100, T+5 = 110 -> +10%)."""
        dates = pd.date_range("2025-01-01", periods=10, freq="B").strftime("%Y-%m-%d")
        prices = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0, 116.0, 118.0]

        df_synth = pd.DataFrame(
            {
                "date": dates,
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [100000] * 10,
            }
        )

        eval_d = dates[0]  # T = 0 (price = 100.0)
        # T+5 is index 5 (price = 110.0)
        outcome = evaluate_forward_outcomes(df_synth, eval_d, horizons=[5], action="BUY")

        self.assertTrue(outcome.availability[5])
        self.assertIsNotNone(outcome.returns[5])
        self.assertAlmostEqual(outcome.returns[5], 0.10, places=4)
        self.assertAlmostEqual(outcome.strategy_returns[5], 0.10, places=4)

    def test_b_horizon_correctness(self):
        """Test B: Horizon correctness (5D, 10D, 20D index mapping)."""
        dates = pd.date_range("2025-01-01", periods=30, freq="B").strftime("%Y-%m-%d")
        # Prices increase linearly by 1.0 each session
        prices = [50.0 + float(i) for i in range(30)]

        df_synth = pd.DataFrame(
            {
                "date": dates,
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [100000] * 30,
            }
        )

        eval_d = dates[2]  # T = index 2 (Price = 52.0)
        # T+5 = index 7 (Price = 57.0) -> return = (57-52)/52 = 5/52 = 0.0961538
        # T+10 = index 12 (Price = 62.0) -> return = (62-52)/52 = 10/52 = 0.1923077
        # T+20 = index 22 (Price = 72.0) -> return = (72-52)/52 = 20/52 = 0.3846154

        outcome = evaluate_forward_outcomes(df_synth, eval_d, horizons=[5, 10, 20], action="BUY")

        self.assertAlmostEqual(outcome.returns[5], 5.0 / 52.0, places=5)
        self.assertAlmostEqual(outcome.returns[10], 10.0 / 52.0, places=5)
        self.assertAlmostEqual(outcome.returns[20], 20.0 / 52.0, places=5)

    def test_c_insufficient_future_data(self):
        """Test C: Insufficient future data handling (no extrapolated outcomes)."""
        df_short = self.df_stock.iloc[:30].copy()  # Total 30 sessions
        eval_d = df_short["date"].iloc[25]  # T = index 25

        # Only 4 future sessions remain after T (26, 27, 28, 29)
        # 5D, 10D, 20D require index 30, 35, 45, which do not exist
        outcome = evaluate_forward_outcomes(df_short, eval_d, horizons=[5, 10, 20], action="BUY")

        for h in [5, 10, 20]:
            self.assertFalse(outcome.availability[h])
            self.assertIsNone(outcome.returns[h])
            self.assertIsNone(outcome.strategy_returns[h])

    def test_d_no_lookahead_critical(self):
        """Test D: Critical no-lookahead test. Mutating post-T data leaves signal at T unchanged."""
        eval_d = self.df_stock["date"].iloc[60]  # T = session index 60

        # Original run
        results_orig = run_backtest_for_symbol(
            symbol="TCB",
            df_stock=self.df_stock,
            evaluation_dates=[eval_d],
            company_name="Techcombank",
            sector="Banking",
            exchange="HOSE",
        )
        sig_orig = results_orig[0].signal

        # Create mutated dataset where all prices/volumes AFTER T are drastically modified
        df_mutated = self.df_stock.copy()
        post_t_mask = df_mutated["date"] > eval_d

        df_mutated.loc[post_t_mask, "close"] = df_mutated.loc[post_t_mask, "close"] * 5.0
        df_mutated.loc[post_t_mask, "open"] = df_mutated.loc[post_t_mask, "open"] * 5.0
        df_mutated.loc[post_t_mask, "high"] = df_mutated.loc[post_t_mask, "high"] * 5.0
        df_mutated.loc[post_t_mask, "low"] = df_mutated.loc[post_t_mask, "low"] * 5.0
        df_mutated.loc[post_t_mask, "volume"] = df_mutated.loc[post_t_mask, "volume"] * 10

        results_mutated = run_backtest_for_symbol(
            symbol="TCB",
            df_stock=df_mutated,
            evaluation_dates=[eval_d],
            company_name="Techcombank",
            sector="Banking",
            exchange="HOSE",
        )
        sig_mutated = results_mutated[0].signal

        # Signal generated at T must be 100% IDENTICAL
        self.assertEqual(sig_orig.action, sig_mutated.action)
        self.assertEqual(sig_orig.signal_score, sig_mutated.signal_score)
        self.assertEqual(sig_orig.confidence, sig_mutated.confidence)
        self.assertEqual(sig_orig.market_regime, sig_mutated.market_regime)
        self.assertEqual(sig_orig.risk_adjusted_score, sig_mutated.risk_adjusted_score)
        self.assertEqual(sig_orig.entry_price, sig_mutated.entry_price)
        self.assertEqual(sig_orig.score_components, sig_mutated.score_components)

        # However, forward outcomes AFTER T SHOULD differ
        outcome_orig = results_orig[0].outcome
        outcome_mutated = results_mutated[0].outcome
        self.assertNotEqual(outcome_orig.returns[5], outcome_mutated.returns[5])

    def test_e_determinism(self):
        """Test E: Determinism verification across multiple invocations."""
        eval_dates = [self.df_stock["date"].iloc[40], self.df_stock["date"].iloc[50]]

        run1 = run_backtest_for_symbol("VNM", self.df_stock, eval_dates)
        run2 = run_backtest_for_symbol("VNM", self.df_stock, eval_dates)

        self.assertEqual(len(run1), len(run2))
        for r1, r2 in zip(run1, run2, strict=True):
            self.assertEqual(r1.to_dict(), r2.to_dict())

    def test_f_direction_handling(self):
        """Test F: Direction handling (BUY, SELL, HOLD strategy returns)."""
        dates = pd.date_range("2025-01-01", periods=10, freq="B").strftime("%Y-%m-%d")
        prices = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0, 116.0, 118.0]

        df_synth = pd.DataFrame(
            {
                "date": dates,
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [100000] * 10,
            }
        )
        eval_d = dates[0]  # T = 0 (100.0), T+5 = index 5 (110.0) -> +10% return

        outcome_buy = evaluate_forward_outcomes(df_synth, eval_d, horizons=[5], action="BUY")
        outcome_sell = evaluate_forward_outcomes(df_synth, eval_d, horizons=[5], action="SELL")
        outcome_hold = evaluate_forward_outcomes(df_synth, eval_d, horizons=[5], action="HOLD")

        self.assertAlmostEqual(outcome_buy.returns[5], 0.10, places=4)

        # BUY strategy return = +10%
        self.assertAlmostEqual(outcome_buy.strategy_returns[5], 0.10, places=4)
        # SELL strategy return = -10%
        self.assertAlmostEqual(outcome_sell.strategy_returns[5], -0.10, places=4)
        # HOLD strategy return = 0%
        self.assertAlmostEqual(outcome_hold.strategy_returns[5], 0.0, places=4)

    def test_g_aggregation_metrics_exact_assertions(self):
        """Test G: Aggregation and breakdown metrics with exact numerical assertions."""
        # Create synthetic test signals and outcomes
        sig1 = BacktestSignal(
            symbol="AAA",
            evaluation_date="2025-01-10",
            action="BUY",
            signal_score=80.0,
            confidence=0.85,
            market_regime="BULL",
            risk_adjusted_score=80.0,
            data_quality="SUFFICIENT",
            model_version="2.0",
            entry_price=50.0,
        )
        out1 = ForwardOutcome(
            evaluation_date="2025-01-10",
            returns={5: 0.10, 10: 0.20, 20: None},
            availability={5: True, 10: True, 20: False},
            strategy_returns={5: 0.10, 10: 0.20, 20: None},
        )

        sig2 = BacktestSignal(
            symbol="BBB",
            evaluation_date="2025-01-10",
            action="SELL",
            signal_score=30.0,
            confidence=0.75,
            market_regime="BULL",
            risk_adjusted_score=30.0,
            data_quality="SUFFICIENT",
            model_version="2.0",
            entry_price=40.0,
        )
        out2 = ForwardOutcome(
            evaluation_date="2025-01-10",
            returns={5: 0.05, 10: -0.05, 20: None},
            availability={5: True, 10: True, 20: False},
            strategy_returns={5: -0.05, 10: 0.05, 20: None},
        )

        sig3 = BacktestSignal(
            symbol="CCC",
            evaluation_date="2025-01-10",
            action="HOLD",
            signal_score=50.0,
            confidence=0.65,
            market_regime="NEUTRAL",
            risk_adjusted_score=45.0,
            data_quality="SUFFICIENT",
            model_version="2.0",
            entry_price=30.0,
        )
        out3 = ForwardOutcome(
            evaluation_date="2025-01-10",
            returns={5: -0.02, 10: 0.01, 20: None},
            availability={5: True, 10: True, 20: False},
            strategy_returns={5: 0.0, 10: 0.0, 20: None},
        )

        results = [
            BacktestResult(signal=sig1, outcome=out1),
            BacktestResult(signal=sig2, outcome=out2),
            BacktestResult(signal=sig3, outcome=out3),
        ]

        summary = aggregate_backtest_results(results, horizons=[5, 10, 20])

        sig_stats = summary["signal_statistics"]
        self.assertEqual(sig_stats["total_signals"], 3)
        self.assertEqual(sig_stats["action_counts"]["BUY"], 1)
        self.assertEqual(sig_stats["action_counts"]["SELL"], 1)
        self.assertEqual(sig_stats["action_counts"]["HOLD"], 1)
        self.assertEqual(sig_stats["valid_outcome_counts"][5], 3)
        self.assertEqual(sig_stats["valid_outcome_counts"][20], 0)

        # Horizon 5 metrics
        m5 = summary["horizon_metrics"][5]
        # Forward returns: 0.10, 0.05, -0.02 -> mean = 0.13 / 3 = 0.043333
        self.assertAlmostEqual(m5["forward_return"]["mean"], 0.043333, places=5)
        self.assertAlmostEqual(m5["forward_return"]["min"], -0.02, places=4)
        self.assertAlmostEqual(m5["forward_return"]["max"], 0.10, places=4)

        # BUY hit rate: 1 BUY signal with fwd return 0.10 > 0 -> 1.0 (100%)
        self.assertEqual(m5["buy_hit_rate"], 1.0)
        # SELL hit rate: 1 SELL signal with fwd return 0.05 (not < 0) -> 0.0 (0%)
        self.assertEqual(m5["sell_hit_rate"], 0.0)
        # Combined directional hit rate: 1 hit out of 2 directional signals -> 0.5 (50%)
        self.assertEqual(m5["combined_directional_hit_rate"], 0.5)

        # Action breakdown
        act_bd = summary["breakdown_by_action"]
        self.assertIn("BUY", act_bd)
        self.assertIn("SELL", act_bd)
        self.assertEqual(act_bd["BUY"][5]["count"], 1)
        self.assertAlmostEqual(act_bd["BUY"][5]["stats"]["mean"], 0.10, places=4)

    def test_h_error_handling(self):
        """Test H: Error handling for invalid inputs."""
        # Empty DataFrame
        with self.assertRaises(ValueError):
            get_as_of_dataset(pd.DataFrame(), "2025-01-01")

        # Missing date column
        with self.assertRaises(ValueError):
            get_as_of_dataset(pd.DataFrame({"close": [10, 20]}), "2025-01-01")

        # Evaluation date not in dataset
        with self.assertRaises(ValueError):
            evaluate_forward_outcomes(self.df_stock, "2020-01-01")


if __name__ == "__main__":
    unittest.main()
