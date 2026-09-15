"""Unit Test Suite for Deterministic No-Lookahead Backtesting Framework."""

import math
import unittest

import pandas as pd

from scripts.lib.backtest import (
    BacktestResult,
    BacktestSignal,
    ForwardOutcome,
    aggregate_backtest_results,
    calculate_as_of_market_breadth,
    evaluate_forward_outcomes,
    get_as_of_dataset,
    run_backtest_for_symbol,
    run_backtest_for_universe,
)


def math_sin(x: float) -> float:
    """Simple deterministic sine helper using Taylor series expansion to avoid random noise."""
    return math.sin(x)


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


class TestBacktestFramework(unittest.TestCase):
    """Test suite verifying backtesting framework requirements."""

    def setUp(self):
        self.df_stock = generate_synthetic_ohlcv(
            num_days=100, start_date="2025-01-01", base_price=50.0, daily_trend=0.002
        )
        self.df_vnindex = generate_synthetic_ohlcv(
            num_days=100,
            start_date="2025-01-01",
            base_price=1200.0,
            daily_trend=0.001,
        )
        self.df_vn30 = generate_synthetic_ohlcv(
            num_days=100,
            start_date="2025-01-01",
            base_price=1250.0,
            daily_trend=0.001,
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

    def test_d_no_lookahead_stock_and_market_level_critical(self):
        """Test D: Critical market-level and stock-level no-lookahead regression test.

        Mutating post-T data in stock price, VNINDEX, VN30, and universe breadth
        leaves the market regime, breadth, and recommendation at T 100% identical.
        """
        eval_d = self.df_stock["date"].iloc[60]  # T = session index 60

        universe_stock_map = {
            "TCB": self.df_stock,
            "ACB": generate_synthetic_ohlcv(num_days=100, base_price=25.0, daily_trend=0.0015),
            "FPT": generate_synthetic_ohlcv(num_days=100, base_price=130.0, daily_trend=0.002),
        }

        # Calculate breadth before mutation
        breadth_orig = calculate_as_of_market_breadth(universe_stock_map, eval_d)

        # Original run
        results_orig = run_backtest_for_symbol(
            symbol="TCB",
            df_stock=self.df_stock,
            evaluation_dates=[eval_d],
            company_name="Techcombank",
            sector="Banking",
            exchange="HOSE",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            universe_stock_map=universe_stock_map,
        )
        sig_orig = results_orig[0].signal

        # Create mutated market & stock datasets where all data strictly AFTER T is drastically altered
        df_stock_mut = self.df_stock.copy()
        df_vnindex_mut = self.df_vnindex.copy()
        df_vn30_mut = self.df_vn30.copy()

        universe_mut = {}
        for s, df_s in universe_stock_map.items():
            df_m = df_s.copy()
            post_t = df_m["date"] > eval_d
            price_cols = ["open", "high", "low", "close"]
            df_m.loc[post_t, price_cols] = df_m.loc[post_t, price_cols] * 10.0
            universe_mut[s] = df_m

        post_t_stock = df_stock_mut["date"] > eval_d
        price_cols = ["open", "high", "low", "close"]
        df_stock_mut.loc[post_t_stock, price_cols] = (
            df_stock_mut.loc[post_t_stock, price_cols] * 0.10
        )

        post_t_vn = df_vnindex_mut["date"] > eval_d
        df_vnindex_mut.loc[post_t_vn, price_cols] = df_vnindex_mut.loc[post_t_vn, price_cols] * 0.20

        post_t_30 = df_vn30_mut["date"] > eval_d
        df_vn30_mut.loc[post_t_30, price_cols] = df_vn30_mut.loc[post_t_30, price_cols] * 0.20

        breadth_mutated = calculate_as_of_market_breadth(universe_mut, eval_d)
        self.assertEqual(breadth_orig, breadth_mutated)

        results_mutated = run_backtest_for_symbol(
            symbol="TCB",
            df_stock=df_stock_mut,
            evaluation_dates=[eval_d],
            company_name="Techcombank",
            sector="Banking",
            exchange="HOSE",
            df_vnindex=df_vnindex_mut,
            df_vn30=df_vn30_mut,
            universe_stock_map=universe_mut,
        )
        sig_mutated = results_mutated[0].signal

        # Signal generated at T must be 100% IDENTICAL across all fields
        self.assertEqual(sig_orig.action, sig_mutated.action)
        self.assertEqual(sig_orig.signal_score, sig_mutated.signal_score)
        self.assertEqual(sig_orig.confidence, sig_mutated.confidence)
        self.assertEqual(sig_orig.market_regime, sig_mutated.market_regime)
        self.assertEqual(sig_orig.risk_adjusted_score, sig_mutated.risk_adjusted_score)
        self.assertEqual(sig_orig.entry_price, sig_mutated.entry_price)
        self.assertEqual(sig_orig.score_components, sig_mutated.score_components)

        # Forward outcomes AFTER T SHOULD differ due to mutated future prices
        outcome_orig = results_orig[0].outcome
        outcome_mutated = results_mutated[0].outcome
        self.assertNotEqual(outcome_orig.returns[5], outcome_mutated.returns[5])

    def test_e_future_data_quality_isolation(self):
        """Test E: Future Data Quality Isolation ('future data quality != signal at T').

        Corrupting/malforming data strictly AFTER T (e.g., unparseable dates, negative prices, bad OHLC)
        must NOT affect or fail signal generation at T.
        """
        eval_d = self.df_stock["date"].iloc[50]  # T = index 50

        # Original signal at T
        res_orig = run_backtest_for_symbol(
            symbol="TCB",
            df_stock=self.df_stock,
            evaluation_dates=[eval_d],
        )[0]

        # Corrupt stock data strictly AFTER T
        df_corrupted_post_t = self.df_stock.copy()
        post_t_idx = df_corrupted_post_t.index[df_corrupted_post_t["date"] > eval_d]

        # Inject invalid date, negative price, and bad OHLC strictly after T
        df_corrupted_post_t.loc[post_t_idx[0], "date"] = "bad-future-date-entry"
        df_corrupted_post_t.loc[post_t_idx[1], "close"] = -10.0
        df_corrupted_post_t.loc[post_t_idx[2], "high"] = 5.0
        df_corrupted_post_t.loc[post_t_idx[2], "low"] = 500.0

        res_corrupted = run_backtest_for_symbol(
            symbol="TCB",
            df_stock=df_corrupted_post_t,
            evaluation_dates=[eval_d],
        )[0]

        # Signal at T MUST be 100% identical
        self.assertEqual(res_orig.signal.action, res_corrupted.signal.action)
        self.assertEqual(res_orig.signal.signal_score, res_corrupted.signal.signal_score)
        self.assertEqual(res_orig.signal.confidence, res_corrupted.signal.confidence)
        self.assertEqual(res_orig.signal.market_regime, res_corrupted.signal.market_regime)

    def test_f_determinism(self):
        """Test F: Determinism verification across multiple invocations."""
        eval_dates = [self.df_stock["date"].iloc[40], self.df_stock["date"].iloc[50]]

        run1 = run_backtest_for_symbol("VNM", self.df_stock, eval_dates)
        run2 = run_backtest_for_symbol("VNM", self.df_stock, eval_dates)

        self.assertEqual(len(run1), len(run2))
        for r1, r2 in zip(run1, run2, strict=True):
            self.assertEqual(r1.to_dict(), r2.to_dict())

    def test_g_direction_handling(self):
        """Test G: Direction handling (BUY, SELL, HOLD strategy returns)."""
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

    def test_h_aggregation_metrics_exact_assertions(self):
        """Test H: Aggregation and breakdown metrics with exact numerical assertions."""
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
        self.assertAlmostEqual(m5["forward_return"]["mean"], 0.043333, places=5)
        self.assertAlmostEqual(m5["forward_return"]["min"], -0.02, places=4)
        self.assertAlmostEqual(m5["forward_return"]["max"], 0.10, places=4)

        # Strategy return diagnostic sum: 0.10 - 0.05 + 0.0 = 0.05
        self.assertAlmostEqual(m5["strategy_return"]["sum_strategy_return"], 0.05, places=4)

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

    def test_i_market_breadth_and_universe_backtest(self):
        """Test I: Point-in-time market breadth calculation and universe-wide backtest."""
        universe_map = {
            "TCB": self.df_stock,
            "ACB": generate_synthetic_ohlcv(num_days=100, base_price=25.0, daily_trend=0.001),
        }
        eval_d = self.df_stock["date"].iloc[50]

        breadth = calculate_as_of_market_breadth(universe_map, eval_d)
        self.assertGreaterEqual(breadth, 0.0)
        self.assertLessEqual(breadth, 1.0)

        univ_results = run_backtest_for_universe(
            universe_stock_map=universe_map,
            evaluation_dates=[eval_d],
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )
        self.assertEqual(len(univ_results), 2)

    def test_j_strict_validation_and_fail_closed_error_handling(self):
        """Test J: Strict input validation and fail-closed error handling."""
        eval_d = self.df_stock["date"].iloc[30]

        # 1. Empty DataFrame
        with self.assertRaises(ValueError):
            get_as_of_dataset(pd.DataFrame(), "2025-01-01")

        # 2. Missing date column
        with self.assertRaises(ValueError):
            get_as_of_dataset(pd.DataFrame({"close": [10, 20]}), "2025-01-01")

        # 3. Invalid date format
        with self.assertRaises(ValueError):
            get_as_of_dataset(self.df_stock, "invalid-date-string")

        # 4. Evaluation date out of bounds
        with self.assertRaises(ValueError):
            get_as_of_dataset(self.df_stock, "2020-01-01")

        # 5. Duplicate dates prior to T fail validation
        df_dup = self.df_stock.copy()
        df_dup.iloc[5] = df_dup.iloc[4]  # Create duplicate date row at index 5 (< T)
        with self.assertRaises(ValueError):
            get_as_of_dataset(df_dup, eval_d)

        # 6. Invalid dates prior to T fail validation
        df_bad_date = self.df_stock.copy()
        df_bad_date.loc[3, "date"] = "bad-date-entry"
        with self.assertRaises(ValueError):
            get_as_of_dataset(df_bad_date, eval_d)

        # 7. Malformed market data (<= T) fails closed in run_backtest_for_symbol
        with self.assertRaises(ValueError):
            run_backtest_for_symbol(
                symbol="TCB",
                df_stock=self.df_stock,
                evaluation_dates=[eval_d],
                df_vnindex=df_dup,  # Malformed VNINDEX with duplicate dates <= T
            )

        # 8. Malformed universe stock data (<= T) fails closed in breadth calculation
        bad_univ_map = {"BAD_STOCK": df_dup}
        with self.assertRaises(ValueError):
            calculate_as_of_market_breadth(bad_univ_map, eval_d)

    def test_k_fail_closed_empty_or_malformed_breadth(self):
        """Test K: Fail-closed market breadth validation on empty or malformed universe."""
        eval_d = self.df_stock["date"].iloc[30]

        # Empty universe map fails closed
        with self.assertRaises(ValueError):
            calculate_as_of_market_breadth({}, eval_d)

        # Map with only empty dataframes fails closed
        with self.assertRaises(ValueError):
            calculate_as_of_market_breadth({"BAD1": pd.DataFrame(), "BAD2": None}, eval_d)


if __name__ == "__main__":
    unittest.main()
