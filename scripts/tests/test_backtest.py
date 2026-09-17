"""Unit Test Suite for Deterministic No-Lookahead Backtesting Framework."""

import math
import unittest

import pandas as pd

from scripts.lib.backtest import (
    REASON_BELOW_MIN_PRICE,
    REASON_BELOW_MIN_TRADED_VALUE,
    REASON_BELOW_MIN_VOLUME,
    REASON_EXCEEDS_MAX_PARTICIPATION,
    REASON_INSUFFICIENT_LOOKBACK_SESSIONS,
    STATUS_EXECUTABLE,
    STATUS_INSUFFICIENT_LIQUIDITY_HISTORY,
    STATUS_NOT_EXECUTABLE,
    BacktestResult,
    BacktestSignal,
    ComponentEvaluationResult,
    ConfidenceCalibrationResult,
    ConfidenceObservation,
    ExecutionConfig,
    ForwardOutcome,
    RegimeEvaluationResult,
    RegimeObservation,
    WalkForwardResult,
    aggregate_backtest_results,
    aggregate_confidence_calibration_results,
    aggregate_regime_evaluation_results,
    calculate_as_of_market_breadth,
    classify_confidence_bucket,
    evaluate_confidence_calibration,
    evaluate_execution_eligibility,
    evaluate_forward_outcomes,
    evaluate_market_regimes,
    evaluate_signal_components,
    generate_walk_forward_dates,
    get_as_of_dataset,
    run_backtest_for_symbol,
    run_backtest_for_universe,
    run_walk_forward_backtest,
)
from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime


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
        must NOT affect or fail point-in-time signal generation at T.
        """
        eval_d = self.df_stock["date"].iloc[50]  # T = index 50

        # Point-in-time dataset as-of T from clean original stock
        df_as_of_orig = get_as_of_dataset(self.df_stock, eval_d)

        # Corrupt stock data strictly AFTER T
        df_corrupted_post_t = self.df_stock.copy()
        post_t_idx = df_corrupted_post_t.index[df_corrupted_post_t["date"] > eval_d]

        # Inject invalid date, negative price, and bad OHLC strictly after T
        df_corrupted_post_t.loc[post_t_idx[0], "date"] = "bad-future-date-entry"
        df_corrupted_post_t.loc[post_t_idx[1], "close"] = -10.0
        df_corrupted_post_t.loc[post_t_idx[2], "high"] = 5.0
        df_corrupted_post_t.loc[post_t_idx[2], "low"] = 500.0

        # Point-in-time dataset as-of T MUST succeed without error despite post-T corruption
        df_as_of_corrupted = get_as_of_dataset(df_corrupted_post_t, eval_d)

        # Datasets <= T MUST be 100% identical
        pd.testing.assert_frame_equal(df_as_of_orig, df_as_of_corrupted)

        # Outcome evaluation on corrupted future data raises ValueError fitting outcome contract
        with self.assertRaises(ValueError):
            evaluate_forward_outcomes(df_corrupted_post_t, eval_d)

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

        # 7. Unsorted input dates prior to T fail validation (fail closed)
        df_unsorted = self.df_stock.copy()
        tmp_row = df_unsorted.iloc[10].copy()
        df_unsorted.iloc[10] = df_unsorted.iloc[15]
        df_unsorted.iloc[15] = tmp_row
        with self.assertRaises(ValueError):
            get_as_of_dataset(df_unsorted, eval_d)

        # 8. Malformed market data (<= T) fails closed in run_backtest_for_symbol
        with self.assertRaises(ValueError):
            run_backtest_for_symbol(
                symbol="TCB",
                df_stock=self.df_stock,
                evaluation_dates=[eval_d],
                df_vnindex=df_dup,  # Malformed VNINDEX with duplicate dates <= T
            )

        # 9. Malformed universe stock data (<= T) fails closed in breadth calculation
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

    def test_l_unsorted_and_duplicate_outcome_dataset_validation(self):
        """Test L: Unsorted and duplicate outcome dataset fail-closed validation."""
        eval_d = self.df_stock["date"].iloc[10]

        # Unsorted outcome dataset
        df_unsorted = self.df_stock.copy()
        tmp = df_unsorted.iloc[20].copy()
        df_unsorted.iloc[20] = df_unsorted.iloc[30]
        df_unsorted.iloc[30] = tmp
        with self.assertRaises(ValueError):
            evaluate_forward_outcomes(df_unsorted, eval_d)

        # Duplicate date outcome dataset
        df_dup = self.df_stock.copy()
        df_dup.iloc[25] = df_dup.iloc[24]
        with self.assertRaises(ValueError):
            evaluate_forward_outcomes(df_dup, eval_d)

    def test_m_future_row_physically_placed_before_t_fails_closed(self):
        """Test M: Regression test where a future row (> T) is physically placed before T in DataFrame.

        Example physical sequence: T-3, T-2, T-1, T+10 (future row), T, T+1.
        get_as_of_dataset(df, evaluation_date=T) MUST fail closed with ValueError because dates <= T are non-monotonic,
        proving that a future observation physically before T is detected and fails closed.
        """
        df_normal = generate_synthetic_ohlcv(50, start_date="2025-01-01")
        eval_d = df_normal["date"].iloc[20]  # T = index 20

        # Construct DataFrame with future row (T+10) physically inserted before T at index 18 without removing any rows
        df_misordered = pd.concat(
            [
                df_normal.iloc[:18],
                df_normal.iloc[30:31],  # T+10 row physically placed before T
                df_normal.iloc[18:],
            ],
            ignore_index=True,
        )

        # get_as_of_dataset <= T must fail closed with ValueError because input dates prior to T contain future observation / non-monotonic dates
        with self.assertRaises(ValueError):
            get_as_of_dataset(df_misordered, eval_d)

    # --- Walk-Forward Validation Framework Unit Tests ---

    def test_wf_a_chronological_evaluation(self):
        """Test WF-A: Evaluation dates are processed in strict chronological order."""
        eval_dates = [
            self.df_stock["date"].iloc[50],
            self.df_stock["date"].iloc[60],
            self.df_stock["date"].iloc[70],
        ]

        wf_res = run_walk_forward_backtest(
            evaluation_dates=eval_dates,
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        self.assertIsInstance(wf_res, WalkForwardResult)
        self.assertEqual(wf_res.evaluation_dates, eval_dates)
        self.assertEqual(len(wf_res.results), 3)

        res_dates = [r.signal.evaluation_date for r in wf_res.results]
        self.assertEqual(res_dates, eval_dates)
        self.assertEqual(res_dates, sorted(res_dates))

    def test_wf_b_minimum_history(self):
        """Test WF-B: Minimum history rule excludes dates with insufficient sessions."""
        # Generating dates with min_history=50, step=10 on 100-day dataset
        gen_dates = generate_walk_forward_dates(self.df_stock, min_history=50, step=10)

        # Index 49 is the 50th session (first eligible)
        expected_first = self.df_stock["date"].iloc[49]
        self.assertEqual(gen_dates[0], expected_first)

        # Confirm dates before min_history are omitted
        early_date = self.df_stock["date"].iloc[20]
        self.assertNotIn(early_date, gen_dates)

        # Dataset with fewer sessions than min_history fails closed
        df_short = self.df_stock.iloc[:30].copy()
        with self.assertRaises(ValueError):
            generate_walk_forward_dates(df_short, min_history=50)

    def test_wf_c_exact_pit_boundary(self):
        """Test WF-C: Exact Point-In-Time (PIT) boundary verification at T."""
        eval_d = self.df_stock["date"].iloc[55]

        wf_res = run_walk_forward_backtest(
            evaluation_dates=[eval_d],
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        sig = wf_res.results[0].signal
        self.assertEqual(sig.evaluation_date, eval_d)

        # Verify entry price matches exact price at evaluation date T (rounded to VND unit)
        c_at_T = self.df_stock[self.df_stock["date"] == eval_d]["close"].iloc[0]
        self.assertAlmostEqual(sig.entry_price, round(c_at_T, 0), places=2)

    def test_wf_d_future_mutation_isolation(self):
        """Test WF-D: Mutating post-T stock data leaves signal scores, confidence, regime, and components identical."""
        eval_d = self.df_stock["date"].iloc[60]

        res_orig = run_walk_forward_backtest(
            evaluation_dates=[eval_d],
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )
        sig_orig = res_orig.results[0].signal

        # Mutate post-T stock prices drastically (+1000%)
        df_mut = self.df_stock.copy()
        post_t_mask = df_mut["date"] > eval_d
        df_mut.loc[post_t_mask, ["open", "high", "low", "close"]] *= 10.0

        res_mut = run_walk_forward_backtest(
            evaluation_dates=[eval_d],
            df_stock=df_mut,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )
        sig_mut = res_mut.results[0].signal

        self.assertEqual(sig_orig.action, sig_mut.action)
        self.assertEqual(sig_orig.signal_score, sig_mut.signal_score)
        self.assertEqual(sig_orig.confidence, sig_mut.confidence)
        self.assertEqual(sig_orig.market_regime, sig_mut.market_regime)
        self.assertEqual(sig_orig.risk_adjusted_score, sig_mut.risk_adjusted_score)
        self.assertEqual(sig_orig.score_components, sig_mut.score_components)

        # Outcomes after T should differ
        self.assertNotEqual(
            res_orig.results[0].outcome.returns[5], res_mut.results[0].outcome.returns[5]
        )

    def test_wf_e_market_future_mutation_isolation(self):
        """Test WF-E: Mutating market-level data (VNINDEX, VN30, breadth) after T leaves signal at T identical."""
        eval_d = self.df_stock["date"].iloc[60]

        universe_stock_map = {
            "TCB": self.df_stock,
            "ACB": generate_synthetic_ohlcv(num_days=100, base_price=25.0, daily_trend=0.001),
        }

        res_orig = run_walk_forward_backtest(
            evaluation_dates=[eval_d],
            universe_stock_map=universe_stock_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )
        sig_orig = next(r.signal for r in res_orig.results if r.signal.symbol == "TCB")

        # Mutate post-T VNINDEX, VN30, and universe stock history
        df_vnindex_mut = self.df_vnindex.copy()
        df_vnindex_mut.loc[df_vnindex_mut["date"] > eval_d, ["open", "high", "low", "close"]] *= (
            0.10
        )

        df_vn30_mut = self.df_vn30.copy()
        df_vn30_mut.loc[df_vn30_mut["date"] > eval_d, ["open", "high", "low", "close"]] *= 0.10

        universe_mut = {}
        for s, df_s in universe_stock_map.items():
            df_m = df_s.copy()
            df_m.loc[df_m["date"] > eval_d, ["open", "high", "low", "close"]] *= 5.0
            universe_mut[s] = df_m

        res_mut = run_walk_forward_backtest(
            evaluation_dates=[eval_d],
            universe_stock_map=universe_mut,
            df_vnindex=df_vnindex_mut,
            df_vn30=df_vn30_mut,
        )
        sig_mut = next(r.signal for r in res_mut.results if r.signal.symbol == "TCB")

        self.assertEqual(sig_orig.action, sig_mut.action)
        self.assertEqual(sig_orig.signal_score, sig_mut.signal_score)
        self.assertEqual(sig_orig.confidence, sig_mut.confidence)
        self.assertEqual(sig_orig.market_regime, sig_mut.market_regime)
        self.assertEqual(sig_orig.risk_adjusted_score, sig_mut.risk_adjusted_score)

    def test_wf_f_future_row_physically_before_t_fails_closed(self):
        """Test WF-F: Misordered dataframe containing future row before T fails closed."""
        df_normal = generate_synthetic_ohlcv(50, start_date="2025-01-01")
        eval_d = df_normal["date"].iloc[20]

        df_misordered = pd.concat(
            [
                df_normal.iloc[:18],
                df_normal.iloc[30:31],  # Future row physically placed before T
                df_normal.iloc[18:],
            ],
            ignore_index=True,
        )

        with self.assertRaises(ValueError):
            run_walk_forward_backtest(
                evaluation_dates=[eval_d],
                df_stock=df_misordered,
                symbol="TCB",
            )

    def test_wf_g_deterministic_rerun(self):
        """Test WF-G: Running walk-forward evaluation twice yields identical outputs."""
        eval_dates = [self.df_stock["date"].iloc[50], self.df_stock["date"].iloc[60]]

        run1 = run_walk_forward_backtest(
            evaluation_dates=eval_dates,
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )
        run2 = run_walk_forward_backtest(
            evaluation_dates=eval_dates,
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        self.assertEqual(run1.to_dict(), run2.to_dict())

    def test_wf_h_forward_horizon_semantics(self):
        """Test WF-H: Exact (Price[T+N] / Price[T]) - 1.0 forward return formula."""
        eval_d = self.df_stock["date"].iloc[50]  # T = index 50

        wf_res = run_walk_forward_backtest(
            evaluation_dates=[eval_d],
            df_stock=self.df_stock,
            symbol="TCB",
            horizons=[5, 10, 20],
        )

        outcome = wf_res.results[0].outcome
        p_T = self.df_stock["close"].iloc[50]
        p_T5 = self.df_stock["close"].iloc[55]
        expected_ret5 = round((p_T5 / p_T) - 1.0, 6)

        self.assertAlmostEqual(outcome.returns[5], expected_ret5, places=5)

    def test_wf_i_insufficient_future_data(self):
        """Test WF-I: Evaluation date near end of history sets availability=False and returns=None."""
        eval_d = self.df_stock["date"].iloc[-3]  # Only 2 future sessions remain

        wf_res = run_walk_forward_backtest(
            evaluation_dates=[eval_d],
            df_stock=self.df_stock,
            symbol="TCB",
            horizons=[5, 10, 20],
        )

        outcome = wf_res.results[0].outcome
        self.assertFalse(outcome.availability[5])
        self.assertIsNone(outcome.returns[5])

    def test_wf_j_no_hidden_future_dependency(self):
        """Test WF-J: Synthetic dataset with extreme post-T price shifts leaves signal at T completely unchanged."""
        eval_d = self.df_stock["date"].iloc[50]

        df_synth_a = generate_synthetic_ohlcv(num_days=80, start_date="2025-01-01", base_price=50.0)
        df_synth_b = df_synth_a.copy()

        # Invert future prices completely (> T)
        post_t_mask = df_synth_b["date"] > eval_d
        df_synth_b.loc[post_t_mask, ["open", "high", "low", "close"]] *= 0.01

        res_a = run_walk_forward_backtest(
            evaluation_dates=[eval_d],
            df_stock=df_synth_a,
            symbol="TCB",
        )
        res_b = run_walk_forward_backtest(
            evaluation_dates=[eval_d],
            df_stock=df_synth_b,
            symbol="TCB",
        )

        self.assertEqual(res_a.results[0].signal.to_dict(), res_b.results[0].signal.to_dict())

    def test_wf_fail_closed_validation_errors(self):
        """Test WF Fail-Closed: Unsorted, duplicate, or missing evaluation dates raise ValueError."""
        # 1. Unsorted evaluation dates
        dates_unsorted = [self.df_stock["date"].iloc[60], self.df_stock["date"].iloc[50]]
        with self.assertRaises(ValueError):
            run_walk_forward_backtest(
                evaluation_dates=dates_unsorted,
                df_stock=self.df_stock,
                symbol="TCB",
            )

    def test_wf_min_history_explicit_evaluation_date_too_early(self):
        """Test PR #87 Fix Test A1: Single stock explicit evaluation date with insufficient history <= T raises ValueError."""
        # Date at index 3 has only 4 historical sessions <= T
        early_date = self.df_stock["date"].iloc[3]

        with self.assertRaises(ValueError) as cm:
            run_walk_forward_backtest(
                evaluation_dates=[early_date],
                df_stock=self.df_stock,
                symbol="TCB",
                min_history=5,
            )
        self.assertIn("insufficient history", str(cm.exception))
        self.assertIn(early_date, str(cm.exception))
        self.assertIn("TCB", str(cm.exception))

    def test_wf_min_history_explicit_evaluation_date_exact_minimum(self):
        """Test PR #87 Fix Test A2: Single stock explicit evaluation date with exact min_history sessions succeeds."""
        # Date at index 4 has exactly 5 historical sessions <= T (indices 0, 1, 2, 3, 4)
        exact_date = self.df_stock["date"].iloc[4]

        wf_res = run_walk_forward_backtest(
            evaluation_dates=[exact_date],
            df_stock=self.df_stock,
            symbol="TCB",
            min_history=5,
        )
        self.assertEqual(wf_res.evaluation_dates, [exact_date])
        self.assertEqual(len(wf_res.results), 1)

    def test_wf_universe_none_stock_fails_closed(self):
        """Test Fail-Closed 1: None stock value in universe_stock_map raises ValueError identifying symbol."""
        df_stock_a = generate_synthetic_ohlcv(100, start_date="2025-01-01")
        univ_map = {"AAA": df_stock_a, "BBB": None}

        with self.assertRaises(ValueError) as cm:
            run_walk_forward_backtest(universe_stock_map=univ_map, min_history=10)
        self.assertIn("BBB", str(cm.exception))
        self.assertIn("None", str(cm.exception))

    def test_wf_universe_empty_stock_fails_closed(self):
        """Test Fail-Closed 2: Empty DataFrame stock value in universe_stock_map raises ValueError identifying symbol."""
        df_stock_a = generate_synthetic_ohlcv(100, start_date="2025-01-01")
        univ_map = {"AAA": df_stock_a, "BBB": pd.DataFrame()}

        with self.assertRaises(ValueError) as cm:
            run_walk_forward_backtest(universe_stock_map=univ_map, min_history=10)
        self.assertIn("BBB", str(cm.exception))
        self.assertIn("empty", str(cm.exception))

    def test_wf_universe_missing_exact_evaluation_date_fails_closed(self):
        """Test Fail-Closed 3: Stock in universe lacking exact evaluation date T raises ValueError identifying symbol and date."""
        df_stock_a = generate_synthetic_ohlcv(100, start_date="2025-01-01")
        # df_stock_b starts at a different start_date so exact evaluation date on day 5 of A does not exist in B
        df_stock_b = generate_synthetic_ohlcv(50, start_date="2025-03-01")

        eval_early_a = df_stock_a["date"].iloc[10]  # January 2025 date not in df_stock_b

        univ_map = {"AAA": df_stock_a, "BBB": df_stock_b}

        with self.assertRaises(ValueError) as cm:
            run_walk_forward_backtest(
                evaluation_dates=[eval_early_a],
                universe_stock_map=univ_map,
                min_history=5,
            )
        self.assertIn("BBB", str(cm.exception))
        self.assertIn("failed point-in-time validation", str(cm.exception))

    def test_wf_universe_invalid_unsorted_stock_fails_closed(self):
        """Test Fail-Closed 4: Stock in universe with unsorted/duplicate dates fails closed with ValueError."""
        df_stock_a = generate_synthetic_ohlcv(100, start_date="2025-01-01")
        df_stock_b = df_stock_a.copy()
        # Create duplicate date in df_stock_b
        df_stock_b.iloc[10] = df_stock_b.iloc[9]

        univ_map = {"AAA": df_stock_a, "BBB": df_stock_b}
        eval_d = df_stock_a["date"].iloc[50]

        with self.assertRaises(ValueError) as cm:
            run_walk_forward_backtest(
                evaluation_dates=[eval_d],
                universe_stock_map=univ_map,
                min_history=10,
            )
        self.assertIn("BBB", str(cm.exception))

    def test_wf_universe_explicit_dates_per_stock_min_history(self):
        """Test PR #87 Fix Test B / Test 5: Universe explicit evaluation date fails closed if ANY stock lacks min_history."""
        # Stock A starts at index 0 (2025-01-01) -> 50 sessions at index 49
        df_stock_a = generate_synthetic_ohlcv(100, start_date="2025-01-01", base_price=50.0)
        # Stock B starts later at 2025-02-15 -> on 2025-02-20, Stock B only has 4 sessions
        df_stock_b = generate_synthetic_ohlcv(50, start_date="2025-02-15", base_price=30.0)

        univ_map = {"STOCK_A": df_stock_a, "STOCK_B": df_stock_b}
        eval_d = df_stock_b["date"].iloc[
            3
        ]  # 4 sessions for STOCK_B <= eval_d, but >50 sessions for STOCK_A

        with self.assertRaises(ValueError) as cm:
            run_walk_forward_backtest(
                evaluation_dates=[eval_d],
                universe_stock_map=univ_map,
                min_history=10,
            )
        self.assertIn("STOCK_B", str(cm.exception))
        self.assertIn("insufficient history", str(cm.exception))
        self.assertIn(eval_d, str(cm.exception))

    def test_wf_universe_generated_dates_strict_contract(self):
        """Test PR #87 Fix Test C: Generated universe dates strictly require ALL stocks to satisfy min_history."""
        # Stock A starts 2025-01-01 (100 sessions)
        df_stock_a = generate_synthetic_ohlcv(100, start_date="2025-01-01", base_price=50.0)
        # Stock B starts 2025-01-01 (70 sessions)
        df_stock_b = generate_synthetic_ohlcv(70, start_date="2025-01-01", base_price=30.0)

        univ_map = {"STOCK_A": df_stock_a, "STOCK_B": df_stock_b}

        # Auto-generate dates with min_history=20, step=10 (end_date bounded to Stock B history)
        end_d = df_stock_b["date"].iloc[-1]
        wf_res = run_walk_forward_backtest(
            universe_stock_map=univ_map,
            min_history=20,
            step=10,
            end_date=end_d,
        )

        # Confirm every generated date satisfies min_history=20 for BOTH Stock A and Stock B
        for gen_d in wf_res.evaluation_dates:
            len_a = len(get_as_of_dataset(df_stock_a, gen_d))
            len_b = len(get_as_of_dataset(df_stock_b, gen_d))
            self.assertGreaterEqual(len_a, 20)
            self.assertGreaterEqual(len_b, 20)

    def test_wf_universe_generated_dates_stock_missing_candidate_date_fails_closed(self):
        """Test Fail-Closed: If auto-generated candidate date is missing from a universe stock, fails closed with ValueError."""
        # Stock A starts 2025-01-01
        df_stock_a = generate_synthetic_ohlcv(100, start_date="2025-01-01", base_price=50.0)
        # Stock B starts later at 2025-02-01
        df_stock_b = generate_synthetic_ohlcv(70, start_date="2025-02-01", base_price=30.0)

        univ_map = {"STOCK_A": df_stock_a, "STOCK_B": df_stock_b}

        # Auto-generate dates from Stock A starting in Jan 2025 -> candidate date in Jan fails in Stock B
        with self.assertRaises(ValueError) as cm:
            run_walk_forward_backtest(
                universe_stock_map=univ_map,
                min_history=20,
                step=10,
            )
        self.assertIn("STOCK_B", str(cm.exception))
        self.assertIn("failed point-in-time validation", str(cm.exception))

    def test_wf_min_history_future_mutation_cannot_satisfy_min_history(self):
        """Test PR #87 Fix Test D: Mutating future data (> T) cannot bypass min_history enforcement <= T."""
        # Date at index 3 has 4 sessions <= T
        early_date = self.df_stock["date"].iloc[3]

        # Duplicate/append future rows strictly AFTER early_date
        df_future_mut = pd.concat([self.df_stock, self.df_stock.iloc[10:]], ignore_index=True)

        # Evaluating at early_date still only sees 4 sessions <= T and MUST fail min_history=5
        with self.assertRaises(ValueError) as cm:
            run_walk_forward_backtest(
                evaluation_dates=[early_date],
                df_stock=df_future_mut,
                symbol="TCB",
                min_history=5,
            )
        self.assertIn("insufficient history", str(cm.exception))

        # 2. Duplicate evaluation dates
        dates_dup = [self.df_stock["date"].iloc[50], self.df_stock["date"].iloc[50]]
        with self.assertRaises(ValueError):
            run_walk_forward_backtest(
                evaluation_dates=dates_dup,
                df_stock=self.df_stock,
                symbol="TCB",
            )

        # 3. Invalid evaluation date format
        with self.assertRaises(ValueError):
            run_walk_forward_backtest(
                evaluation_dates=["invalid-date-format"],
                df_stock=self.df_stock,
                symbol="TCB",
            )

        # 4. Evaluation date not in dataset
        with self.assertRaises(ValueError):
            run_walk_forward_backtest(
                evaluation_dates=["2010-01-01"],
                df_stock=self.df_stock,
                symbol="TCB",
            )

    # --- PR #88 Signal Component Evaluation Unit Tests ---

    def test_comp_1_component_decomposition(self):
        """Test Comp 1: Signal component decomposition returns Trend, Momentum, Volume, RS, and Divergence scores matching production recommendation engine."""
        eval_d = self.df_stock["date"].iloc[50]

        comp_res = evaluate_signal_components(
            evaluation_dates=[eval_d],
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        self.assertIsInstance(comp_res, ComponentEvaluationResult)
        obs_map = {o.component: o for o in comp_res.observations if o.horizon == 5}

        # Validate all 5 production signal components exist
        expected_comps = ["trend", "momentum", "volume", "relative_strength", "divergence"]
        for c in expected_comps:
            self.assertIn(c, obs_map)

        # Compare directly with production recommendation engine
        df_pit = get_as_of_dataset(self.df_stock, eval_d)
        df_vn_pit = get_as_of_dataset(self.df_vnindex, eval_d)
        df_vn30_pit = get_as_of_dataset(self.df_vn30, eval_d)

        regime_info = detect_market_regime(df_vnindex=df_vn_pit, df_vn30=df_vn30_pit)
        rec = generate_recommendation(
            symbol="TCB",
            company_name="",
            sector="",
            exchange="HOSE",
            df_stock=df_pit,
            market_regime_info=regime_info,
            df_vnindex=df_vn_pit,
            data_as_of=eval_d,
        )

        prod_comps = rec["score_components"]
        for c in expected_comps:
            self.assertEqual(obs_map[c].component_score, prod_comps[c])

    def test_comp_2_same_evaluation_dates(self):
        """Test Comp 2: All signal components are evaluated on the EXACT SAME evaluation dates."""
        eval_dates = [
            self.df_stock["date"].iloc[50],
            self.df_stock["date"].iloc[60],
        ]

        comp_res = evaluate_signal_components(
            evaluation_dates=eval_dates,
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        expected_comps = ["trend", "momentum", "volume", "relative_strength", "divergence"]

        for eval_d in eval_dates:
            for c in expected_comps:
                c_obs = [
                    o
                    for o in comp_res.observations
                    if o.evaluation_date == eval_d and o.component == c and o.horizon == 5
                ]
                self.assertEqual(len(c_obs), 1)

    def test_comp_3_same_forward_outcomes(self):
        """Test Comp 3: All signal components use the EXACT SAME forward outcome for each (evaluation_date, horizon)."""
        eval_d = self.df_stock["date"].iloc[50]

        comp_res = evaluate_signal_components(
            evaluation_dates=[eval_d],
            df_stock=self.df_stock,
            symbol="TCB",
            horizons=[5, 10, 20],
        )

        for h in [5, 10, 20]:
            fwd_rets = [
                o.forward_return
                for o in comp_res.observations
                if o.horizon == h and o.evaluation_date == eval_d
            ]
            # All 5 components must share identical forward return value at horizon h
            self.assertEqual(len(fwd_rets), 5)
            self.assertEqual(len(set(fwd_rets)), 1)

    def test_comp_4_no_lookahead_stock_mutation(self):
        """Test Comp 4: Mutating stock data strictly AFTER T does not alter component scores at T."""
        eval_d = self.df_stock["date"].iloc[60]

        res_orig = evaluate_signal_components(
            evaluation_dates=[eval_d],
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        df_mut = self.df_stock.copy()
        post_t = df_mut["date"] > eval_d
        df_mut.loc[post_t, ["open", "high", "low", "close"]] *= 100.0

        res_mut = evaluate_signal_components(
            evaluation_dates=[eval_d],
            df_stock=df_mut,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        orig_scores = {
            o.component: o.component_score for o in res_orig.observations if o.horizon == 5
        }
        mut_scores = {
            o.component: o.component_score for o in res_mut.observations if o.horizon == 5
        }

        self.assertEqual(orig_scores, mut_scores)

    def test_comp_5_no_lookahead_market_mutation(self):
        """Test Comp 5: Mutating market-level data (VNINDEX, VN30) strictly AFTER T does not alter component scores at T."""
        eval_d = self.df_stock["date"].iloc[60]

        res_orig = evaluate_signal_components(
            evaluation_dates=[eval_d],
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        df_vn_mut = self.df_vnindex.copy()
        df_vn_mut.loc[df_vn_mut["date"] > eval_d, ["open", "high", "low", "close"]] *= 0.01

        df_30_mut = self.df_vn30.copy()
        df_30_mut.loc[df_30_mut["date"] > eval_d, ["open", "high", "low", "close"]] *= 0.01

        res_mut = evaluate_signal_components(
            evaluation_dates=[eval_d],
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=df_vn_mut,
            df_vn30=df_30_mut,
        )

        orig_scores = {
            o.component: o.component_score for o in res_orig.observations if o.horizon == 5
        }
        mut_scores = {
            o.component: o.component_score for o in res_mut.observations if o.horizon == 5
        }

        self.assertEqual(orig_scores, mut_scores)

    def test_comp_6_future_row_physically_before_t_fails_closed(self):
        """Test Comp 6: Component evaluation fails closed if future row (> T) is physically placed before T."""
        df_normal = generate_synthetic_ohlcv(50, start_date="2025-01-01")
        eval_d = df_normal["date"].iloc[20]

        df_misordered = pd.concat(
            [
                df_normal.iloc[:18],
                df_normal.iloc[30:31],  # Future row physically placed before T
                df_normal.iloc[18:],
            ],
            ignore_index=True,
        )

        with self.assertRaises(ValueError):
            evaluate_signal_components(
                evaluation_dates=[eval_d],
                df_stock=df_misordered,
                symbol="TCB",
            )

    def test_comp_7_deterministic_rerun(self):
        """Test Comp 7: Running component evaluation twice produces identical observations and aggregate metrics."""
        eval_dates = [
            self.df_stock["date"].iloc[50],
            self.df_stock["date"].iloc[60],
        ]

        res1 = evaluate_signal_components(
            evaluation_dates=eval_dates,
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        res2 = evaluate_signal_components(
            evaluation_dates=eval_dates,
            df_stock=self.df_stock,
            symbol="TCB",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        self.assertEqual(res1.to_dict(), res2.to_dict())

    def test_comp_8_missing_and_invalid_data_handling(self):
        """Test Comp 8: Missing/invalid component inputs produce None score without crash or silent corruption."""
        df_short = self.df_stock.iloc[:20].copy()  # Only 20 sessions (minimal history)
        eval_d = df_short["date"].iloc[-1]

        # In short history without benchmark, relative_strength component score will be None
        comp_res = evaluate_signal_components(
            evaluation_dates=[eval_d],
            df_stock=df_short,
            symbol="TCB",
            df_vnindex=None,
            min_history=20,
        )

        rs_obs = [
            o
            for o in comp_res.observations
            if o.component == "relative_strength" and o.horizon == 5
        ]
        self.assertEqual(len(rs_obs), 1)
        self.assertIsNone(rs_obs[0].component_score)
        self.assertIsNone(rs_obs[0].score_bucket)

    def test_comp_9_production_regression(self):
        """Test Comp 9: Production recommendation functions preserve 100% exact output on fixtures."""
        df_pit = get_as_of_dataset(self.df_stock, self.evaluation_date)
        df_vn_pit = get_as_of_dataset(self.df_vnindex, self.evaluation_date)
        df_vn30_pit = get_as_of_dataset(self.df_vn30, self.evaluation_date)

        regime_info = detect_market_regime(df_vnindex=df_vn_pit, df_vn30=df_vn30_pit)

        rec = generate_recommendation(
            symbol="TCB",
            company_name="Techcombank",
            sector="Banking",
            exchange="HOSE",
            df_stock=df_pit,
            market_regime_info=regime_info,
            df_vnindex=df_vn_pit,
            data_as_of=self.evaluation_date,
        )

        # Verify production schema keys and version
        self.assertEqual(rec["model_version"], "2.0")
        self.assertIn("score_components", rec)
        self.assertIn("signal_score", rec)
        self.assertIn("action", rec)
        self.assertIn("confidence", rec)

    def test_comp_10_horizon_semantics(self):
        """Test Comp 10: Component evaluation observations pair correctly with exact T+N forward outcome formula."""
        eval_d = self.df_stock["date"].iloc[50]  # T = index 50

        comp_res = evaluate_signal_components(
            evaluation_dates=[eval_d],
            df_stock=self.df_stock,
            symbol="TCB",
            horizons=[5, 10, 20],
        )

        p_T = self.df_stock["close"].iloc[50]
        p_T5 = self.df_stock["close"].iloc[55]
        p_T10 = self.df_stock["close"].iloc[60]
        p_T20 = self.df_stock["close"].iloc[70]

        expected_ret5 = round((p_T5 / p_T) - 1.0, 6)
        expected_ret10 = round((p_T10 / p_T) - 1.0, 6)
        expected_ret20 = round((p_T20 / p_T) - 1.0, 6)

        obs_5 = next(o for o in comp_res.observations if o.horizon == 5)
        obs_10 = next(o for o in comp_res.observations if o.horizon == 10)
        obs_20 = next(o for o in comp_res.observations if o.horizon == 20)

        self.assertAlmostEqual(obs_5.forward_return, expected_ret5, places=5)
        self.assertAlmostEqual(obs_10.forward_return, expected_ret10, places=5)
        self.assertAlmostEqual(obs_20.forward_return, expected_ret20, places=5)


class TestExecutionEligibilityFramework(unittest.TestCase):
    """Test suite verifying execution eligibility and liquidity assumption framework."""

    def setUp(self):
        # 100-day clean stock dataset with high price and volume
        # Price = 50,000 VND/share, Volume = 100,000 shares
        # Traded value = 5,000,000,000 VND/day = 5.0 billion VND/day
        self.df_stock = generate_synthetic_ohlcv(
            num_days=100, start_date="2025-01-01", base_price=50000.0, daily_trend=0.001
        )
        self.evaluation_date = self.df_stock["date"].iloc[50]  # Day 50

    def test_exec_config_validation_lookback_window(self):
        """Test ExecutionConfig raises ValueError for lookback_window <= 0 or invalid types."""
        with self.assertRaises(ValueError):
            ExecutionConfig(lookback_window=0)
        with self.assertRaises(ValueError):
            ExecutionConfig(lookback_window=-10)
        with self.assertRaises(ValueError):
            ExecutionConfig(lookback_window=True)
        with self.assertRaises(ValueError):
            ExecutionConfig(lookback_window=20.5)

    def test_exec_config_validation_nan_and_inf(self):
        """Test ExecutionConfig raises ValueError for NaN or Inf thresholds or order sizes."""
        for bad_val in [float("nan"), float("inf"), float("-inf")]:
            with self.assertRaises(ValueError):
                ExecutionConfig(min_avg_traded_value_bn=bad_val)
            with self.assertRaises(ValueError):
                ExecutionConfig(min_avg_volume=bad_val)
            with self.assertRaises(ValueError):
                ExecutionConfig(min_price=bad_val)
            with self.assertRaises(ValueError):
                ExecutionConfig(max_participation_rate=bad_val)
            with self.assertRaises(ValueError):
                ExecutionConfig(estimated_order_size_shares=bad_val)
            with self.assertRaises(ValueError):
                ExecutionConfig(estimated_order_value_vnd=bad_val)

    def test_exec_config_validation_bool_and_str(self):
        """Test ExecutionConfig raises ValueError for boolean or string numeric configuration fields."""
        for bad_val in [True, False, "1.0", "invalid"]:
            with self.assertRaises(ValueError):
                ExecutionConfig(min_avg_traded_value_bn=bad_val)
            with self.assertRaises(ValueError):
                ExecutionConfig(min_avg_volume=bad_val)
            with self.assertRaises(ValueError):
                ExecutionConfig(min_price=bad_val)
            with self.assertRaises(ValueError):
                ExecutionConfig(max_participation_rate=bad_val)
            with self.assertRaises(ValueError):
                ExecutionConfig(estimated_order_size_shares=bad_val)
            with self.assertRaises(ValueError):
                ExecutionConfig(estimated_order_value_vnd=bad_val)

    def test_exec_config_validation_negative_thresholds(self):
        """Test ExecutionConfig raises ValueError for negative liquidity thresholds."""
        with self.assertRaises(ValueError):
            ExecutionConfig(min_avg_traded_value_bn=-1.0)
        with self.assertRaises(ValueError):
            ExecutionConfig(min_avg_volume=-500.0)
        with self.assertRaises(ValueError):
            ExecutionConfig(min_price=-1000.0)

    def test_exec_config_validation_participation_rate(self):
        """Test ExecutionConfig raises ValueError for invalid max_participation_rate <= 0 or > 1.0."""
        with self.assertRaises(ValueError):
            ExecutionConfig(max_participation_rate=0.0)
        with self.assertRaises(ValueError):
            ExecutionConfig(max_participation_rate=-0.1)
        with self.assertRaises(ValueError):
            ExecutionConfig(max_participation_rate=1.05)

    def test_exec_config_validation_negative_order_size_or_value(self):
        """Test ExecutionConfig raises ValueError for negative order size or order value."""
        with self.assertRaises(ValueError):
            ExecutionConfig(estimated_order_size_shares=-100.0)
        with self.assertRaises(ValueError):
            ExecutionConfig(estimated_order_value_vnd=-50000.0)

    def test_exec_config_validation_both_order_sizes_supplied(self):
        """Test ExecutionConfig raises ValueError when both order size fields are supplied."""
        with self.assertRaises(ValueError):
            ExecutionConfig(
                estimated_order_size_shares=1000.0,
                estimated_order_value_vnd=50000000.0,
            )

    def test_exec_config_neither_order_size_supplied_unevaluated(self):
        """Test participation rate remains unevaluated (None) when neither order size field is supplied."""
        cfg = ExecutionConfig(
            max_participation_rate=0.01,
            estimated_order_size_shares=None,
            estimated_order_value_vnd=None,
            lookback_window=20,
        )
        elig = evaluate_execution_eligibility(self.df_stock, self.evaluation_date, cfg)
        self.assertIsNone(elig.metrics["estimated_participation_rate"])
        # Should remain executable because participation rate check was not triggered
        self.assertEqual(elig.status, STATUS_EXECUTABLE)

    def test_exec_config_valid_boundary_values_accepted(self):
        """Test ExecutionConfig accepts valid boundary values (0.0 for thresholds, 1.0 for participation, 1 for lookback)."""
        cfg = ExecutionConfig(
            min_avg_traded_value_bn=0.0,
            min_avg_volume=0.0,
            min_price=0.0,
            max_participation_rate=1.0,
            estimated_order_size_shares=0.0,
            lookback_window=1,
        )
        self.assertEqual(cfg.lookback_window, 1)
        self.assertEqual(cfg.min_avg_traded_value_bn, 0.0)

    def test_exec_a_exact_t_boundary(self):
        """Test Exec A: Exact T boundary - observation <= T used, > T ignored."""
        elig_t = evaluate_execution_eligibility(
            self.df_stock, self.evaluation_date, ExecutionConfig(lookback_window=20)
        )
        self.assertEqual(elig_t.status, STATUS_EXECUTABLE)
        self.assertTrue(elig_t.is_executable)
        self.assertEqual(elig_t.metrics["available_lookback_sessions"], 20)

    def test_exec_b_future_mutation_isolation(self):
        """Test Exec B: Future mutation - altering volume/turnover > T leaves eligibility at T identical."""
        config = ExecutionConfig(
            min_avg_traded_value_bn=1.0,
            min_avg_volume=50_000.0,
            min_price=10_000.0,
            max_participation_rate=0.10,
            estimated_order_size_shares=5_000.0,
            lookback_window=20,
        )

        elig_orig = evaluate_execution_eligibility(self.df_stock, self.evaluation_date, config)

        # Mutate post-T volume and price drastically (1,000x and 0.001x)
        df_mut = self.df_stock.copy()
        post_t = df_mut["date"] > self.evaluation_date
        df_mut.loc[post_t, "volume"] = 1.0
        df_mut.loc[post_t, "close"] = 1.0

        elig_mut = evaluate_execution_eligibility(df_mut, self.evaluation_date, config)

        self.assertEqual(elig_orig.to_dict(), elig_mut.to_dict())

    def test_exec_c_physically_misplaced_future_row_raises(self):
        """Test Exec C: Physically misplaced future row (> T before T) raises ValueError through evaluate_execution_eligibility."""
        df_normal = generate_synthetic_ohlcv(50, start_date="2025-01-01", base_price=50000.0)
        eval_d = df_normal["date"].iloc[20]

        df_misordered = pd.concat(
            [
                df_normal.iloc[:18],
                df_normal.iloc[30:31],  # Future row physically before T
                df_normal.iloc[18:],
            ],
            ignore_index=True,
        )

        with self.assertRaises(ValueError):
            evaluate_execution_eligibility(df_misordered, eval_d, ExecutionConfig())

    def test_exec_d_insufficient_history(self):
        """Test Exec D: Insufficient history <= T produces INSUFFICIENT_LIQUIDITY_HISTORY without falling back to future."""
        # Dataset with only 15 sessions <= T, but lookback_window = 20
        df_short = generate_synthetic_ohlcv(15, start_date="2025-01-01", base_price=50000.0)
        eval_d = df_short["date"].iloc[-1]

        elig = evaluate_execution_eligibility(df_short, eval_d, ExecutionConfig(lookback_window=20))

        self.assertEqual(elig.status, STATUS_INSUFFICIENT_LIQUIDITY_HISTORY)
        self.assertFalse(elig.is_executable)
        self.assertIn(REASON_INSUFFICIENT_LOOKBACK_SESSIONS, elig.reasons)
        self.assertEqual(elig.metrics["available_lookback_sessions"], 15)

    def test_exec_e_temporal_violations_raise_value_error(self):
        """Test Exec E: Duplicate dates, unsorted dates, or missing evaluation date raise ValueError."""
        eval_d = self.df_stock["date"].iloc[30]

        # Duplicate dates <= T
        df_dup = self.df_stock.copy()
        df_dup.iloc[5] = df_dup.iloc[4]
        with self.assertRaises(ValueError):
            evaluate_execution_eligibility(df_dup, eval_d)

        # Unsorted dates <= T
        df_unsorted = self.df_stock.copy()
        tmp = df_unsorted.iloc[10].copy()
        df_unsorted.iloc[10] = df_unsorted.iloc[12]
        df_unsorted.iloc[12] = tmp
        with self.assertRaises(ValueError):
            evaluate_execution_eligibility(df_unsorted, eval_d)

        # Missing exact evaluation date
        with self.assertRaises(ValueError):
            evaluate_execution_eligibility(self.df_stock, "2020-01-01")

    def test_exec_f_deterministic_rerun(self):
        """Test Exec F: Deterministic rerun gives identical byte-for-byte / struct output."""
        config = ExecutionConfig(
            min_avg_traded_value_bn=2.0,
            min_avg_volume=100_000.0,
            min_price=20_000.0,
            max_participation_rate=0.05,
            estimated_order_size_shares=20_000.0,
        )

        run1 = evaluate_execution_eligibility(self.df_stock, self.evaluation_date, config)
        run2 = evaluate_execution_eligibility(self.df_stock, self.evaluation_date, config)

        self.assertEqual(run1.to_dict(), run2.to_dict())

    def test_exec_g_threshold_boundary_and_precision(self):
        """Test Exec G: Threshold boundary checks (exact, below, above, participation boundary)."""
        dates = pd.date_range("2025-01-01", periods=20, freq="B").strftime("%Y-%m-%d")
        # Fixed 20 sessions: close = 10,000 VND, volume = 100,000 shares
        # Daily traded value = 1,000,000,000 VND = 1.0 billion VND
        df_exact = pd.DataFrame(
            {
                "date": dates,
                "open": [10000.0] * 20,
                "high": [10000.0] * 20,
                "low": [10000.0] * 20,
                "close": [10000.0] * 20,
                "volume": [100000.0] * 20,
            }
        )
        eval_d = dates[-1]

        # 1. Exact minimums -> Executable
        config_exact = ExecutionConfig(
            min_avg_traded_value_bn=1.0,
            min_avg_volume=100_000.0,
            min_price=10_000.0,
            max_participation_rate=0.10,
            estimated_order_size_shares=10_000.0,  # 10,000 / 100,000 = 0.10 participation
            lookback_window=20,
        )
        elig = evaluate_execution_eligibility(df_exact, eval_d, config_exact)
        self.assertEqual(elig.status, STATUS_EXECUTABLE)
        self.assertTrue(elig.is_executable)
        self.assertEqual(elig.reasons, [])

        # 2. Below minimum traded value
        config_high_tv = ExecutionConfig(min_avg_traded_value_bn=1.5, lookback_window=20)
        elig_high_tv = evaluate_execution_eligibility(df_exact, eval_d, config_high_tv)
        self.assertEqual(elig_high_tv.status, STATUS_NOT_EXECUTABLE)
        self.assertIn(REASON_BELOW_MIN_TRADED_VALUE, elig_high_tv.reasons)

        # 3. Below minimum volume
        config_high_vol = ExecutionConfig(min_avg_volume=200_000.0, lookback_window=20)
        elig_high_vol = evaluate_execution_eligibility(df_exact, eval_d, config_high_vol)
        self.assertEqual(elig_high_vol.status, STATUS_NOT_EXECUTABLE)
        self.assertIn(REASON_BELOW_MIN_VOLUME, elig_high_vol.reasons)

        # 4. Below minimum price
        config_high_p = ExecutionConfig(min_price=20_000.0, lookback_window=20)
        elig_high_p = evaluate_execution_eligibility(df_exact, eval_d, config_high_p)
        self.assertEqual(elig_high_p.status, STATUS_NOT_EXECUTABLE)
        self.assertIn(REASON_BELOW_MIN_PRICE, elig_high_p.reasons)

        # 5. Exceeds max participation rate
        config_part = ExecutionConfig(
            max_participation_rate=0.05,
            estimated_order_size_shares=10_000.0,  # 10,000 / 100,000 = 0.10 > 0.05
            lookback_window=20,
        )
        elig_part = evaluate_execution_eligibility(df_exact, eval_d, config_part)
        self.assertEqual(elig_part.status, STATUS_NOT_EXECUTABLE)
        self.assertIn(REASON_EXCEEDS_MAX_PARTICIPATION, elig_part.reasons)

    def test_exec_h_walk_forward_integration(self):
        """Test Exec H: Walk-forward integration consistently evaluates execution eligibility across dates."""
        eval_dates = [self.df_stock["date"].iloc[50], self.df_stock["date"].iloc[60]]

        exec_cfg = ExecutionConfig(
            min_avg_traded_value_bn=1.0,
            min_avg_volume=50_000.0,
            min_price=10_000.0,
            lookback_window=20,
        )

        wf_res = run_walk_forward_backtest(
            evaluation_dates=eval_dates,
            df_stock=self.df_stock,
            symbol="TCB",
            execution_config=exec_cfg,
        )

        for res in wf_res.results:
            self.assertIsNotNone(res.signal.execution_eligibility)
            self.assertEqual(res.signal.execution_eligibility.status, STATUS_EXECUTABLE)

        exec_sum = wf_res.aggregate.get("execution_summary")
        self.assertIsNotNone(exec_sum)
        self.assertEqual(exec_sum["total_evaluation_points"], 2)
        self.assertEqual(exec_sum["execution_evaluated_points"], 2)
        self.assertEqual(exec_sum["executable_count"], 2)
        self.assertEqual(exec_sum["executable_ratio"], 1.0)

    def test_exec_mixed_inputs_aggregation(self):
        """Test aggregate_backtest_results() correctly handles mixed results (some with execution eligibility, some without)."""
        exec_cfg = ExecutionConfig(
            min_avg_traded_value_bn=1.0,
            min_avg_volume=50_000.0,
            min_price=10_000.0,
            lookback_window=20,
        )

        # 2 results WITH execution eligibility (both executable)
        res_exec1 = run_backtest_for_symbol(
            "TCB", self.df_stock, [self.df_stock["date"].iloc[50]], execution_config=exec_cfg
        )[0]
        res_exec2 = run_backtest_for_symbol(
            "TCB", self.df_stock, [self.df_stock["date"].iloc[60]], execution_config=exec_cfg
        )[0]

        # 2 results WITHOUT execution eligibility (execution_config=None)
        res_no_exec1 = run_backtest_for_symbol(
            "TCB", self.df_stock, [self.df_stock["date"].iloc[70]], execution_config=None
        )[0]
        res_no_exec2 = run_backtest_for_symbol(
            "TCB", self.df_stock, [self.df_stock["date"].iloc[80]], execution_config=None
        )[0]

        mixed_results = [res_exec1, res_exec2, res_no_exec1, res_no_exec2]
        summary = aggregate_backtest_results(mixed_results, horizons=[5, 10, 20])

        exec_sum = summary.get("execution_summary")
        self.assertIsNotNone(exec_sum)
        self.assertEqual(exec_sum["total_evaluation_points"], 4)
        self.assertEqual(exec_sum["execution_evaluated_points"], 2)
        self.assertEqual(exec_sum["executable_count"], 2)
        self.assertEqual(exec_sum["executable_ratio"], 1.0)


class TestMarketRegimeValidationFramework(unittest.TestCase):
    """Test suite verifying PR #92 Market-Regime Validation Layer."""

    def setUp(self):
        self.df_vnindex = generate_synthetic_ohlcv(
            num_days=100, start_date="2025-01-01", base_price=1200.0, daily_trend=0.001
        )
        self.df_vn30 = generate_synthetic_ohlcv(
            num_days=100, start_date="2025-01-01", base_price=1250.0, daily_trend=0.001
        )
        self.evaluation_date = self.df_vnindex["date"].iloc[50]

    def test_regime_val_1_basic_evaluation(self):
        """Test Regime Val 1: Observation creation, regime label, regime score, evaluation date, and 5/10/20 forward outcomes."""
        eval_d = self.df_vnindex["date"].iloc[50]  # T = index 50

        res = evaluate_market_regimes(
            df_vnindex=self.df_vnindex,
            evaluation_dates=[eval_d],
            df_vn30=self.df_vn30,
            breadth_ratio=0.70,
            horizons=[5, 10, 20],
        )

        self.assertIsInstance(res, RegimeEvaluationResult)
        self.assertEqual(len(res.observations), 3)  # 3 horizons: 5, 10, 20

        # Check direct output of detect_market_regime for identical point-in-time input <= T
        df_vn_pit = get_as_of_dataset(self.df_vnindex, eval_d)
        df_vn30_pit = get_as_of_dataset(self.df_vn30, eval_d)
        expected_regime = detect_market_regime(
            df_vnindex=df_vn_pit,
            df_vn30=df_vn30_pit,
            breadth_ratio=0.70,
        )

        for obs in res.observations:
            self.assertEqual(obs.evaluation_date, eval_d)
            self.assertEqual(obs.regime, expected_regime["regime"])
            self.assertEqual(obs.regime_score, expected_regime["regime_score"])
            self.assertEqual(obs.confidence, expected_regime["confidence"])
            self.assertTrue(obs.availability)

        # Check forward return formula exactness
        p_T = self.df_vnindex["close"].iloc[50]
        p_T5 = self.df_vnindex["close"].iloc[55]
        p_T10 = self.df_vnindex["close"].iloc[60]
        p_T20 = self.df_vnindex["close"].iloc[70]

        obs_5 = next(o for o in res.observations if o.horizon == 5)
        obs_10 = next(o for o in res.observations if o.horizon == 10)
        obs_20 = next(o for o in res.observations if o.horizon == 20)

        self.assertAlmostEqual(obs_5.forward_return, round((p_T5 / p_T) - 1.0, 6), places=5)
        self.assertAlmostEqual(obs_10.forward_return, round((p_T10 / p_T) - 1.0, 6), places=5)
        self.assertAlmostEqual(obs_20.forward_return, round((p_T20 / p_T) - 1.0, 6), places=5)

    def test_regime_val_2_no_lookahead_future_mutation(self):
        """Test Regime Val 2: Mutating VNINDEX, VN30, or market breadth strictly AFTER T cannot change regime at T."""
        eval_d = self.df_vnindex["date"].iloc[60]

        universe_stock_map = {
            "TCB": generate_synthetic_ohlcv(100, base_price=50.0),
            "ACB": generate_synthetic_ohlcv(100, base_price=25.0),
        }

        res_orig = evaluate_market_regimes(
            df_vnindex=self.df_vnindex,
            evaluation_dates=[eval_d],
            df_vn30=self.df_vn30,
            universe_stock_map=universe_stock_map,
        )
        obs_orig = res_orig.observations[0]

        # Mutate post-T VNINDEX, VN30, and stock prices
        df_vn_mut = self.df_vnindex.copy()
        df_vn_mut.loc[df_vn_mut["date"] > eval_d, ["open", "high", "low", "close"]] *= 0.05

        df_vn30_mut = self.df_vn30.copy()
        df_vn30_mut.loc[df_vn30_mut["date"] > eval_d, ["open", "high", "low", "close"]] *= 0.05

        univ_mut = {}
        for s, df_s in universe_stock_map.items():
            df_m = df_s.copy()
            df_m.loc[df_m["date"] > eval_d, ["open", "high", "low", "close"]] *= 10.0
            univ_mut[s] = df_m

        res_mut = evaluate_market_regimes(
            df_vnindex=df_vn_mut,
            evaluation_dates=[eval_d],
            df_vn30=df_vn30_mut,
            universe_stock_map=univ_mut,
        )
        obs_mut = res_mut.observations[0]

        self.assertEqual(obs_orig.regime, obs_mut.regime)
        self.assertEqual(obs_orig.regime_score, obs_mut.regime_score)
        self.assertEqual(obs_orig.confidence, obs_mut.confidence)
        self.assertEqual(obs_orig.regime_metrics, obs_mut.regime_metrics)

        # Future outcomes should differ due to mutated post-T VNINDEX prices
        self.assertNotEqual(obs_orig.forward_return, obs_mut.forward_return)

    def test_regime_val_3_misordered_future_row_fails_closed(self):
        """Test Regime Val 3: Physically placing a future row (> T) before T fails closed."""
        df_normal = generate_synthetic_ohlcv(50, start_date="2025-01-01")
        eval_d = df_normal["date"].iloc[20]

        df_misordered = pd.concat(
            [
                df_normal.iloc[:18],
                df_normal.iloc[30:31],  # Future row physically placed before T
                df_normal.iloc[18:],
            ],
            ignore_index=True,
        )

        with self.assertRaises(ValueError):
            evaluate_market_regimes(
                df_vnindex=df_misordered,
                evaluation_dates=[eval_d],
            )

    def test_regime_val_4_temporal_validation_fail_closed(self):
        """Test Regime Val 4: Duplicate, unsorted, invalid, or missing dates fail closed."""
        eval_d = self.df_vnindex["date"].iloc[30]

        # 1. Duplicate dates <= T
        df_dup = self.df_vnindex.copy()
        df_dup.iloc[5] = df_dup.iloc[4]
        with self.assertRaises(ValueError):
            evaluate_market_regimes(df_vnindex=df_dup, evaluation_dates=[eval_d])

        # 2. Unsorted dates <= T
        df_unsorted = self.df_vnindex.copy()
        tmp = df_unsorted.iloc[10].copy()
        df_unsorted.iloc[10] = df_unsorted.iloc[12]
        df_unsorted.iloc[12] = tmp
        with self.assertRaises(ValueError):
            evaluate_market_regimes(df_vnindex=df_unsorted, evaluation_dates=[eval_d])

        # 3. Missing exact evaluation date
        with self.assertRaises(ValueError):
            evaluate_market_regimes(df_vnindex=self.df_vnindex, evaluation_dates=["2020-01-01"])

        # 4. Unsorted evaluation_dates list
        dates_unsorted = [self.df_vnindex["date"].iloc[40], self.df_vnindex["date"].iloc[30]]
        with self.assertRaises(ValueError):
            evaluate_market_regimes(df_vnindex=self.df_vnindex, evaluation_dates=dates_unsorted)

        # 5. Duplicate evaluation_dates list
        dates_dup = [eval_d, eval_d]
        with self.assertRaises(ValueError):
            evaluate_market_regimes(df_vnindex=self.df_vnindex, evaluation_dates=dates_dup)

    def test_regime_val_5_insufficient_future_data(self):
        """Test Regime Val 5: Evaluation date near end of history produces returns=None and availability=False."""
        eval_d = self.df_vnindex["date"].iloc[-3]  # Only 2 future sessions remain

        res = evaluate_market_regimes(
            df_vnindex=self.df_vnindex,
            evaluation_dates=[eval_d],
            horizons=[5, 10, 20],
        )

        for obs in res.observations:
            self.assertFalse(obs.availability)
            self.assertIsNone(obs.forward_return)

    def test_regime_val_6_regime_consistency(self):
        """Test Regime Val 6: Validation layer regime output matches direct detect_market_regime output for identical PIT inputs."""
        eval_dates = [
            self.df_vnindex["date"].iloc[30],
            self.df_vnindex["date"].iloc[50],
            self.df_vnindex["date"].iloc[70],
        ]

        res = evaluate_market_regimes(
            df_vnindex=self.df_vnindex,
            evaluation_dates=eval_dates,
            df_vn30=self.df_vn30,
            breadth_ratio=0.60,
        )

        for eval_d in eval_dates:
            df_vn_pit = get_as_of_dataset(self.df_vnindex, eval_d)
            df_vn30_pit = get_as_of_dataset(self.df_vn30, eval_d)
            direct_regime = detect_market_regime(
                df_vnindex=df_vn_pit,
                df_vn30=df_vn30_pit,
                breadth_ratio=0.60,
            )

            obs_list = [o for o in res.observations if o.evaluation_date == eval_d]
            for obs in obs_list:
                self.assertEqual(obs.regime, direct_regime["regime"])
                self.assertEqual(obs.regime_score, direct_regime["regime_score"])
                self.assertEqual(obs.confidence, direct_regime["confidence"])

    def test_regime_val_7_determinism(self):
        """Test Regime Val 7: Repeated evaluations produce 100% identical observations and aggregate outputs."""
        eval_dates = [
            self.df_vnindex["date"].iloc[40],
            self.df_vnindex["date"].iloc[60],
        ]

        res1 = evaluate_market_regimes(
            df_vnindex=self.df_vnindex,
            evaluation_dates=eval_dates,
            df_vn30=self.df_vn30,
            breadth_ratio=0.55,
        )
        res2 = evaluate_market_regimes(
            df_vnindex=self.df_vnindex,
            evaluation_dates=eval_dates,
            df_vn30=self.df_vn30,
            breadth_ratio=0.55,
        )

        self.assertEqual(res1.to_dict(), res2.to_dict())

    def test_regime_val_8_aggregation_and_denominators(self):
        """Test Regime Val 8: Grouped metrics distinguish total_observations, available_count, unavailable_count."""
        obs1 = RegimeObservation(
            evaluation_date="2025-01-10",
            regime="STRONG_BULL",
            regime_score=85.0,
            confidence=0.85,
            horizon=5,
            forward_return=0.03,
            availability=True,
        )
        obs2 = RegimeObservation(
            evaluation_date="2025-01-20",
            regime="STRONG_BULL",
            regime_score=80.0,
            confidence=0.85,
            horizon=5,
            forward_return=0.01,
            availability=True,
        )
        obs3 = RegimeObservation(
            evaluation_date="2025-02-01",
            regime="STRONG_BULL",
            regime_score=82.0,
            confidence=0.85,
            horizon=5,
            forward_return=None,
            availability=False,
        )

        obs4 = RegimeObservation(
            evaluation_date="2025-01-10",
            regime="BEAR",
            regime_score=30.0,
            confidence=0.85,
            horizon=5,
            forward_return=-0.04,
            availability=True,
        )

        agg = aggregate_regime_evaluation_results(
            observations=[obs1, obs2, obs3, obs4],
            horizons=[5],
        )

        sb_5 = agg["by_regime"]["STRONG_BULL"][5]
        self.assertEqual(sb_5["observation_count"], 3)
        self.assertEqual(sb_5["available_forward_outcome_count"], 2)
        self.assertEqual(sb_5["unavailable_forward_outcome_count"], 1)
        self.assertAlmostEqual(sb_5["mean"], 0.02, places=4)
        self.assertEqual(sb_5["positive_return_rate"], 1.0)  # Both available returns > 0

        bear_5 = agg["by_regime"]["BEAR"][5]
        self.assertEqual(bear_5["observation_count"], 1)
        self.assertEqual(bear_5["available_forward_outcome_count"], 1)
        self.assertEqual(bear_5["unavailable_forward_outcome_count"], 0)
        self.assertAlmostEqual(bear_5["mean"], -0.04, places=4)
        self.assertEqual(
            bear_5["positive_return_rate"], 0.0
        )  # Return -0.04 is not > 0 -> positive_return_rate = 0.0

    def test_regime_val_9_insufficient_history(self):
        """Test Regime Val 9: Insufficient market history (< 20 sessions) preserves detect_market_regime insufficient result."""
        # Single evaluation date on short history (10 sessions)
        df_short = self.df_vnindex.iloc[:10].copy()
        eval_d = df_short["date"].iloc[-1]

        # detect_market_regime on < 20 sessions returns DEFENSIVE, 50.0 score, 0.40 confidence
        res_direct = detect_market_regime(df_vnindex=df_short)
        self.assertEqual(res_direct["regime"], "DEFENSIVE")
        self.assertEqual(res_direct["regime_score"], 50.0)

        res = evaluate_market_regimes(
            df_vnindex=df_short,
            evaluation_dates=[eval_d],
            min_history=1,
        )

        for obs in res.observations:
            self.assertEqual(obs.regime, "DEFENSIVE")
            self.assertEqual(obs.regime_score, 50.0)
            self.assertEqual(obs.confidence, 0.40)

    def test_regime_val_10_vn30_temporal_violations_fail_closed(self):
        """Test Regime Val 10: Supplied VN30 with duplicate, unsorted, misordered future row, or missing T raises ValueError."""
        eval_d = self.df_vnindex["date"].iloc[50]

        # 1. Duplicate dates in VN30
        df_vn30_dup = self.df_vn30.copy()
        df_vn30_dup.iloc[5] = df_vn30_dup.iloc[4]
        with self.assertRaises(ValueError):
            evaluate_market_regimes(
                df_vnindex=self.df_vnindex,
                evaluation_dates=[eval_d],
                df_vn30=df_vn30_dup,
            )

        # 2. Unsorted dates in VN30
        df_vn30_unsorted = self.df_vn30.copy()
        tmp = df_vn30_unsorted.iloc[10].copy()
        df_vn30_unsorted.iloc[10] = df_vn30_unsorted.iloc[12]
        df_vn30_unsorted.iloc[12] = tmp
        with self.assertRaises(ValueError):
            evaluate_market_regimes(
                df_vnindex=self.df_vnindex,
                evaluation_dates=[eval_d],
                df_vn30=df_vn30_unsorted,
            )

        # 3. Misordered future row physically before T in VN30
        df_vn30_normal = generate_synthetic_ohlcv(50, start_date="2025-01-01")
        df_vn30_misordered = pd.concat(
            [
                df_vn30_normal.iloc[:18],
                df_vn30_normal.iloc[30:31],
                df_vn30_normal.iloc[18:],
            ],
            ignore_index=True,
        )
        with self.assertRaises(ValueError):
            evaluate_market_regimes(
                df_vnindex=self.df_vnindex,
                evaluation_dates=[eval_d],
                df_vn30=df_vn30_misordered,
            )

        # 4. Missing exact evaluation date T in VN30
        df_vn30_different_dates = generate_synthetic_ohlcv(50, start_date="2026-01-01")
        with self.assertRaises(ValueError):
            evaluate_market_regimes(
                df_vnindex=self.df_vnindex,
                evaluation_dates=[eval_d],
                df_vn30=df_vn30_different_dates,
            )

    def test_regime_val_11_omitted_vn30_supported_empty_raises(self):
        """Test Regime Val 11: Omitted VN30 (df_vn30=None) remains valid, while supplied empty VN30 (pd.DataFrame()) raises ValueError."""
        eval_d = self.df_vnindex["date"].iloc[50]

        # Omitted VN30 (None) -> valid
        res = evaluate_market_regimes(
            df_vnindex=self.df_vnindex,
            evaluation_dates=[eval_d],
            df_vn30=None,
        )
        self.assertEqual(len(res.observations), 3)
        self.assertIsNotNone(res.observations[0].regime)

        # Supplied empty DataFrame -> raises ValueError fail-closed
        with self.assertRaises(ValueError):
            evaluate_market_regimes(
                df_vnindex=self.df_vnindex,
                evaluation_dates=[eval_d],
                df_vn30=pd.DataFrame(),
            )

    def test_regime_val_12_parse_canonical_date_contract_rigorous(self):
        """Test Regime Val 12: _parse_canonical_date accepts YYYY-MM-DD and naive calendar pd.Timestamp, rejecting time components, timezones, booleans, and invalid inputs."""
        from scripts.lib.backtest import _parse_canonical_date

        # 1. "2025-01-10" -> accepted and canonicalized
        self.assertEqual(_parse_canonical_date("2025-01-10"), "2025-01-10")

        # 2. Naive pd.Timestamp("2025-01-10") -> accepted
        self.assertEqual(_parse_canonical_date(pd.Timestamp("2025-01-10")), "2025-01-10")

        # 3. "2025-01-10 15:30:00" string containing time component -> rejected
        with self.assertRaises(ValueError):
            _parse_canonical_date("2025-01-10 15:30:00")

        # 4. Timestamp with non-zero time component -> rejected
        with self.assertRaises(ValueError):
            _parse_canonical_date(pd.Timestamp("2025-01-10 15:30:00"))

        # 5. Timezone-aware pd.Timestamp -> rejected
        with self.assertRaises(ValueError):
            _parse_canonical_date(pd.Timestamp("2025-01-10 00:00:00", tz="UTC"))

        # 6. Timezone-bearing string -> rejected
        with self.assertRaises(ValueError):
            _parse_canonical_date("2025-01-10T00:00:00+07:00")

        # 7. Boolean -> rejected
        with self.assertRaises(ValueError):
            _parse_canonical_date(True)

        # 8. Invalid date string -> rejected
        with self.assertRaises(ValueError):
            _parse_canonical_date("not-a-valid-date")


class TestConfidenceCalibration(unittest.TestCase):
    """Test suite verifying historical recommendation confidence calibration layer."""

    def setUp(self):
        self.df_stock = generate_synthetic_ohlcv(
            num_days=100, start_date="2025-01-01", base_price=50.0, daily_trend=0.002
        )
        self.df_vnindex = generate_synthetic_ohlcv(
            num_days=100, start_date="2025-01-01", base_price=1200.0, daily_trend=0.001
        )
        self.df_vn30 = generate_synthetic_ohlcv(
            num_days=100, start_date="2025-01-01", base_price=1250.0, daily_trend=0.001
        )

    def test_classify_confidence_bucket_boundaries_and_invalid(self):
        """Test boundary classification and fail-closed validation for confidence values."""
        # Boundaries
        self.assertEqual(classify_confidence_bucket(0.0), "[0.0, 0.1)")
        self.assertEqual(classify_confidence_bucket(0.0999), "[0.0, 0.1)")
        self.assertEqual(classify_confidence_bucket(0.1), "[0.1, 0.2)")
        self.assertEqual(classify_confidence_bucket(0.1001), "[0.1, 0.2)")
        self.assertEqual(classify_confidence_bucket(0.2), "[0.2, 0.3)")
        self.assertEqual(classify_confidence_bucket(0.3), "[0.3, 0.4)")
        self.assertEqual(classify_confidence_bucket(0.4), "[0.4, 0.5)")
        self.assertEqual(classify_confidence_bucket(0.5), "[0.5, 0.6)")
        self.assertEqual(classify_confidence_bucket(0.6), "[0.6, 0.7)")
        self.assertEqual(classify_confidence_bucket(0.7), "[0.7, 0.8)")
        self.assertEqual(classify_confidence_bucket(0.8), "[0.8, 0.9)")
        self.assertEqual(classify_confidence_bucket(0.8999), "[0.8, 0.9)")
        self.assertEqual(classify_confidence_bucket(0.9), "[0.9, 1.0]")
        self.assertEqual(classify_confidence_bucket(0.95), "[0.9, 1.0]")
        self.assertEqual(classify_confidence_bucket(1.0), "[0.9, 1.0]")

        # Invalid confidence inputs fail closed
        invalid_inputs = [
            float("nan"),
            float("inf"),
            float("-inf"),
            -0.01,
            1.01,
            None,
            True,
            False,
            "0.5",
            [0.5],
        ]
        for inv in invalid_inputs:
            with self.assertRaises((ValueError, TypeError)):
                classify_confidence_bucket(inv)

    def test_calibration_gap_and_brier_score_exact_calculation(self):
        """Test exact calculation of mean confidence, positive return rate, calibration gap, and Brier score."""
        # 4 observations with confidence = 0.80 ([0.8, 0.9) bucket)
        # Outcomes: 3 positive returns (> 0), 1 negative return (< 0)
        # Positive return rate = 3/4 = 0.75
        # Mean confidence = 0.80
        # Calibration gap = 0.75 - 0.80 = -0.05
        # Brier score = ((0.8-1)^2 * 3 + (0.8-0)^2 * 1) / 4 = (0.12 + 0.64) / 4 = 0.19
        obs_list = [
            ConfidenceObservation(
                evaluation_date="2025-01-10",
                symbol="AAA",
                action="BUY",
                confidence=0.80,
                signal_score=75.0,
                market_regime="BULL",
                confidence_bucket="[0.8, 0.9)",
                forward_returns={5: 0.05},
                availability={5: True},
            ),
            ConfidenceObservation(
                evaluation_date="2025-01-10",
                symbol="BBB",
                action="BUY",
                confidence=0.80,
                signal_score=75.0,
                market_regime="BULL",
                confidence_bucket="[0.8, 0.9)",
                forward_returns={5: 0.03},
                availability={5: True},
            ),
            ConfidenceObservation(
                evaluation_date="2025-01-10",
                symbol="CCC",
                action="BUY",
                confidence=0.80,
                signal_score=75.0,
                market_regime="BULL",
                confidence_bucket="[0.8, 0.9)",
                forward_returns={5: 0.01},
                availability={5: True},
            ),
            ConfidenceObservation(
                evaluation_date="2025-01-10",
                symbol="DDD",
                action="BUY",
                confidence=0.80,
                signal_score=75.0,
                market_regime="BULL",
                confidence_bucket="[0.8, 0.9)",
                forward_returns={5: -0.02},
                availability={5: True},
            ),
        ]

        agg = aggregate_confidence_calibration_results(obs_list, horizons=[5])
        bucket_stats = agg["by_bucket"]["[0.8, 0.9)"][5]

        self.assertEqual(bucket_stats["observation_count"], 4)
        self.assertEqual(bucket_stats["available_outcome_count"], 4)
        self.assertEqual(bucket_stats["unavailable_outcome_count"], 0)
        self.assertEqual(bucket_stats["positive_return_rate"], 0.75)
        self.assertEqual(bucket_stats["observed_outcome_rate"], 0.75)
        self.assertEqual(bucket_stats["mean_confidence"], 0.80)
        self.assertAlmostEqual(bucket_stats["calibration_gap"], -0.05, places=5)
        self.assertAlmostEqual(bucket_stats["brier_score"], 0.19, places=5)

    def test_missing_outcomes_handling(self):
        """Verify unavailable forward outcomes are omitted from return stats and not filled with zero or negative."""
        obs_list = [
            ConfidenceObservation(
                evaluation_date="2025-01-10",
                symbol="AAA",
                action="BUY",
                confidence=0.85,
                signal_score=80.0,
                market_regime="BULL",
                confidence_bucket="[0.8, 0.9)",
                forward_returns={5: 0.10, 10: None},
                availability={5: True, 10: False},
            ),
            ConfidenceObservation(
                evaluation_date="2025-01-10",
                symbol="BBB",
                action="BUY",
                confidence=0.85,
                signal_score=80.0,
                market_regime="BULL",
                confidence_bucket="[0.8, 0.9)",
                forward_returns={5: None, 10: None},
                availability={5: False, 10: False},
            ),
        ]

        agg = aggregate_confidence_calibration_results(obs_list, horizons=[5, 10])

        # Horizon 5
        h5_stats = agg["by_bucket"]["[0.8, 0.9)"][5]
        self.assertEqual(h5_stats["observation_count"], 2)
        self.assertEqual(h5_stats["available_outcome_count"], 1)
        self.assertEqual(h5_stats["unavailable_outcome_count"], 1)
        self.assertEqual(h5_stats["mean_forward_return"], 0.10)
        self.assertEqual(h5_stats["positive_return_rate"], 1.0)

        # Horizon 10 (all unavailable)
        h10_stats = agg["by_bucket"]["[0.8, 0.9)"][10]
        self.assertEqual(h10_stats["observation_count"], 2)
        self.assertEqual(h10_stats["available_outcome_count"], 0)
        self.assertEqual(h10_stats["unavailable_outcome_count"], 2)
        self.assertIsNone(h10_stats["mean_forward_return"])
        self.assertIsNone(h10_stats["positive_return_rate"])
        self.assertIsNone(h10_stats["calibration_gap"])
        self.assertIsNone(h10_stats["brier_score"])

    def test_evaluate_confidence_calibration_end_to_end_and_determinism(self):
        """Verify evaluate_confidence_calibration runs end-to-end, produces deterministic output, and serializes cleanly."""
        dates = self.df_stock["date"].iloc[50:53].tolist()

        res1 = evaluate_confidence_calibration(
            evaluation_dates=dates,
            df_stock=self.df_stock,
            symbol="AAA",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            horizons=[5, 10],
            min_history=50,
        )

        res2 = evaluate_confidence_calibration(
            evaluation_dates=dates,
            df_stock=self.df_stock,
            symbol="AAA",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            horizons=[5, 10],
            min_history=50,
        )

        # Determinism check
        self.assertEqual(res1.to_dict(), res2.to_dict())
        self.assertIsInstance(res1, ConfidenceCalibrationResult)
        self.assertEqual(len(res1.observations), 3)

        dict_out = res1.to_dict()
        self.assertIn("observations", dict_out)
        self.assertIn("aggregate", dict_out)
        self.assertIn("by_bucket", dict_out["aggregate"])
        self.assertIn("by_action", dict_out["aggregate"])
        self.assertIn("overall", dict_out["aggregate"])

    def test_no_lookahead_and_temporal_validation(self):
        """Verify temporal ordering and fail-closed validation for physically misordered future data."""
        # Unsorted / misplaced future row prior to T must fail closed
        df_corrupted = self.df_stock.copy()
        # Swap rows to put future date earlier
        row_0 = df_corrupted.iloc[0].copy()
        df_corrupted.iloc[0] = df_corrupted.iloc[80]
        df_corrupted.iloc[80] = row_0

        dates = [self.df_stock["date"].iloc[50]]
        with self.assertRaises(ValueError):
            evaluate_confidence_calibration(
                evaluation_dates=dates,
                df_stock=df_corrupted,
                symbol="AAA",
            )

    def test_production_confidence_preservation(self):
        """Verify that calibration layer reads production confidence output directly without altering or recomputing it."""
        dates = [self.df_stock["date"].iloc[50]]
        res = evaluate_confidence_calibration(
            evaluation_dates=dates,
            df_stock=self.df_stock,
            symbol="AAA",
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        obs = res.observations[0]
        # Directly call production generate_recommendation at T
        df_as_of = get_as_of_dataset(self.df_stock, dates[0])
        df_vn_as_of = get_as_of_dataset(self.df_vnindex, dates[0])
        df_30_as_of = get_as_of_dataset(self.df_vn30, dates[0])

        rec = generate_recommendation(
            symbol="AAA",
            company_name="",
            sector="",
            exchange="HOSE",
            df_stock=df_as_of,
            market_regime_info=detect_market_regime(df_vnindex=df_vn_as_of, df_vn30=df_30_as_of),
            df_vnindex=df_vn_as_of,
            data_as_of=dates[0],
        )

        # Confirm confidence in observation matches production recommendation engine exactly
        self.assertEqual(obs.confidence, rec["confidence"])
        self.assertEqual(obs.action, rec["action"])
        self.assertEqual(obs.signal_score, rec["signal_score"])


if __name__ == "__main__":
    unittest.main()
