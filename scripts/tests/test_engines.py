"""Unit, boundary, and regression tests for extracted quantitative engines in scripts/quant/ (#174)."""

from collections.abc import Mapping
import unittest

import pandas as pd

from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.risk import normalize_universe_liquidity_scores
from scripts.quant import (
    CandidateSpec,
    MarketAnalysisEngine,
    RecommendationInput,
    RecommendationResult,
    RiskInput,
    RiskTradePlanEngine,
    SignalInput,
    SignalRecommendationEngine,
    calculate_confidence,
    calculate_divergence_score,
    calculate_momentum_score,
    calculate_multi_timeframe_features,
    calculate_relative_strength_score,
    calculate_risk_adjusted_score,
    calculate_signal_score,
    calculate_t25_risk_metrics,
    calculate_trend_score,
    calculate_volume_score,
    classify_action,
    compute_market_breadth,
    compute_signal,
    compute_stock_risk_and_trade_plan,
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


class TestQuantFeaturesAndRegime(unittest.TestCase):
    """Test scripts/quant/features.py and scripts/quant/regime.py."""

    def setUp(self):
        self.df_vnindex = make_sample_ohlcv(days=60, start_price=1200.0, trend=2.0)
        self.df_vn30 = make_sample_ohlcv(days=60, start_price=1250.0, trend=2.0)
        self.stock_a = make_sample_ohlcv(days=30, start_price=50.0, trend=0.5)
        self.stock_b = make_sample_ohlcv(days=30, start_price=50.0, trend=-0.5)

    def test_compute_market_breadth_deterministic(self):
        stock_map = {"AAA": self.stock_a, "BBB": self.stock_b}
        breadth = compute_market_breadth(stock_map)
        self.assertEqual(breadth, 0.50)

    def test_compute_market_breadth_custom_mapping(self):
        """Verify custom Mapping implementation is supported without falling back to 0.50."""
        custom_map = CustomMapping({"AAA": self.stock_a})
        breadth = compute_market_breadth(custom_map)
        self.assertEqual(breadth, 1.0)

    def test_market_analysis_engine_analyze(self):
        input_data = type(
            "InputData",
            (),
            {
                "stock_data_map": {"AAA": self.stock_a, "BBB": self.stock_b},
                "df_vnindex": self.df_vnindex,
                "df_vn30": self.df_vn30,
                "candidate_symbols": None,
                "processed_symbols": None,
                "vn30_sufficient": True,
            },
        )()
        res = MarketAnalysisEngine.analyze(input_data)
        self.assertIn("regime", res.market_regime)
        self.assertEqual(res.market_regime["metrics"]["market_breadth_ratio"], 0.50)


class TestQuantSignalAndRisk(unittest.TestCase):
    """Test scripts/quant/signal.py and scripts/quant/risk.py decomposed calculations."""

    def setUp(self):
        self.df_vnindex = make_sample_ohlcv(days=60, start_price=1200.0, trend=2.0)
        self.df_stock = make_sample_ohlcv(days=60, start_price=50.0, trend=0.5)
        self.market_regime = detect_market_regime(self.df_vnindex, breadth_ratio=0.60)

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
        self.assertEqual(sig_res.symbol, "VNM")
        self.assertEqual(sig_res.data_quality, "SUFFICIENT")
        self.assertIsNotNone(sig_res.score)

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
        self.assertIsNotNone(risk_res.risk_adjusted_score)
        self.assertIsNotNone(risk_res.trade_plan["stop_loss"])


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
        self.assertEqual(rec["symbol"], "VNM")
        self.assertEqual(rec["data_as_of"], "2025-01-20")

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

        engine_rec = generate_single_recommendation(
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

        direct_dict = direct_rec.to_dict() if hasattr(direct_rec, "to_dict") else direct_rec
        engine_dict = engine_rec.to_dict() if hasattr(engine_rec, "to_dict") else engine_rec
        self.assertEqual(engine_dict, direct_dict)


if __name__ == "__main__":
    unittest.main()
