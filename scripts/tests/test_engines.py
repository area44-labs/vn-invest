"""Unit, boundary, and regression tests for extracted quantitative engines (#174)."""

import unittest
from collections.abc import Mapping

import pandas as pd

from scripts.engine import (
    CandidateSpec,
    MarketAnalysisEngine,
    MarketAnalysisInput,
    MarketAnalysisResult,
    RiskTradePlanEngine,
    RiskTradePlanInput,
    RiskTradePlanResult,
    SignalRecommendationEngine,
    SignalRecommendationInput,
    SignalRecommendationResult,
    compute_market_breadth,
)
from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.risk import normalize_universe_liquidity_scores


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


class TestCandidateSpecContract(unittest.TestCase):
    """Test CandidateSpec input contract validation."""

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


class TestMarketAnalysisEngine(unittest.TestCase):
    """Test MarketAnalysisEngine unit behavior and contracts."""

    def setUp(self):
        self.df_vnindex = make_sample_ohlcv(days=60, start_price=1200.0, trend=2.0)
        self.df_vn30 = make_sample_ohlcv(days=60, start_price=1250.0, trend=2.0)
        self.stock_a = make_sample_ohlcv(days=30, start_price=50.0, trend=0.5)  # bullish
        self.stock_b = make_sample_ohlcv(days=30, start_price=50.0, trend=-0.5)  # bearish

    def test_compute_market_breadth_deterministic(self):
        stock_map = {"AAA": self.stock_a, "BBB": self.stock_b}
        breadth = compute_market_breadth(stock_map)
        self.assertEqual(breadth, 0.50)  # 1 bullish out of 2 valid

    def test_compute_market_breadth_custom_mapping(self):
        """Verify custom Mapping implementation is supported without falling back to 0.50."""
        custom_map = CustomMapping({"AAA": self.stock_a})
        breadth = compute_market_breadth(custom_map)
        self.assertEqual(breadth, 1.0)  # 1 bullish out of 1 valid

    def test_engine_analyze_returns_typed_result(self):
        input_data = MarketAnalysisInput(
            stock_data_map={"AAA": self.stock_a, "BBB": self.stock_b},
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
        )
        res = MarketAnalysisEngine.analyze(input_data)
        self.assertIsInstance(res, MarketAnalysisResult)
        self.assertEqual(res.breadth_ratio, 0.50)
        self.assertIn("regime", res.market_regime)
        self.assertEqual(res.to_dict()["breadth_ratio"], 0.50)

    def test_engine_boundary_isolation(self):
        """Engine accepts pure primitive types without requiring PipelineContext or Universe."""
        input_data = MarketAnalysisInput(
            stock_data_map={"AAA": self.stock_a},
            df_vnindex=self.df_vnindex,
        )
        res = MarketAnalysisEngine.analyze(input_data)
        self.assertEqual(res.breadth_ratio, 1.0)


class TestSignalRecommendationEngine(unittest.TestCase):
    """Test SignalRecommendationEngine unit behavior, contracts, and regression cases."""

    def setUp(self):
        self.df_vnindex = make_sample_ohlcv(days=60, start_price=1200.0, trend=2.0)
        self.df_stock = make_sample_ohlcv(days=60, start_price=50.0, trend=0.5)
        self.market_regime = detect_market_regime(self.df_vnindex, breadth_ratio=0.60)
        self.candidate = CandidateSpec(
            symbol="VNM",
            company_name="Vinamilk",
            sector="Consumer Goods",
            exchange="HOSE",
        )

    def test_generate_recommendations_typed_result(self):
        input_data = SignalRecommendationInput(
            candidates=[self.candidate],
            stock_data_map={"VNM": self.df_stock},
            market_regime=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
            data_source="REAL_DATA",
        )
        res = SignalRecommendationEngine.generate_recommendations(input_data)
        self.assertIsInstance(res, SignalRecommendationResult)
        self.assertEqual(len(res.recommendations), 1)
        rec = res.recommendations[0]
        self.assertEqual(rec["symbol"], "VNM")
        self.assertEqual(rec["data_as_of"], "2025-01-20")

    def test_production_sufficient_stock_provenance(self):
        """1. Production + sufficient stock -> data_source equals actual source tag."""
        input_data = SignalRecommendationInput(
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
        input_data = SignalRecommendationInput(
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
        input_data = SignalRecommendationInput(
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
        input_data = SignalRecommendationInput(
            candidates=[self.candidate],
            stock_data_map={"VNM": self.df_stock},  # raw data exists but not processed
            data_sources={"VNM": "EXPLICITLY_INVALID"},
            processed_symbols=set(),  # VNM not in processed
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
        input_data = SignalRecommendationInput(
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
        input_data = SignalRecommendationInput(
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

    def test_behavioral_parity(self):
        """7. Behavioral parity -> full payload comparison between engine and direct legacy calculation."""
        direct_rec = generate_recommendation(
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

        input_data = SignalRecommendationInput(
            candidates=[self.candidate],
            stock_data_map={"VNM": self.df_stock},
            market_regime=self.market_regime,
            df_vnindex=self.df_vnindex,
            data_as_of="2025-01-20",
            data_source="REAL_DATA",
        )
        res = SignalRecommendationEngine.generate_recommendations(input_data)
        engine_rec = res.recommendations[0]

        direct_dict = direct_rec.to_dict() if hasattr(direct_rec, "to_dict") else direct_rec
        engine_dict = engine_rec.to_dict() if hasattr(engine_rec, "to_dict") else engine_rec
        self.assertEqual(engine_dict, direct_dict)


class TestRiskTradePlanEngine(unittest.TestCase):
    """Test RiskTradePlanEngine unit behavior and contracts."""

    def setUp(self):
        self.df_vnindex = make_sample_ohlcv(days=60, start_price=1200.0, trend=2.0)
        self.df_stock_a = make_sample_ohlcv(days=60, start_price=50.0, trend=0.5)
        self.df_stock_b = make_sample_ohlcv(days=60, start_price=30.0, trend=0.2)
        self.market_regime = detect_market_regime(self.df_vnindex, breadth_ratio=0.60)

        self.rec_a = generate_recommendation(
            symbol="AAA",
            company_name="Alpha",
            sector="Tech",
            exchange="HOSE",
            df_stock=self.df_stock_a,
            market_regime_info=self.market_regime,
            df_vnindex=self.df_vnindex,
        )
        self.rec_b = generate_recommendation(
            symbol="BBB",
            company_name="Beta",
            sector="Tech",
            exchange="HOSE",
            df_stock=self.df_stock_b,
            market_regime_info=self.market_regime,
            df_vnindex=self.df_vnindex,
        )

    def test_process_risk_typed_result(self):
        input_data = RiskTradePlanInput(
            scanned_recs=[self.rec_a, self.rec_b],
            market_regime=self.market_regime,
        )
        res = RiskTradePlanEngine.process_risk(input_data)
        self.assertIsInstance(res, RiskTradePlanResult)
        self.assertEqual(len(res.recommendations), 2)
        rec = res.recommendations[0]
        rec_dict = rec.to_dict() if hasattr(rec, "to_dict") else rec
        self.assertIn("risk_metrics", rec_dict)
        self.assertIn("liquidity_score", rec_dict["risk_metrics"])

    def test_risk_parity_with_legacy_call(self):
        direct_recs = normalize_universe_liquidity_scores(
            scanned_recommendations=[self.rec_a, self.rec_b],
            market_regime=self.market_regime,
        )

        input_data = RiskTradePlanInput(
            scanned_recs=[self.rec_a, self.rec_b],
            market_regime=self.market_regime,
        )
        res = RiskTradePlanEngine.process_risk(input_data)
        self.assertEqual(res.recommendations, direct_recs)


class TestEngineEdgeCasesAndBoundarySafety(unittest.TestCase):
    """Test engine handling of empty, partial, or invalid inputs."""

    def test_market_engine_empty_input(self):
        input_data = MarketAnalysisInput(stock_data_map={})
        res = MarketAnalysisEngine.analyze(input_data)
        self.assertEqual(res.breadth_ratio, 0.50)
        self.assertEqual(res.market_regime["regime"], "DEFENSIVE")

    def test_recommendation_engine_empty_candidates(self):
        input_data = SignalRecommendationInput(
            candidates=[],
            stock_data_map={},
            market_regime={"regime": "DEFENSIVE"},
        )
        res = SignalRecommendationEngine.generate_recommendations(input_data)
        self.assertEqual(res.recommendations, [])

    def test_recommendation_engine_missing_stock_data(self):
        cand = CandidateSpec(symbol="XYZ", company_name="Xyz", sector="Sector")
        input_data = SignalRecommendationInput(
            candidates=[cand],
            stock_data_map={},
            market_regime={"regime": "DEFENSIVE"},
        )
        res = SignalRecommendationEngine.generate_recommendations(input_data)
        self.assertEqual(len(res.recommendations), 1)
        rec_dict = (
            res.recommendations[0].to_dict()
            if hasattr(res.recommendations[0], "to_dict")
            else res.recommendations[0]
        )
        self.assertEqual(rec_dict["action"], "AVOID")

    def test_risk_engine_empty_recommendations(self):
        input_data = RiskTradePlanInput(scanned_recs=[], market_regime={"regime": "DEFENSIVE"})
        res = RiskTradePlanEngine.process_risk(input_data)
        self.assertEqual(res.recommendations, [])


if __name__ == "__main__":
    unittest.main()
