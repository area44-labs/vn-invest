"""Unit tests for VN Invest Domain Contracts."""

import unittest
from dataclasses import FrozenInstanceError

from scripts.domain import (
    DataQuality,
    OHLCVData,
    PipelineResult,
    Recommendation,
    RiskAssessment,
    TradePlan,
    Universe,
    UniverseCandidate,
)


class TestOHLCVDataDomainContract(unittest.TestCase):
    """Test suite for OHLCVData immutable domain model."""

    def test_valid_ohlcv_construction_and_serialization(self):
        candle = OHLCVData(
            date="2026-03-31",
            open=50.0,
            high=52.5,
            low=49.5,
            close=51.0,
            volume=1000000.0,
        )
        self.assertEqual(candle.date, "2026-03-31")
        self.assertEqual(candle.open, 50.0)
        self.assertEqual(candle.high, 52.5)
        self.assertEqual(candle.low, 49.5)
        self.assertEqual(candle.close, 51.0)
        self.assertEqual(candle.volume, 1000000.0)

        data_dict = candle.to_dict()
        self.assertEqual(data_dict["date"], "2026-03-31")
        self.assertEqual(data_dict["close"], 51.0)

        reconstructed = OHLCVData.from_dict(data_dict)
        self.assertEqual(reconstructed, candle)

    def test_immutability(self):
        candle = OHLCVData(
            date="2026-03-31",
            open=50.0,
            high=52.5,
            low=49.5,
            close=51.0,
            volume=1000000.0,
        )
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            candle.close = 55.0  # type: ignore

    def test_non_positive_price_rejection(self):
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=0.0, high=52.5, low=49.5, close=51.0, volume=1000.0)
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=-5.0, low=49.5, close=51.0, volume=1000.0)

    def test_negative_volume_rejection(self):
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=52.5, low=49.5, close=51.0, volume=-100.0)

    def test_invalid_ohlc_relationship_rejection(self):
        # High < Low
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=48.0, low=49.5, close=50.0, volume=1000.0)

        # High < Open
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=55.0, high=52.5, low=49.5, close=50.0, volume=1000.0)

        # Low > Close
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=52.5, low=51.0, close=49.5, volume=1000.0)

    def test_empty_date_rejection(self):
        with self.assertRaises(ValueError):
            OHLCVData("", open=50.0, high=52.5, low=49.5, close=51.0, volume=1000.0)

    def test_nan_and_inf_rejection(self):
        with self.assertRaises(ValueError):
            OHLCVData(
                "2026-03-31", open=float("nan"), high=52.5, low=49.5, close=51.0, volume=1000.0
            )
        with self.assertRaises(ValueError):
            OHLCVData(
                "2026-03-31", open=50.0, high=float("inf"), low=49.5, close=51.0, volume=1000.0
            )


class TestDataQualityDomainContract(unittest.TestCase):
    """Test suite for DataQuality domain model."""

    def test_valid_data_quality(self):
        dq = DataQuality(
            status="SUFFICIENT",
            issues=(),
            valid_row_count=100,
            latest_date="2026-03-31",
            data_as_of="2026-03-31",
            data_source="TEST",
        )
        self.assertEqual(dq.status, "SUFFICIENT")
        self.assertEqual(dq.valid_row_count, 100)

        d = dq.to_dict()
        self.assertEqual(d["status"], "SUFFICIENT")
        self.assertEqual(DataQuality.from_dict(d), dq)

    def test_invalid_status_rejection(self):
        with self.assertRaises(ValueError):
            DataQuality(status="UNKNOWN")

    def test_negative_valid_row_count_rejection(self):
        with self.assertRaises(ValueError):
            DataQuality(status="SUFFICIENT", valid_row_count=-5)

    def test_immutability(self):
        dq = DataQuality(status="SUFFICIENT")
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            dq.status = "PARTIAL"  # type: ignore


class TestUniverseDomainContract(unittest.TestCase):
    """Test suite for UniverseCandidate and Universe domain models."""

    def test_candidate_and_universe_construction(self):
        c1 = UniverseCandidate(
            symbol="VNM", company_name="Vinamilk", sector="Consumer", exchange="HOSE"
        )
        c2 = UniverseCandidate(
            symbol="FPT", company_name="FPT Corp", sector="Technology", exchange="HOSE"
        )

        u = Universe(universe_type="VN30", candidates=(c1, c2))
        self.assertEqual(u.universe_size, 2)
        self.assertEqual(len(u.candidates), 2)

        u_dict = u.to_dict()
        self.assertEqual(u_dict["universe_type"], "VN30")
        self.assertEqual(u_dict["universe_size"], 2)

        reconstructed = Universe.from_dict(
            {"universe_type": "VN30", "candidates": [c1.to_dict(), c2.to_dict()]}
        )
        self.assertEqual(reconstructed.universe_size, 2)
        self.assertEqual(reconstructed.candidates[0].symbol, "VNM")

    def test_invalid_candidate_exchange_rejection(self):
        with self.assertRaises(ValueError):
            UniverseCandidate(
                symbol="VNM", company_name="Vinamilk", sector="Consumer", exchange="NASDAQ"
            )

    def test_empty_candidate_symbol_rejection(self):
        with self.assertRaises(ValueError):
            UniverseCandidate(symbol="", company_name="Vinamilk", sector="Consumer")


class TestTradePlanDomainContract(unittest.TestCase):
    """Test suite for TradePlan domain model."""

    def test_valid_trade_plan(self):
        tp = TradePlan(
            current_price=50000.0,
            entry_low=49500.0,
            entry_high=50500.0,
            stop_loss=47500.0,
            tp1=55000.0,
            tp2=58000.0,
            risk_reward=2.0,
            position_percent=15.0,
        )
        self.assertEqual(tp.current_price, 50000.0)
        self.assertEqual(tp.position_percent, 15.0)

        tp_dict = tp.to_dict()
        self.assertEqual(tp_dict["stop_loss"], 47500.0)
        self.assertEqual(TradePlan.from_dict(tp_dict), tp)

    def test_invalid_position_percent_rejection(self):
        with self.assertRaises(ValueError):
            TradePlan(position_percent=-5.0)
        with self.assertRaises(ValueError):
            TradePlan(position_percent=105.0)

    def test_negative_price_rejection(self):
        with self.assertRaises(ValueError):
            TradePlan(current_price=-1000.0)


class TestRiskAssessmentDomainContract(unittest.TestCase):
    """Test suite for RiskAssessment domain model."""

    def test_valid_risk_assessment(self):
        ra = RiskAssessment(
            var_t25=-0.045,
            es_t25=-0.062,
            volatility_60d=0.25,
            max_drawdown=-0.12,
            liquidity_score=85.0,
            avg_value_20d=150.5,
            risk_level="MEDIUM",
        )
        self.assertEqual(ra.liquidity_score, 85.0)
        self.assertEqual(ra.risk_level, "MEDIUM")

        metrics_dict = ra.to_metrics_dict()
        self.assertNotIn("risk_level", metrics_dict)
        self.assertEqual(metrics_dict["liquidity_score"], 85.0)

        full_dict = ra.to_dict()
        self.assertEqual(full_dict["risk_level"], "MEDIUM")
        self.assertEqual(RiskAssessment.from_dict(full_dict), ra)

    def test_invalid_liquidity_score_rejection(self):
        with self.assertRaises(ValueError):
            RiskAssessment(liquidity_score=105.0)
        with self.assertRaises(ValueError):
            RiskAssessment(liquidity_score=-1.0)

    def test_invalid_risk_level_rejection(self):
        with self.assertRaises(ValueError):
            RiskAssessment(risk_level="EXTREME")


class TestRecommendationDomainContract(unittest.TestCase):
    """Test suite for Recommendation domain model."""

    def setUp(self):
        self.valid_rec = Recommendation(
            symbol="VNM",
            company_name="Vinamilk",
            exchange="HOSE",
            sector="Consumer Goods",
            action="BUY",
            model_version="2.0",
            data_quality="SUFFICIENT",
            data_as_of="2026-03-31",
            data_source="REAL_DATA",
            signal_score=78.5,
            risk_adjusted_score=75.0,
            score_components={
                "trend": 80.0,
                "momentum": 75.0,
                "volume": 70.0,
                "relative_strength": 85.0,
                "divergence": 80.0,
            },
            confidence=0.82,
            risk_level="MEDIUM",
            expected_return={
                "expected_return_5d": None,
                "expected_return_10d": None,
                "expected_return_20d": None,
            },
            risk_metrics=RiskAssessment(
                var_t25=-0.04,
                es_t25=-0.05,
                volatility_60d=0.22,
                max_drawdown=-0.10,
                liquidity_score=90.0,
                avg_value_20d=200.0,
                risk_level="MEDIUM",
            ),
            trade_plan=TradePlan(
                current_price=68000.0,
                entry_low=67500.0,
                entry_high=68500.0,
                stop_loss=64000.0,
                tp1=74000.0,
                tp2=78000.0,
                risk_reward=2.5,
                position_percent=15.0,
            ),
            reasons=("Gia tren MA20",),
            warnings=(),
            invalidation=("Gia vi pham cat lo 64.000 VNĐ",),
            divergence={"1H": "NONE", "1D": "BULLISH", "1W": "NONE", "1M": "NONE"},
        )

    def test_valid_recommendation_serialization(self):
        rec_dict = self.valid_rec.to_dict()
        self.assertEqual(rec_dict["symbol"], "VNM")
        self.assertEqual(rec_dict["action"], "BUY")
        self.assertEqual(rec_dict["confidence"], 0.82)
        self.assertEqual(rec_dict["risk_metrics"]["liquidity_score"], 90.0)
        self.assertEqual(rec_dict["trade_plan"]["current_price"], 68000.0)

        reconstructed = Recommendation.from_dict(rec_dict)
        self.assertEqual(reconstructed.symbol, "VNM")
        self.assertEqual(reconstructed.signal_score, 78.5)

    def test_dict_subscripting_compatibility(self):
        rec = self.valid_rec
        self.assertEqual(rec["symbol"], "VNM")
        self.assertEqual(rec["action"], "BUY")
        self.assertEqual(rec.get("confidence"), 0.82)
        self.assertIn("trade_plan", rec)
        self.assertIn("risk_metrics", rec)
        self.assertEqual(rec["trade_plan"]["current_price"], 68000.0)

    def test_immutable_with_liquidity_score_update(self):
        rec = self.valid_rec
        updated = rec.with_liquidity_score(liquidity_score=95.0, risk_adjusted_score=77.0)

        # Verify updated instance has new scores
        self.assertEqual(updated.risk_metrics.liquidity_score, 95.0)
        self.assertEqual(updated.risk_adjusted_score, 77.0)

        # Verify original instance was unchanged
        self.assertEqual(rec.risk_metrics.liquidity_score, 90.0)
        self.assertEqual(rec.risk_adjusted_score, 75.0)

    def test_invalid_action_rejection(self):
        with self.assertRaises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "action": "SUPER_BUY"})

    def test_invalid_exchange_rejection(self):
        with self.assertRaises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "exchange": "NYSE"})

    def test_out_of_range_score_rejection(self):
        with self.assertRaises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "signal_score": 150.0})

    def test_out_of_range_confidence_rejection(self):
        with self.assertRaises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "confidence": 1.5})


class TestPipelineResultDomainContract(unittest.TestCase):
    """Test suite for PipelineResult domain model."""

    def test_pipeline_result_unpacking_and_attributes(self):
        recs_data = {"schema_version": "2.0", "recommendations": []}
        market_data = {"market": {"regime": "BULL"}}
        history_data = recs_data
        universe_audit = {"status": "SUCCESS"}

        pr = PipelineResult(
            recs_data=recs_data,
            market_data=market_data,
            history_data=history_data,
            universe_audit=universe_audit,
        )

        # 3-element tuple unpacking compatibility
        r, m, h = pr
        self.assertEqual(r, recs_data)
        self.assertEqual(m, market_data)
        self.assertEqual(h, history_data)

        # Attribute access
        self.assertEqual(pr.recommendations_payload, recs_data)
        self.assertEqual(pr.universe_audit, universe_audit)

        # Serialization
        pr_dict = pr.to_dict()
        self.assertEqual(pr_dict["market"]["market"]["regime"], "BULL")


if __name__ == "__main__":
    unittest.main()
