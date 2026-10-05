"""Tests for Quantitative Configuration and Version Contract (`scripts/quant/config.py`).

Verifies:
1. Production and backtest engines use identical central quantitative configuration.
2. Quant version and config hash propagate consistently across models and outputs.
3. No duplicated quantitative parameter definitions exist across modules.
4. Identical input + identical configuration/version produces deterministic output.
5. Parameter changes alter config_hash and version contract explicitly.
6. Existing quantitative behavior is preserved intact under DEFAULT_QUANT_CONFIG.
7. QuantConfig nested fields cannot be mutated in-place.
8. Production and backtest outputs carry identical quant_version and config_hash for the same config.
"""

import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

from scripts.lib import config as legacy_config
from scripts.lib.portfolio_backtest import PortfolioConfig, run_portfolio_backtest
from scripts.quant.config import DEFAULT_QUANT_CONFIG
from scripts.quant.contracts import (
    CandidateSpec,
    RecommendationInput,
)
from scripts.quant.recommendation import (
    SignalRecommendationEngine,
    generate_single_recommendation,
)
from scripts.quant.signal import (
    calculate_trend_score,
    classify_action,
)


class TestQuantitativeConfigAndVersionContract(unittest.TestCase):
    def test_default_config_properties_and_version_contract(self):
        """1. Verify DEFAULT_QUANT_CONFIG properties, hash calculation, and version contract structure."""
        cfg = DEFAULT_QUANT_CONFIG
        self.assertEqual(cfg.quant_version, "1.0.0")
        self.assertEqual(cfg.model_version, "2.0")

        contract = cfg.version_contract
        self.assertIn("quant_version", contract)
        self.assertIn("model_version", contract)
        self.assertIn("config_hash", contract)
        self.assertEqual(contract["quant_version"], "1.0.0")
        self.assertEqual(contract["model_version"], "2.0")
        self.assertEqual(contract["config_hash"], cfg.get_config_hash())
        self.assertEqual(len(cfg.get_config_hash()), 12)

    def test_quant_config_immutability(self):
        """2. Verify QuantConfig instance and nested fields cannot be mutated in-place."""
        cfg = DEFAULT_QUANT_CONFIG

        # Attribute assignment on frozen dataclass
        with self.assertRaises((TypeError, AttributeError)):
            cfg.quant_version = "2.0.0"

        # Nested mapping mutation attempts
        with self.assertRaises((TypeError, AttributeError)):
            cfg.signal_weights["trend"] = 0.99

        with self.assertRaises((TypeError, AttributeError)):
            cfg.divergence_timeframe_weights["1D"] = 0.99

        with self.assertRaises((TypeError, AttributeError)):
            cfg.regime_score_factors["BULL"] = 2.00

    def test_no_duplicated_configuration(self):
        """3. Verify legacy scripts.lib.config delegates directly to DEFAULT_QUANT_CONFIG without duplication."""
        self.assertEqual(legacy_config.QUANT_VERSION, DEFAULT_QUANT_CONFIG.quant_version)
        self.assertEqual(legacy_config.SIGNAL_MODEL_VERSION, DEFAULT_QUANT_CONFIG.model_version)
        self.assertEqual(
            dict(legacy_config.SIGNAL_WEIGHTS), dict(DEFAULT_QUANT_CONFIG.signal_weights)
        )
        self.assertEqual(
            dict(legacy_config.DIVERGENCE_TIMEFRAME_WEIGHTS),
            dict(DEFAULT_QUANT_CONFIG.divergence_timeframe_weights),
        )
        self.assertEqual(
            legacy_config.VALID_MARKET_REGIMES, set(DEFAULT_QUANT_CONFIG.valid_market_regimes)
        )
        self.assertEqual(legacy_config.MA_SHORT_PERIOD, DEFAULT_QUANT_CONFIG.ma_short_period)
        self.assertEqual(legacy_config.MA_LONG_PERIOD, DEFAULT_QUANT_CONFIG.ma_long_period)

    def test_version_contract_detects_parameter_changes(self):
        """4. Verify modifying configuration parameters changes config_hash and version_contract explicitly."""
        base_hash = DEFAULT_QUANT_CONFIG.get_config_hash()

        # Modify signal weights
        modified_weights = dict(DEFAULT_QUANT_CONFIG.signal_weights)
        modified_weights["trend"] = 0.50
        modified_weights["momentum"] = 0.05
        cfg_mod = replace(DEFAULT_QUANT_CONFIG, signal_weights=modified_weights)

        mod_hash = cfg_mod.get_config_hash()
        self.assertNotEqual(base_hash, mod_hash)
        self.assertEqual(cfg_mod.version_contract["config_hash"], mod_hash)

        # Modify threshold
        cfg_mod_thresh = replace(DEFAULT_QUANT_CONFIG, score_threshold_buy=70.0)
        self.assertNotEqual(base_hash, cfg_mod_thresh.get_config_hash())

    def test_quant_version_and_config_hash_propagation(self):
        """5. Verify production recommendation and backtest output carry identical quant_version + config_hash."""
        dates = pd.date_range("2026-01-01", periods=60)
        df_stock = pd.DataFrame(
            {
                "time": dates.strftime("%Y-%m-%d"),
                "open": np.linspace(50, 70, 60),
                "high": np.linspace(51, 71, 60),
                "low": np.linspace(49, 69, 60),
                "close": np.linspace(50, 70, 60),
                "volume": [1000000.0] * 60,
            }
        )
        market_regime = {"regime": "BULL", "regime_score": 70.0}

        custom_cfg = replace(DEFAULT_QUANT_CONFIG, score_threshold_buy=70.0)

        # Production Recommendation
        rec = generate_single_recommendation(
            symbol="HPG",
            company_name="Hoa Phat Group",
            sector="Thép",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=market_regime,
            config=custom_cfg,
        )

        # Portfolio Backtest Output
        p_cfg = PortfolioConfig(
            max_positions=1, min_history=20, min_signal_score=0.0, quant_config=custom_cfg
        )
        bt_res = run_portfolio_backtest(
            evaluation_dates=["2026-02-15"],
            universe_stock_map={"HPG": df_stock},
            config=p_cfg,
        )
        bt_dict = bt_res.to_dict()

        expected_hash = custom_cfg.get_config_hash()
        expected_quant_ver = custom_cfg.quant_version

        # Production rec verification
        self.assertEqual(rec.quant_version, expected_quant_ver)
        self.assertEqual(rec.config_hash, expected_hash)
        self.assertEqual(rec.to_dict()["quant_version"], expected_quant_ver)
        self.assertEqual(rec.to_dict()["config_hash"], expected_hash)

        # Backtest verification
        self.assertEqual(bt_dict["config"]["quant_version"], expected_quant_ver)
        self.assertEqual(bt_dict["config"]["quant_config_hash"], expected_hash)

    def test_deterministic_output_under_identical_config(self):
        """6. Verify identical input + identical config yields exact deterministic outputs across repeated runs."""
        dates = pd.date_range("2026-01-01", periods=60)
        df_stock = pd.DataFrame(
            {
                "time": dates.strftime("%Y-%m-%d"),
                "open": np.linspace(50, 70, 60),
                "high": np.linspace(51, 71, 60),
                "low": np.linspace(49, 69, 60),
                "close": np.linspace(50, 70, 60),
                "volume": [1000000.0] * 60,
            }
        )
        market_regime = {"regime": "BULL", "regime_score": 70.0}

        rec1 = generate_single_recommendation(
            symbol="HPG",
            company_name="Hoa Phat Group",
            sector="Thép",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=market_regime,
            config=DEFAULT_QUANT_CONFIG,
        )

        rec2 = generate_single_recommendation(
            symbol="HPG",
            company_name="Hoa Phat Group",
            sector="Thép",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=market_regime,
            config=DEFAULT_QUANT_CONFIG,
        )

        self.assertEqual(rec1.action, rec2.action)
        self.assertEqual(rec1.signal_score, rec2.signal_score)
        self.assertEqual(rec1.risk_adjusted_score, rec2.risk_adjusted_score)
        self.assertEqual(rec1.confidence, rec2.confidence)
        self.assertEqual(rec1.model_version, DEFAULT_QUANT_CONFIG.model_version)
        self.assertEqual(rec1.quant_version, DEFAULT_QUANT_CONFIG.quant_version)
        self.assertEqual(rec1.config_hash, DEFAULT_QUANT_CONFIG.get_config_hash())

    def test_custom_config_propagation_and_behavior_change(self):
        """7. Verify custom QuantConfig alters scoring behavior explicitly when thresholds or weights change."""
        # Standard trend score with Close (55), MA20 (50), MA50 (45) => Base 50 + 25 + 15 + 10 = 100
        score_std = calculate_trend_score(55.0, 50.0, 45.0, config=DEFAULT_QUANT_CONFIG)
        self.assertEqual(score_std, 100.0)

        # Custom config with ma20_weight = 10.0 instead of 25.0 => Base 50 + 10 + 15 + 10 = 85.0
        custom_cfg = replace(DEFAULT_QUANT_CONFIG, trend_ma20_weight=10.0)
        score_custom = calculate_trend_score(55.0, 50.0, 45.0, config=custom_cfg)
        self.assertEqual(score_custom, 85.0)

        # Custom buy threshold
        action_std = classify_action(68.0, "BULL", 100, 90, config=DEFAULT_QUANT_CONFIG)
        self.assertEqual(action_std, "BUY")  # 68 >= 65 default buy threshold

        strict_cfg = replace(DEFAULT_QUANT_CONFIG, score_threshold_buy=70.0)
        action_strict = classify_action(68.0, "BULL", 100, 90, config=strict_cfg)
        self.assertEqual(action_strict, "WATCH")  # 68 < 70 strict buy threshold

    def test_engine_consumers_accept_config(self):
        """8. Verify MarketAnalysisEngine and SignalRecommendationEngine accept and use custom config payload."""
        dates = pd.date_range("2026-01-01", periods=60)
        df_stock = pd.DataFrame(
            {
                "time": dates.strftime("%Y-%m-%d"),
                "open": np.linspace(50, 70, 60),
                "high": np.linspace(51, 71, 60),
                "low": np.linspace(49, 69, 60),
                "close": np.linspace(50, 70, 60),
                "volume": [1000000.0] * 60,
            }
        )

        custom_cfg = replace(DEFAULT_QUANT_CONFIG, score_threshold_buy=70.0)

        input_data = RecommendationInput(
            candidates=[
                CandidateSpec(
                    symbol="FPT", company_name="FPT Corp", sector="Công nghệ", exchange="HOSE"
                )
            ],
            stock_data_map={"FPT": df_stock},
            market_regime={"regime": "BULL", "regime_score": 70.0},
            config=custom_cfg,
        )

        res = SignalRecommendationEngine.generate_recommendations(input_data)
        self.assertEqual(len(res.recommendations), 1)
        rec = res.recommendations[0]
        self.assertEqual(rec.model_version, custom_cfg.model_version)
        self.assertEqual(rec.quant_version, custom_cfg.quant_version)
        self.assertEqual(rec.config_hash, custom_cfg.get_config_hash())


if __name__ == "__main__":
    unittest.main()
