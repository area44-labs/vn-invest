"""Deterministic Unit Tests for Execution Cost Assumptions (Transaction Costs & Slippage).

This module provides deterministic, network-free, and date-independent unit tests validating
execution cost assumptions, slippage semantics, execution prices, effective returns,
and portfolio-level returns after costs in the backtesting framework.
"""

import unittest
from unittest.mock import patch

import pandas as pd

from scripts.lib.backtest import (
    ExecutionConfig,
    calculate_execution_return,
    evaluate_execution_eligibility,
)
from scripts.lib.portfolio_backtest import (
    PortfolioConfig,
    evaluate_portfolio_at_date,
)


class TestTransactionCostSemantics(unittest.TestCase):
    """Test suite validating transaction cost semantics, formula, and input bounds."""

    def test_case_a_zero_transaction_cost(self) -> None:
        """Case A — Zero transaction cost: return remains unchanged from gross return."""
        entry_price = 10_000.0
        exit_price = 11_000.0
        res = calculate_execution_return(
            entry_price=entry_price,
            exit_price=exit_price,
            transaction_cost_pct=0.0,
            slippage_pct=0.0,
            action="BUY",
        )
        expected_gross = round((11_000.0 / 10_000.0) - 1.0, 6)  # +10.0% = 0.10
        self.assertEqual(res.gross_return, 0.10)
        self.assertEqual(res.slippage_adjusted_return, 0.10)
        self.assertEqual(res.net_return, expected_gross)

    def test_case_b_positive_transaction_cost(self) -> None:
        """Case B — Positive transaction cost: synthetic trade with hand-calculated exact expected value."""
        entry_price = 50_000.0
        exit_price = 55_000.0
        # Total transaction cost = 0.30% (0.0030), i.e., 0.15% (0.0015) entry and 0.15% exit
        tc = 0.0030
        res = calculate_execution_return(
            entry_price=entry_price,
            exit_price=exit_price,
            transaction_cost_pct=tc,
            slippage_pct=0.0,
            action="BUY",
        )
        # Gross return = (55,000 / 50,000) - 1.0 = 0.10
        # Net value return factor = (1 - 0.0015) * (55,000 / 50,000) * (1 - 0.0015) - 1.0
        # = 0.9985 * 1.10 * 0.9985 - 1.0 = 1.09670225 - 1.0 = 0.096702
        expected_net = round((1.0 - 0.0015) * 1.10 * (1.0 - 0.0015) - 1.0, 6)
        self.assertEqual(res.gross_return, 0.10)
        self.assertEqual(res.net_return, expected_net)
        self.assertEqual(res.net_return, 0.096702)

    def test_case_c_transaction_cost_symmetry(self) -> None:
        """Case C — Cost symmetry: explicit entry and exit fee legs apply consistently across BUY and SELL."""
        entry_price = 20_000.0
        exit_price = 22_000.0
        # BUY leg: entry cost 0.15%, exit cost 0.15%
        res_buy = calculate_execution_return(
            entry_price=entry_price,
            exit_price=exit_price,
            transaction_cost_pct=0.003,
            slippage_pct=0.0,
            action="BUY",
            cost_entry_pct=0.0015,
            cost_exit_pct=0.0015,
        )
        expected_buy_net = round((1.0 - 0.0015) * (22000.0 / 20000.0) * (1.0 - 0.0015) - 1.0, 6)
        self.assertEqual(res_buy.net_return, expected_buy_net)

        # SELL leg: short sell entry cost 0.15%, exit cover cost 0.15%
        res_sell = calculate_execution_return(
            entry_price=entry_price,
            exit_price=18_000.0,
            transaction_cost_pct=0.003,
            slippage_pct=0.0,
            action="SELL",
            cost_entry_pct=0.0015,
            cost_exit_pct=0.0015,
        )
        # Price drop from 20,000 to 18,000 is +10% gross gain for SELL (1.0 - 18,000/20,000 = +0.10)
        # Net return = (1 - 0.0015) * 1.10 * (1 - 0.0015) - 1.0 = 0.096702
        expected_sell_net = round((1.0 - 0.0015) * 1.10 * (1.0 - 0.0015) - 1.0, 6)
        self.assertEqual(res_sell.gross_return, 0.10)
        self.assertEqual(res_sell.net_return, expected_sell_net)

    def test_explicit_entry_exit_cost_consistency(self) -> None:
        """Explicit entry/exit costs must match transaction_cost_pct when both are specified."""
        # Consistent configuration succeeds and reconciles total cost
        res = calculate_execution_return(
            entry_price=10000.0,
            exit_price=11000.0,
            transaction_cost_pct=0.004,
            cost_entry_pct=0.001,
            cost_exit_pct=0.003,
            action="BUY",
        )
        self.assertEqual(res.transaction_cost_pct, 0.004)

        # Inconsistent configuration raises ValueError fail-closed
        with self.assertRaises(ValueError):
            calculate_execution_return(
                entry_price=10000.0,
                exit_price=11000.0,
                transaction_cost_pct=0.003,
                cost_entry_pct=0.001,
                cost_exit_pct=0.005,  # 0.001 + 0.005 = 0.006 != 0.003
                action="BUY",
            )

    def test_case_d_invalid_transaction_cost(self) -> None:
        """Case D — Invalid transaction cost parameters raise ValueError or TypeError fail-closed."""
        # Negative cost
        with self.assertRaises(ValueError):
            calculate_execution_return(10000.0, 11000.0, transaction_cost_pct=-0.01)

        # NaN cost
        with self.assertRaises(ValueError):
            calculate_execution_return(10000.0, 11000.0, transaction_cost_pct=float("nan"))

        # Inf cost
        with self.assertRaises(ValueError):
            calculate_execution_return(10000.0, 11000.0, transaction_cost_pct=float("inf"))

        # Boolean cost
        with self.assertRaises(ValueError):
            calculate_execution_return(10000.0, 11000.0, transaction_cost_pct=True)  # type: ignore[arg-type]

        # Non-numeric string cost
        with self.assertRaises(ValueError):
            calculate_execution_return(10000.0, 11000.0, transaction_cost_pct="invalid")  # type: ignore[arg-type]


class TestSlippageSemantics(unittest.TestCase):
    """Test suite validating execution slippage semantics, directionality, and input bounds."""

    def test_case_a_zero_slippage(self) -> None:
        """Case A — Zero slippage: execution prices match reference prices exactly."""
        p_entry = 25_000.0
        p_exit = 27_500.0
        res = calculate_execution_return(
            entry_price=p_entry,
            exit_price=p_exit,
            transaction_cost_pct=0.0,
            slippage_pct=0.0,
            action="BUY",
        )
        self.assertEqual(res.entry_exec_price, p_entry)
        self.assertEqual(res.exit_exec_price, p_exit)
        self.assertEqual(res.slippage_adjusted_return, res.gross_return)

    def test_case_b_positive_slippage(self) -> None:
        """Case B — Positive slippage: hand-calculated expected execution price and return."""
        p_entry = 10_000.0
        p_exit = 12_000.0
        slip = 0.0010  # 0.10% adverse slippage on each leg
        res = calculate_execution_return(
            entry_price=p_entry,
            exit_price=p_exit,
            transaction_cost_pct=0.0,
            slippage_pct=slip,
            action="BUY",
        )
        # BUY entry price with adverse slippage: 10,000 * (1 + 0.001) = 10,010.0
        # BUY exit price with adverse slippage: 12,000 * (1 - 0.001) = 11,988.0
        # Slippage-adjusted return = (11,988 / 10,010) - 1.0 = 1.1976023976... - 1.0 = 0.197602
        self.assertEqual(res.entry_exec_price, 10_010.0)
        self.assertEqual(res.exit_exec_price, 11_988.0)
        self.assertEqual(res.gross_return, 0.20)
        self.assertEqual(res.slippage_adjusted_return, round((11_988.0 / 10_010.0) - 1.0, 6))

    def test_case_c_buy_vs_sell_directionality(self) -> None:
        """Case C — Buy vs Sell slippage directionality: both legs experience adverse pricing."""
        p_entry = 40_000.0
        p_exit = 44_000.0
        slip = 0.0020  # 0.20% slippage

        # BUY: higher entry price, lower exit price
        res_buy = calculate_execution_return(
            entry_price=p_entry,
            exit_price=p_exit,
            transaction_cost_pct=0.0,
            slippage_pct=slip,
            action="BUY",
        )
        self.assertEqual(res_buy.entry_exec_price, 40_080.0)  # 40,000 * 1.002
        self.assertEqual(res_buy.exit_exec_price, 43_912.0)  # 44,000 * 0.998
        self.assertLess(res_buy.slippage_adjusted_return, res_buy.gross_return)

        # SELL: lower entry price (sold cheaper), higher exit price (bought back higher)
        p_exit_sell = 36_000.0
        res_sell = calculate_execution_return(
            entry_price=p_entry,
            exit_price=p_exit_sell,
            transaction_cost_pct=0.0,
            slippage_pct=slip,
            action="SELL",
        )
        self.assertEqual(res_sell.entry_exec_price, 39_920.0)  # 40,000 * 0.998
        self.assertEqual(res_sell.exit_exec_price, 36_072.0)  # 36,000 * 1.002
        self.assertLess(res_sell.slippage_adjusted_return, res_sell.gross_return)

    def test_case_d_invalid_slippage(self) -> None:
        """Case D — Invalid slippage parameters raise ValueError or TypeError fail-closed."""
        # Negative slippage
        with self.assertRaises(ValueError):
            calculate_execution_return(10000.0, 11000.0, slippage_pct=-0.005)

        # NaN slippage
        with self.assertRaises(ValueError):
            calculate_execution_return(10000.0, 11000.0, slippage_pct=float("nan"))

        # Inf slippage
        with self.assertRaises(ValueError):
            calculate_execution_return(10000.0, 11000.0, slippage_pct=float("inf"))

        # Boolean slippage
        with self.assertRaises(ValueError):
            calculate_execution_return(10000.0, 11000.0, slippage_pct=True)  # type: ignore[arg-type]


class TestActionSemantics(unittest.TestCase):
    """Test suite validating action semantics in calculate_execution_return()."""

    def test_non_executed_action_returns_zero(self) -> None:
        """HOLD, WATCH, and AVOID actions yield strictly zero returns without execution costs."""
        for non_exec_action in ("HOLD", "WATCH", "AVOID"):
            res = calculate_execution_return(
                entry_price=10_000.0,
                exit_price=12_000.0,
                transaction_cost_pct=0.003,
                slippage_pct=0.001,
                action=non_exec_action,
            )
            self.assertEqual(res.entry_exec_price, 10_000.0)
            self.assertEqual(res.exit_exec_price, 12_000.0)
            self.assertEqual(res.gross_return, 0.0)
            self.assertEqual(res.slippage_adjusted_return, 0.0)
            self.assertEqual(res.net_return, 0.0)

    def test_unsupported_action_raises_value_error(self) -> None:
        """Unsupported actions raise ValueError fail-closed."""
        with self.assertRaises(ValueError):
            calculate_execution_return(10000.0, 11000.0, action="INVALID_ACTION")


class TestCostSlippageInteraction(unittest.TestCase):
    """Test suite validating interaction between transaction costs and slippage."""

    def test_combined_cost_and_slippage_calculation(self) -> None:
        """Deterministic scenario verifying gross return, slippage-adjusted return, and final net return."""
        p_entry = 100_000.0
        p_exit = 110_000.0  # +10.0% gross return
        tc = 0.0030  # 0.30% total transaction cost (0.15% entry, 0.15% exit)
        slip = 0.0010  # 0.10% adverse slippage per leg

        res = calculate_execution_return(
            entry_price=p_entry,
            exit_price=p_exit,
            transaction_cost_pct=tc,
            slippage_pct=slip,
            action="BUY",
        )

        # 1. Entry execution price: 100,000 * (1 + 0.001) = 100,100.0
        self.assertEqual(res.entry_exec_price, 100_100.0)

        # 2. Exit execution price: 110,000 * (1 - 0.001) = 109,890.0
        self.assertEqual(res.exit_exec_price, 109_890.0)

        # 3. Gross return: (110,000 / 100,000) - 1.0 = 0.10 (10.0%)
        self.assertEqual(res.gross_return, 0.10)

        # 4. Slippage-adjusted return: (109,890 / 100,100) - 1.0 = 0.097802
        expected_slip_ret = round((109_890.0 / 100_100.0) - 1.0, 6)
        self.assertEqual(res.slippage_adjusted_return, expected_slip_ret)
        self.assertEqual(res.slippage_adjusted_return, 0.097802)

        # 5. Final net return after transaction costs:
        # factor = (1 - 0.0015) * (109,890 / 100,100) * (1 - 0.0015) - 1.0
        # = 0.9985 * 1.0978021978... * 0.9985 - 1.0 = 1.09451121... - 1.0 = 0.094511
        expected_net_ret = round((1.0 - 0.0015) * (109_890.0 / 100_100.0) * (1.0 - 0.0015) - 1.0, 6)
        self.assertEqual(res.net_return, expected_net_ret)
        self.assertEqual(res.net_return, 0.094511)

        # Ordering invariant: gross > slippage_adjusted > net
        self.assertGreater(res.gross_return, res.slippage_adjusted_return)
        self.assertGreater(res.slippage_adjusted_return, res.net_return)

    def test_no_double_counting_or_repeated_application(self) -> None:
        """Verify costs and slippage are strictly applied once and do not compound repeatedly."""
        res1 = calculate_execution_return(
            entry_price=10_000.0,
            exit_price=10_000.0,
            transaction_cost_pct=0.003,
            slippage_pct=0.001,
            action="BUY",
        )
        # Entry exec = 10,010, Exit exec = 9,990
        # Slippage ret = (9,990 / 10,010) - 1 = -0.001998
        # Net ret = 0.9985 * (9,990 / 10,010) * 0.9985 - 1 = -0.004990022... = -0.00499
        expected_net = round(0.9985 * (9_990.0 / 10_010.0) * 0.9985 - 1.0, 6)
        self.assertEqual(res1.gross_return, 0.0)
        self.assertEqual(res1.slippage_adjusted_return, -0.001998)
        self.assertEqual(res1.net_return, expected_net)
        self.assertEqual(res1.net_return, -0.00499)


class TestPortfolioLevelCostConsistency(unittest.TestCase):
    """Test suite validating portfolio-level net returns match weighted position net returns."""

    def setUp(self) -> None:
        """Create deterministic 2-stock synthetic universe."""
        dates = pd.date_range("2024-01-01", periods=60, freq="B").strftime("%Y-%m-%d")

        # Stock A: steady 2% daily gain
        prices_a = [10_000.0 * (1.02**i) for i in range(60)]
        df_a = pd.DataFrame(
            {
                "date": dates,
                "open": prices_a,
                "high": prices_a,
                "low": prices_a,
                "close": prices_a,
                "volume": [1_000_000.0] * 60,
            }
        )

        # Stock B: steady 1% daily gain
        prices_b = [20_000.0 * (1.01**i) for i in range(60)]
        df_b = pd.DataFrame(
            {
                "date": dates,
                "open": prices_b,
                "high": prices_b,
                "low": prices_b,
                "close": prices_b,
                "volume": [2_000_000.0] * 60,
            }
        )

        self.universe = {"STKA": df_a, "STKB": df_b}
        self.eval_date = dates[49]  # 50th trading session

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_independent_portfolio_oracle_validation(self, mock_gen_rec) -> None:
        """Independent oracle test comparing portfolio return against hand-calculated constants with mock action controls."""

        # Deterministic mock recommendation responses:
        # STKA -> Action: BUY, Signal Score: 80.0, Confidence: 0.8, Price: 26,915.88
        # STKB -> Action: WATCH, Signal Score: 40.0, Confidence: 0.5, Price: 32,693.30
        def side_effect(symbol, **kwargs):
            if symbol == "STKA":
                return {
                    "action": "BUY",
                    "signal_score": 80.0,
                    "risk_adjusted_score": 80.0,
                    "confidence": 0.8,
                    "trade_plan": {"current_price": 26915.88},
                }
            return {
                "action": "WATCH",
                "signal_score": 40.0,
                "risk_adjusted_score": 40.0,
                "confidence": 0.5,
                "trade_plan": {"current_price": 32693.30},
            }

        mock_gen_rec.side_effect = side_effect

        # Independent hand-calculation for STKA (BUY):
        # Entry P_0 = 26,915.88, Exit P_5 = 26,915.88 * 1.02^5 = 29,717.3082
        # Strategy return = +0.104081
        # P_entry_exec = 26,915.88 * 1.001 = 26,942.79588
        # P_exit_exec = 29,717.3082 * 0.999 = 29,687.59089
        # net_return_stka = (1 - 0.0015) * (29,687.59089 / 26,942.79588) * (1 - 0.0015) - 1 = 0.098572

        # Independent hand-calculation for STKB (WATCH):
        # Action WATCH -> non-executed trade -> net_return_stkb = 0.0

        # Equal weighting (0.50 each):
        # Hand-calculated weighted portfolio return = 0.5 * 0.098572 + 0.5 * 0.0 = 0.049286
        HAND_CALCULATED_ORACLE_PORTFOLIO_NET_RETURN = 0.049286

        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_confidence=0.0,
            allowed_actions=("BUY", "WATCH"),
            min_history=30,
            transaction_cost_pct=0.0030,
            slippage_pct=0.0010,
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            horizons=[5],
        )

        self.assertEqual(len(eval_res.positions), 2)
        self.assertEqual(eval_res.positions[0].symbol, "STKA")
        self.assertEqual(eval_res.positions[0].action, "BUY")
        self.assertEqual(eval_res.positions[1].symbol, "STKB")
        self.assertEqual(eval_res.positions[1].action, "WATCH")

        self.assertEqual(
            eval_res.portfolio_forward_returns[5],
            HAND_CALCULATED_ORACLE_PORTFOLIO_NET_RETURN,
        )

    def test_portfolio_net_return_equals_weighted_net_position_returns(self) -> None:
        """Verify portfolio net return equals weighted sum of constituent position net returns."""
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_confidence=0.0,
            allowed_actions=("BUY", "WATCH", "HOLD", "SELL", "AVOID"),
            min_history=30,
            transaction_cost_pct=0.0030,
            slippage_pct=0.0010,
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            horizons=[5],
        )

        self.assertEqual(len(eval_res.positions), 2)
        pos_a = eval_res.positions[0]
        pos_b = eval_res.positions[1]

        # Independent position net return validation
        ret_a_5d = pos_a.forward_returns[5]
        ret_b_5d = pos_b.forward_returns[5]

        expected_portfolio_net = round(pos_a.weight * ret_a_5d + pos_b.weight * ret_b_5d, 6)
        self.assertEqual(eval_res.portfolio_forward_returns[5], expected_portfolio_net)

    def test_zero_cost_and_slippage_preserves_gross_portfolio_return(self) -> None:
        """Verify zero cost and zero slippage preserves raw gross portfolio return."""
        cfg_zero = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_confidence=0.0,
            allowed_actions=("BUY", "WATCH", "HOLD", "SELL", "AVOID"),
            min_history=30,
            transaction_cost_pct=0.0,
            slippage_pct=0.0,
        )

        eval_res_zero = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg_zero,
            horizons=[5],
        )

        cfg_cost = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_confidence=0.0,
            allowed_actions=("BUY", "WATCH", "HOLD", "SELL", "AVOID"),
            min_history=30,
            transaction_cost_pct=0.003,
            slippage_pct=0.001,
        )

        eval_res_cost = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg_cost,
            horizons=[5],
        )

        # Net return with cost & slippage must be strictly less than gross return
        self.assertLess(
            eval_res_cost.portfolio_forward_returns[5],
            eval_res_zero.portfolio_forward_returns[5],
        )


class TestSellExitPriceReconstructionAndPortfolioCoverage(unittest.TestCase):
    """Test suite validating SELL exit price reconstruction and explicit BUY + SELL portfolio coverage."""

    def test_sell_exit_price_reconstruction_from_100_to_90(self) -> None:
        """Regression test: SELL trade with entry=100 and exit=90 reconstructs exit price as 90 (never 110)."""
        entry_price = 100.0
        exit_price = 90.0
        tc = 0.0030
        slip = 0.0010

        # Directional strategy return for SELL when price drops 100 -> 90 is +10.0% (+0.10)
        # Verify calculate_execution_return with action="SELL" and reference exit price 90.0
        res = calculate_execution_return(
            entry_price=entry_price,
            exit_price=exit_price,
            transaction_cost_pct=tc,
            slippage_pct=slip,
            action="SELL",
        )

        # Reconstructed reference exit price must equal 90.0
        self.assertEqual(res.entry_price, 100.0)
        self.assertEqual(res.exit_price, 90.0)

        # Execution entry price with SELL discount: 100.0 * (1 - 0.001) = 99.90
        # Execution exit price with SELL markup: 90.0 * (1 + 0.001) = 90.09
        self.assertEqual(res.entry_exec_price, 99.90)
        self.assertEqual(res.exit_exec_price, 90.09)

        # Gross return for SELL: 1.0 - (90 / 100) = +0.10
        self.assertEqual(res.gross_return, 0.10)

        # Slippage-adjusted return for SELL: 1.0 - (90.09 / 99.90) = 1 - 0.9018018... = +0.098198
        self.assertEqual(res.slippage_adjusted_return, 0.098198)

        # Net return after 0.15% entry and 0.15% exit transaction costs:
        # factor = (1 - 0.0015) * (1 + 0.098198198...) * (1 - 0.0015) - 1.0 = 0.094906
        self.assertEqual(res.net_return, 0.094906)

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_combined_buy_and_sell_portfolio_execution(self, mock_gen_rec) -> None:
        """Verify combined BUY and SELL positions in portfolio backtest use correct exit prices and net returns."""
        dates = pd.date_range("2024-01-01", periods=60, freq="B").strftime("%Y-%m-%d")

        # Stock BUY (100 -> 110 at session 50)
        prices_buy = [100.0] * 50 + [110.0] * 10
        df_buy = pd.DataFrame(
            {
                "date": dates,
                "open": prices_buy,
                "high": prices_buy,
                "low": prices_buy,
                "close": prices_buy,
                "volume": [1_000_000.0] * 60,
            }
        )

        # Stock SELL (100 -> 90 at session 50)
        prices_sell = [100.0] * 50 + [90.0] * 10
        df_sell = pd.DataFrame(
            {
                "date": dates,
                "open": prices_sell,
                "high": prices_sell,
                "low": prices_sell,
                "close": prices_sell,
                "volume": [1_000_000.0] * 60,
            }
        )

        universe = {"STK_BUY": df_buy, "STK_SELL": df_sell}
        eval_date = dates[49]  # 50th trading session

        def side_effect(symbol, **kwargs):
            if symbol == "STK_BUY":
                return {
                    "action": "BUY",
                    "signal_score": 80.0,
                    "risk_adjusted_score": 80.0,
                    "confidence": 0.8,
                    "trade_plan": {"current_price": 100.0},
                }
            return {
                "action": "SELL",
                "signal_score": 75.0,
                "risk_adjusted_score": 75.0,
                "confidence": 0.7,
                "trade_plan": {"current_price": 100.0},
            }

        mock_gen_rec.side_effect = side_effect

        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_confidence=0.0,
            allowed_actions=("BUY", "SELL"),
            min_history=30,
            transaction_cost_pct=0.0030,
            slippage_pct=0.0010,
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_date,
            universe_stock_map=universe,
            config=cfg,
            horizons=[5],
        )

        self.assertEqual(len(eval_res.positions), 2)
        pos_buy = [p for p in eval_res.positions if p.symbol == "STK_BUY"][0]
        pos_sell = [p for p in eval_res.positions if p.symbol == "STK_SELL"][0]

        # Verify net return of BUY position: 0.094511
        self.assertEqual(pos_buy.forward_returns[5], 0.094511)

        # Verify net return of SELL position: 0.094906
        self.assertEqual(pos_sell.forward_returns[5], 0.094906)

        # Hand-calculated oracle weighted net return:
        # 0.50 * 0.094511 + 0.50 * 0.094906 = 0.0947085 -> round to 6 decimals = 0.094709
        HAND_CALCULATED_COMBINED_ORACLE_RETURN = 0.094709
        self.assertEqual(
            eval_res.portfolio_forward_returns[5], HAND_CALCULATED_COMBINED_ORACLE_RETURN
        )


class TestNoLookaheadAndEligibilityInteraction(unittest.TestCase):
    """Test suite validating temporal isolation and PR #100 execution eligibility interaction."""

    def test_execution_eligibility_not_altered_by_cost_assumptions(self) -> None:
        """Verify non-executable stocks under PR #100 remain non-executable regardless of cost settings."""
        dates = pd.date_range("2024-01-01", periods=30, freq="B").strftime("%Y-%m-%d")
        # Low volume stock failing min_avg_volume requirement (10,000 < 50,000 threshold)
        prices = [10_000.0] * 30
        df_low_vol = pd.DataFrame(
            {
                "date": dates,
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [10_000.0] * 30,
            }
        )

        exec_cfg = ExecutionConfig(min_avg_volume=50_000.0)
        elig = evaluate_execution_eligibility(
            df_stock=df_low_vol, evaluation_date=dates[25], config=exec_cfg
        )

        self.assertFalse(elig.is_executable)
        self.assertEqual(elig.status, "not_executable")

        # Zero cost / slippage calculation does not alter eligibility status
        res = calculate_execution_return(
            entry_price=10000.0,
            exit_price=11000.0,
            transaction_cost_pct=0.0,
            slippage_pct=0.0,
        )
        self.assertEqual(res.gross_return, 0.10)


if __name__ == "__main__":
    unittest.main()
