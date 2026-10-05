"""Unit, boundary, contract, and regression tests for quantitative engines in scripts/quant/ (#174)."""

import unittest
from collections.abc import Mapping

import pandas as pd

from scripts.quant import (
    CandidateSpec,
    FeatureInput,
    FeatureResult,
    MarketAnalysisEngine,
    MarketAnalysisInput,
    RecommendationInput,
    RecommendationResult,
    RegimeInput,
    RegimeResult,
    RiskInput,
    RiskResult,
    RiskTradePlanEngine,
    RiskTradePlanInput,
    SignalInput,
    SignalRecommendationEngine,
    SignalResult,
    compute_market_breadth,
    compute_signal,
    compute_stock_risk_and_trade_plan,
    detect_market_regime,
    generate_single_recommendation,
)


def make_sample_ohlcv(
    days: int = 60, start_price: float = 50.0, trend: float = 0.5
) -> pd.DataFrame:
    """Generate deterministic synthetic OHLCV DataFrame."""
    dates = pd.date_range("2025-01-01", periods=days, freq="B").strftime("%Y-%m-%d").tolist()
    closes = [start_price + i * trend for i in range(days)]
    opens = [c - 0.2 for c in closes]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    volumes = [1_000_000 + i * 10_000 for i in range(days)]

    return pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


class CustomMapping(Mapping):
    """Custom Mapping implementation for testing compute_market_breadth Mapping contract."""

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)


class TestQuantContracts(unittest.TestCase):
    """Test CandidateSpec and quantitative contract validation."""

    def test_candidate_spec_normalization_and_validation(self):
        cand = CandidateSpec(
            symbol="  vnm ",
            company_name="Vinamilk",
            sector="Consumer Goods",
            exchange="hose",
        )
        self.assertEqual(cand.symbol, "VNM")
        self.assertEqual(cand.company_name, "Vinamilk")
        self.assertEqual(cand.sector, "Consumer Goods")
        self.assertEqual(cand.exchange, "HOSE")

    def test_candidate_spec_invalid_inputs(self):
        with self.assertRaises(ValueError):
            CandidateSpec(symbol="", company_name="Name", sector="Sector")
        with self.assertRaises(ValueError):
            CandidateSpec(symbol="ABC", company_name="", sector="Sector")


class TestQuantMarketAnalysisAndRegimeEngine(unittest.TestCase):
    """Test scripts/quant/features.py, scripts/quant/regime.py, and MarketAnalysisEngine."""

    def setUp(self):
        self.df_vnindex = make_sample_ohlcv(days=60, start_price=1200.0, trend=2.0)
        self.df_vn30 = make_sample_ohlcv(days=60, start_price=1250.0, trend=2.0)
        self.stock_a = make_sample_ohlcv(days=30, start_price=50.0, trend=0.5)
        self.stock_b = make_sample_ohlcv(days=30, start_price=50.0, trend=-0.5)

    def test_compute_market_breadth_feature_input_contract(self):
        feature_in = FeatureInput(
            stock_data_map={"AAA": self.stock_a, "BBB": self.stock_b},
        )
        res = compute_market_breadth(feature_in)
        self.assertIsInstance(res, FeatureResult)
        self.assertEqual(res.breadth_ratio, 0.50)

    def test_compute_market_breadth_custom_mapping(self):
        """Verify custom Mapping implementation is supported without falling back to 0.50."""
        custom_map = CustomMapping({"AAA": self.stock_a})
        res = compute_market_breadth(custom_map)
        self.assertIsInstance(res, FeatureResult)
        self.assertEqual(res.breadth_ratio, 1.0)

    def test_detect_market_regime_input_contract(self):
        regime_in = RegimeInput(
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            breadth_ratio=0.60,
        )
        res = detect_market_regime(regime_in)
        self.assertIsInstance(res, RegimeResult)
        self.assertIn("regime", res.market_regime)

    def test_market_analysis_engine_analyze(self):
        input_data = MarketAnalysisInput(
            stock_data_map={"AAA": self.stock_a, "BBB": self.stock_b},
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_symbols=None,
            processed_symbols=None,
            vn30_sufficient=True,
        )
        res = MarketAnalysisEngine.analyze(input_data)
        self.assertIsInstance(res, RegimeResult)
        self.assertIn("regime", res.market_regime)
        self.assertEqual(res.market_regime["metrics"]["market_breadth_ratio"], 0.50)


class TestQuantSignalEngine(unittest.TestCase):
    """Test scripts/quant/signal.py decomposed calculations."""

    def setUp(self):
        self.df_vnindex = make_sample_ohlcv(days=60, start_price=1200.0, trend=2.0)
        self.df_stock = make_sample_ohlcv(days=60, start_price=50.0, trend=0.5)
        regime_res = detect_market_regime(
            RegimeInput(df_vnindex=self.df_vnindex, breadth_ratio=0.60)
        )
        self.market_regime = regime_res.market_regime

    def test_compute_signal(self):
        sig_input = SignalInput(
            symbol="VNM",
            company_name="Vinamilk",
            sector="Consumer Goods",
            exchange="HOSE",
            df_stock=self.df_stock,
            market_regime=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
            data_source="REAL_DATA",
        )
        sig_res = compute_signal(sig_input)
        self.assertIsInstance(sig_res, SignalResult)
        self.assertEqual(sig_res.symbol, "VNM")
        self.assertEqual(sig_res.data_quality, "SUFFICIENT")
        self.assertIsNotNone(sig_res.score)


class TestQuantRiskEngine(unittest.TestCase):
    """Test scripts/quant/risk.py risk assessment and trade plan calculations."""

    def setUp(self):
        self.df_vnindex = make_sample_ohlcv(days=60, start_price=1200.0, trend=2.0)
        self.df_stock = make_sample_ohlcv(days=60, start_price=50.0, trend=0.5)
        regime_res = detect_market_regime(
            RegimeInput(df_vnindex=self.df_vnindex, breadth_ratio=0.60)
        )
        self.market_regime = regime_res.market_regime

    def test_compute_stock_risk_and_trade_plan(self):
        sig_input = SignalInput(
            symbol="VNM",
            company_name="Vinamilk",
            sector="Consumer Goods",
            exchange="HOSE",
            df_stock=self.df_stock,
            market_regime=self.market_regime,
            df_vnindex=self.df_vnindex,
        )
        sig_res = compute_signal(sig_input)

        risk_input = RiskInput(
            symbol="VNM",
            company_name="Vinamilk",
            exchange="HOSE",
            sector="Consumer Goods",
            df_d=sig_res.df_d,
            val_res=sig_res.val_res,
            market_regime=self.market_regime,
            signal_result=sig_res,
            action="BUY",
        )
        risk_res = compute_stock_risk_and_trade_plan(risk_input)
        self.assertIsInstance(risk_res, RiskResult)
        self.assertIsNotNone(risk_res.risk_adjusted_score)
        self.assertIsNotNone(risk_res.trade_plan["stop_loss"])

    def test_risk_trade_plan_engine_process_risk(self):
        rec = generate_single_recommendation(
            symbol="VNM",
            company_name="Vinamilk",
            sector="Consumer Goods",
            exchange="HOSE",
            df_stock=self.df_stock,
            market_regime_info=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
            data_source="REAL_DATA",
        )
        risk_tp_in = RiskTradePlanInput(
            scanned_recs=[rec],
            market_regime=self.market_regime,
        )
        recs_out = RiskTradePlanEngine.process_risk(risk_tp_in)
        self.assertEqual(len(recs_out), 1)


class TestQuantRecommendationEngine(unittest.TestCase):
    """Test SignalRecommendationEngine unit behavior, contracts, provenance, and parity."""

    def setUp(self):
        self.df_vnindex = make_sample_ohlcv(days=60, start_price=1200.0, trend=2.0)
        self.df_stock = make_sample_ohlcv(days=60, start_price=50.0, trend=0.5)
        regime_res = detect_market_regime(
            RegimeInput(df_vnindex=self.df_vnindex, breadth_ratio=0.60)
        )
        self.market_regime = regime_res.market_regime
        self.candidate = CandidateSpec(
            symbol="VNM",
            company_name="Vinamilk",
            sector="Consumer Goods",
            exchange="HOSE",
        )

    def test_generate_recommendations_typed_result(self):
        input_data = RecommendationInput(
            candidates=[self.candidate],
            stock_data_map={"VNM": self.df_stock},
            market_regime=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
            data_source="REAL_DATA",
        )
        res = SignalRecommendationEngine.generate_recommendations(input_data)
        self.assertIsInstance(res, RecommendationResult)
        self.assertEqual(len(res.recommendations), 1)
        rec = res.recommendations[0]
        self.assertEqual(rec.symbol if hasattr(rec, "symbol") else rec["symbol"], "VNM")

    def test_production_sufficient_stock_provenance(self):
        """1. Production + sufficient stock -> data_source equals actual source tag."""
        input_data = RecommendationInput(
            candidates=[self.candidate],
            stock_data_map={"VNM": self.df_stock},
            data_sources={"VNM": "REAL_DATA"},
            processed_symbols={"VNM"},
            market_regime=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
        )
        res = SignalRecommendationEngine.generate_recommendations(input_data)
        rec_dict = (
            res.recommendations[0].to_dict()
            if hasattr(res.recommendations[0], "to_dict")
            else res.recommendations[0]
        )
        self.assertEqual(rec_dict["data_source"], "REAL_DATA")

    def test_production_provider_failure_provenance(self):
        """2. Production + provider failure -> data_source is None."""
        input_data = RecommendationInput(
            candidates=[self.candidate],
            stock_data_map={"VNM": pd.DataFrame()},
            data_sources={"VNM": "PROVIDER_FAILURE"},
            processed_symbols=set(),
            market_regime=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
        )
        res = SignalRecommendationEngine.generate_recommendations(input_data)
        rec_dict = (
            res.recommendations[0].to_dict()
            if hasattr(res.recommendations[0], "to_dict")
            else res.recommendations[0]
        )
        self.assertIsNone(rec_dict["data_source"])

    def test_production_insufficient_data_provenance(self):
        """3. Production + insufficient data -> data_source is None."""
        input_data = RecommendationInput(
            candidates=[self.candidate],
            stock_data_map={"VNM": pd.DataFrame()},
            data_sources={"VNM": "INSUFFICIENT_HISTORICAL_DATA"},
            processed_symbols=set(),
            market_regime=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
        )
        res = SignalRecommendationEngine.generate_recommendations(input_data)
        rec_dict = (
            res.recommendations[0].to_dict()
            if hasattr(res.recommendations[0], "to_dict")
            else res.recommendations[0]
        )
        self.assertIsNone(rec_dict["data_source"])

    def test_production_symbol_not_processed_provenance(self):
        """4. Production + symbol not processed -> recommendation created with data_source is None."""
        input_data = RecommendationInput(
            candidates=[self.candidate],
            stock_data_map={"VNM": self.df_stock},
            data_sources={"VNM": "EXPLICITLY_INVALID"},
            processed_symbols=set(),
            market_regime=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
        )
        res = SignalRecommendationEngine.generate_recommendations(input_data)
        rec_dict = (
            res.recommendations[0].to_dict()
            if hasattr(res.recommendations[0], "to_dict")
            else res.recommendations[0]
        )
        self.assertIsNone(rec_dict["data_source"])
        self.assertEqual(rec_dict["action"], "AVOID")

    def test_historical_valid_dataset_provenance(self):
        """5. Historical + valid dataset -> retains correct historical date/source semantics."""
        input_data = RecommendationInput(
            candidates=[self.candidate],
            stock_data_map={"VNM": self.df_stock},
            data_source="explicit_historical_input",
            market_regime=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
        )
        res = SignalRecommendationEngine.generate_recommendations(input_data)
        rec_dict = (
            res.recommendations[0].to_dict()
            if hasattr(res.recommendations[0], "to_dict")
            else res.recommendations[0]
        )
        self.assertEqual(rec_dict["data_source"], "explicit_historical_input")
        self.assertEqual(rec_dict["data_as_of"], "2025-01-20")

    def test_historical_empty_dataset_provenance(self):
        """6. Historical + empty dataset -> data_source is None."""
        input_data = RecommendationInput(
            candidates=[self.candidate],
            stock_data_map={"VNM": pd.DataFrame()},
            data_source="explicit_historical_input",
            market_regime=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
        )
        res = SignalRecommendationEngine.generate_recommendations(input_data)
        rec_dict = (
            res.recommendations[0].to_dict()
            if hasattr(res.recommendations[0], "to_dict")
            else res.recommendations[0]
        )
        self.assertIsNone(rec_dict["data_source"])

    def test_engine_and_single_recommendation_parity(self):
        """7. Engine parity -> full payload comparison between SignalRecommendationEngine and generate_single_recommendation."""
        engine_res = SignalRecommendationEngine.generate_recommendations(
            RecommendationInput(
                candidates=[self.candidate],
                stock_data_map={"VNM": self.df_stock},
                market_regime=self.market_regime,
                df_vnindex=self.df_vnindex,
                data_as_of="2025-01-20",
                data_source="REAL_DATA",
                processed_symbols={"VNM"},
                data_sources={"VNM": "REAL_DATA"},
            )
        )

        single_rec = generate_single_recommendation(
            symbol="VNM",
            company_name="Vinamilk",
            sector="Consumer Goods",
            exchange="HOSE",
            df_stock=self.df_stock,
            market_regime_info=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
            data_source="REAL_DATA",
        )

        engine_dict = (
            engine_res.recommendations[0].to_dict()
            if hasattr(engine_res.recommendations[0], "to_dict")
            else engine_res.recommendations[0]
        )
        single_dict = single_rec.to_dict() if hasattr(single_rec, "to_dict") else single_rec
        self.assertEqual(engine_dict, single_dict)

    def test_legacy_wrapper_backward_compatibility(self):
        """8. Backward compatibility -> legacy scripts.lib wrapper delegates to scripts.quant with exact payload equivalence."""
        from scripts.lib.recommendation import generate_recommendation as legacy_generate_rec

        legacy_rec = legacy_generate_rec(
            symbol="VNM",
            company_name="Vinamilk",
            sector="Consumer Goods",
            exchange="HOSE",
            df_stock=self.df_stock,
            market_regime_info=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
            data_source="REAL_DATA",
        )

        quant_rec = generate_single_recommendation(
            symbol="VNM",
            company_name="Vinamilk",
            sector="Consumer Goods",
            exchange="HOSE",
            df_stock=self.df_stock,
            market_regime_info=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
            data_source="REAL_DATA",
        )

        legacy_dict = legacy_rec.to_dict() if hasattr(legacy_rec, "to_dict") else legacy_rec
        quant_dict = quant_rec.to_dict() if hasattr(quant_rec, "to_dict") else quant_rec
        self.assertEqual(legacy_dict, quant_dict)


class TestQuantUnificationAndBacktestParity(unittest.TestCase):
    """Test Issue #175: Proof of unification between production and backtest quantitative engines."""

    def setUp(self):
        self.df_vnindex = make_sample_ohlcv(days=80, start_price=1200.0, trend=2.0)
        self.df_vn30 = make_sample_ohlcv(days=80, start_price=1250.0, trend=2.0)
        self.df_stock = make_sample_ohlcv(days=80, start_price=50.0, trend=0.5)
        self.as_of_date = self.df_stock["date"].iloc[50]

    def test_backtest_uses_quant_engine_directly(self):
        """Verify backtest modules use detect_market_regime and generate_recommendation from scripts.quant."""
        import scripts.lib.backtest as bt
        import scripts.lib.portfolio_backtest as pbt
        from scripts.quant.regime import lib_detect_market_regime

        self.assertIs(bt.detect_market_regime, lib_detect_market_regime)
        self.assertIs(bt.generate_recommendation, generate_single_recommendation)
        self.assertIs(pbt.detect_market_regime, lib_detect_market_regime)
        self.assertIs(pbt.generate_recommendation, generate_single_recommendation)

    def test_production_and_backtest_quant_equivalence_and_determinism(self):
        """Verify production engine output matches backtest signal generation at identical point in time."""
        from scripts.lib.backtest import get_as_of_dataset, run_backtest_for_symbol

        # 1. Backtest call at as_of_date
        results = run_backtest_for_symbol(
            symbol="VNM",
            df_stock=self.df_stock,
            evaluation_dates=[self.as_of_date],
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )
        self.assertEqual(len(results), 1)
        backtest_sig = results[0].signal

        # 2. Production engine call with point-in-time sliced data <= as_of_date
        df_stock_pit = get_as_of_dataset(self.df_stock, self.as_of_date)
        df_vnindex_pit = get_as_of_dataset(self.df_vnindex, self.as_of_date)
        df_vn30_pit = get_as_of_dataset(self.df_vn30, self.as_of_date)

        regime_res = detect_market_regime(
            RegimeInput(
                df_vnindex=df_vnindex_pit,
                df_vn30=df_vn30_pit,
                breadth_ratio=1.0,  # Single stock in universe produces 1.0
            )
        )
        prod_rec = generate_single_recommendation(
            symbol="VNM",
            company_name="Company VNM",
            sector="General",
            exchange="HOSE",
            df_stock=df_stock_pit,
            market_regime_info=regime_res.market_regime,
            df_vnindex=df_vnindex_pit,
            data_as_of=self.as_of_date,
        )

        # 3. Assert full quantitative equivalence
        self.assertEqual(backtest_sig.action, prod_rec.action)
        self.assertEqual(backtest_sig.signal_score, prod_rec.signal_score)
        self.assertEqual(backtest_sig.confidence, prod_rec.confidence)
        self.assertEqual(backtest_sig.market_regime, regime_res.market_regime["regime"])
        self.assertEqual(backtest_sig.risk_adjusted_score, prod_rec.risk_adjusted_score)
        self.assertEqual(backtest_sig.score_components, prod_rec.score_components)

    def test_pit_dataset_no_lookahead_isolation(self):
        """Verify future mutations (> as_of_date) do not alter quantitative signal outputs at as_of_date."""
        from scripts.lib.backtest import run_backtest_for_symbol

        # Run 1: original data
        res1 = run_backtest_for_symbol(
            symbol="VNM",
            df_stock=self.df_stock,
            evaluation_dates=[self.as_of_date],
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )

        # Run 2: mutate future stock and index prices (> as_of_date)
        df_stock_mutated = self.df_stock.copy()
        df_vnindex_mutated = self.df_vnindex.copy()
        df_vn30_mutated = self.df_vn30.copy()

        future_mask_stock = df_stock_mutated["date"] > self.as_of_date
        for col in ["open", "high", "low", "close"]:
            df_stock_mutated.loc[future_mask_stock, col] *= 5.0

        future_mask_vn = df_vnindex_mutated["date"] > self.as_of_date
        for col in ["open", "high", "low", "close"]:
            df_vnindex_mutated.loc[future_mask_vn, col] *= 0.1

        res2 = run_backtest_for_symbol(
            symbol="VNM",
            df_stock=df_stock_mutated,
            evaluation_dates=[self.as_of_date],
            df_vnindex=df_vnindex_mutated,
            df_vn30=df_vn30_mutated,
        )

        # Quantitative signal generated at T MUST be identical
        self.assertEqual(res1[0].signal.to_dict(), res2[0].signal.to_dict())
        # Forward outcomes AFTER T MUST reflect modified future prices
        self.assertNotEqual(res1[0].outcome.to_dict(), res2[0].outcome.to_dict())


if __name__ == "__main__":
    unittest.main()
