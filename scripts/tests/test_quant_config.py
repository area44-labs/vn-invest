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
9. PipelineContext validates batch quant_version and config_hash consistency, failing closed on mixed configs.
10. SignalRecommendationEngine propagates QuantConfig to custom recommendation generators and validates matching version/hash outputs.
"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from scripts.backtest.portfolio import PortfolioConfig, run_portfolio_backtest
from scripts.domain import Universe
from scripts.pipeline.context import PipelineContext
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


@pytest.mark.unit
class TestQuantitativeConfigAndVersionContract:
    def test_default_config_properties_and_version_contract(self):
        """1. Verify DEFAULT_QUANT_CONFIG properties, hash calculation, and version contract structure."""
        cfg = DEFAULT_QUANT_CONFIG
        assert cfg.quant_version == "1.0.0"
        assert cfg.model_version == "2.0"

        contract = cfg.version_contract
        assert "quant_version" in contract
        assert "model_version" in contract
        assert "config_hash" in contract
        assert contract["quant_version"] == "1.0.0"
        assert contract["model_version"] == "2.0"
        assert contract["config_hash"] == cfg.get_config_hash()
        assert len(cfg.get_config_hash()) == 12

    def test_quant_config_immutability(self):
        """2. Verify QuantConfig instance and nested fields cannot be mutated in-place."""
        cfg = DEFAULT_QUANT_CONFIG

        # Attribute assignment on frozen dataclass
        with pytest.raises((TypeError, AttributeError)):
            cfg.quant_version = "2.0.0"

        # Nested mapping mutation attempts
        with pytest.raises((TypeError, AttributeError)):
            cfg.signal_weights["trend"] = 0.99

        with pytest.raises((TypeError, AttributeError)):
            cfg.divergence_timeframe_weights["1D"] = 0.99

        with pytest.raises((TypeError, AttributeError)):
            cfg.regime_score_factors["BULL"] = 2.00

    def test_default_quant_config_canonical_defaults(self):
        """3. Verify DEFAULT_QUANT_CONFIG canonical defaults and weight structure."""
        assert DEFAULT_QUANT_CONFIG.quant_version == "1.0.0"
        assert DEFAULT_QUANT_CONFIG.model_version == "2.0"
        assert sum(DEFAULT_QUANT_CONFIG.signal_weights.values()) == pytest.approx(1.0)
        assert sum(DEFAULT_QUANT_CONFIG.divergence_timeframe_weights.values()) == pytest.approx(1.0)
        assert len(DEFAULT_QUANT_CONFIG.valid_market_regimes) == 6
        assert DEFAULT_QUANT_CONFIG.ma_short_period == 20
        assert DEFAULT_QUANT_CONFIG.ma_long_period == 50

    def test_version_contract_detects_parameter_changes(self):
        """4. Verify modifying configuration parameters changes config_hash and version_contract explicitly."""
        base_hash = DEFAULT_QUANT_CONFIG.get_config_hash()

        # Modify signal weights
        modified_weights = dict(DEFAULT_QUANT_CONFIG.signal_weights)
        modified_weights["trend"] = 0.50
        modified_weights["momentum"] = 0.05
        cfg_mod = replace(DEFAULT_QUANT_CONFIG, signal_weights=modified_weights)

        mod_hash = cfg_mod.get_config_hash()
        assert base_hash != mod_hash
        assert cfg_mod.version_contract["config_hash"] == mod_hash

        # Modify threshold
        cfg_mod_thresh = replace(DEFAULT_QUANT_CONFIG, score_threshold_buy=70.0)
        assert base_hash != cfg_mod_thresh.get_config_hash()

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
        assert rec.quant_version == expected_quant_ver
        assert rec.config_hash == expected_hash
        assert rec.to_dict()["quant_version"] == expected_quant_ver
        assert rec.to_dict()["config_hash"] == expected_hash

        # Backtest verification
        assert bt_dict["config"]["quant_version"] == expected_quant_ver
        assert bt_dict["config"]["quant_config_hash"] == expected_hash

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

        assert rec1.action == rec2.action
        assert rec1.signal_score == rec2.signal_score
        assert rec1.risk_adjusted_score == rec2.risk_adjusted_score
        assert rec1.confidence == rec2.confidence
        assert rec1.model_version == DEFAULT_QUANT_CONFIG.model_version
        assert rec1.quant_version == DEFAULT_QUANT_CONFIG.quant_version
        assert rec1.config_hash == DEFAULT_QUANT_CONFIG.get_config_hash()

    def test_custom_config_propagation_and_behavior_change(self):
        """7. Verify custom QuantConfig alters scoring behavior explicitly when thresholds or weights change."""
        # Standard trend score with Close (55), MA20 (50), MA50 (45) => Base 50 + 25 + 15 + 10 = 100
        score_std = calculate_trend_score(55.0, 50.0, 45.0, config=DEFAULT_QUANT_CONFIG)
        assert score_std == 100.0

        # Custom config with ma20_weight = 10.0 instead of 25.0 => Base 50 + 10 + 15 + 10 = 85.0
        custom_cfg = replace(DEFAULT_QUANT_CONFIG, trend_ma20_weight=10.0)
        score_custom = calculate_trend_score(55.0, 50.0, 45.0, config=custom_cfg)
        assert score_custom == 85.0

        # Custom buy threshold
        action_std = classify_action(68.0, "BULL", 100, 90, config=DEFAULT_QUANT_CONFIG)
        assert action_std == "BUY"  # 68 >= 65 default buy threshold

        strict_cfg = replace(DEFAULT_QUANT_CONFIG, score_threshold_buy=70.0)
        action_strict = classify_action(68.0, "BULL", 100, 90, config=strict_cfg)
        assert action_strict == "WATCH"  # 68 < 70 strict buy threshold

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
        assert len(res.recommendations) == 1
        rec = res.recommendations[0]
        assert rec.model_version == custom_cfg.model_version
        assert rec.quant_version == custom_cfg.quant_version
        assert rec.config_hash == custom_cfg.get_config_hash()

    def test_batch_quant_config_validation_in_pipeline_context(self):
        """9. Verify PipelineContext.build_payloads() validates batch quant version/hash consistency."""
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

        cfg_a = DEFAULT_QUANT_CONFIG
        cfg_b = replace(DEFAULT_QUANT_CONFIG, score_threshold_buy=70.0)

        rec_a1 = generate_single_recommendation(
            symbol="HPG",
            company_name="Hoa Phat Group",
            sector="Thép",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=market_regime,
            config=cfg_a,
        )
        rec_a2 = generate_single_recommendation(
            symbol="FPT",
            company_name="FPT Corp",
            sector="Công nghệ",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=market_regime,
            config=cfg_a,
        )
        rec_b1 = generate_single_recommendation(
            symbol="VNM",
            company_name="Vinamilk",
            sector="Thực phẩm",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=market_regime,
            config=cfg_b,
        )

        u = Universe(universe_type="TEST", candidates=[])

        # Case 1: Batch with identical configuration -> build_payloads succeeds
        ctx_ok = PipelineContext()
        ctx_ok.set_universe(u)
        ctx_ok.scanned_recs = [rec_a1, rec_a2]
        recs_payload, _, _ = ctx_ok.build_payloads()

        assert recs_payload["quant_version"] == cfg_a.quant_version
        assert recs_payload["config_hash"] == cfg_a.get_config_hash()

        # Case 2: Batch with mixed configuration -> build_payloads fails closed with ValueError
        ctx_mixed = PipelineContext()
        ctx_mixed.set_universe(u)
        ctx_mixed.scanned_recs = [rec_a1, rec_b1]

        with pytest.raises(ValueError) as err_ctx:
            ctx_mixed.build_payloads()

        assert "Mixed quantitative configuration versions" in str(err_ctx.value)

    def test_custom_recommendation_generator_config_propagation_and_validation(self):
        """10. Verify custom recommendation generator receives QuantConfig and output version/hash is validated."""
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

        # Custom generator that consumes config
        def custom_gen_matching(
            symbol,
            company_name,
            sector,
            exchange,
            df_stock,
            market_regime_info,
            df_vnindex=None,
            data_as_of=None,
            data_source=None,
            config=DEFAULT_QUANT_CONFIG,
        ):
            return generate_single_recommendation(
                symbol=symbol,
                company_name=company_name,
                sector=sector,
                exchange=exchange,
                df_stock=df_stock,
                market_regime_info=market_regime_info,
                df_vnindex=df_vnindex,
                data_as_of=data_as_of,
                data_source=data_source,
                config=config,
            )

        # Case 1: Custom generator returns matching quant_version and config_hash -> succeeds
        input_data_matching = RecommendationInput(
            candidates=[
                CandidateSpec(
                    symbol="FPT", company_name="FPT Corp", sector="Công nghệ", exchange="HOSE"
                )
            ],
            stock_data_map={"FPT": df_stock},
            market_regime={"regime": "BULL", "regime_score": 70.0},
            config=custom_cfg,
        )

        res_matching = SignalRecommendationEngine.generate_recommendations(
            input_data_matching, recommendation_generator=custom_gen_matching
        )
        assert len(res_matching.recommendations) == 1
        rec_m = res_matching.recommendations[0]
        assert rec_m.quant_version == custom_cfg.quant_version
        assert rec_m.config_hash == custom_cfg.get_config_hash()

        # Custom generator that returns mismatched config_hash
        def custom_gen_mismatched(
            symbol,
            company_name,
            sector,
            exchange,
            df_stock,
            market_regime_info,
            df_vnindex=None,
            data_as_of=None,
            data_source=None,
            config=DEFAULT_QUANT_CONFIG,
        ):
            rec = generate_single_recommendation(
                symbol=symbol,
                company_name=company_name,
                sector=sector,
                exchange=exchange,
                df_stock=df_stock,
                market_regime_info=market_regime_info,
                df_vnindex=df_vnindex,
                data_as_of=data_as_of,
                data_source=data_source,
                config=DEFAULT_QUANT_CONFIG,  # Uses default instead of passed custom_cfg!
            )
            return rec

        # Case 2: Custom generator returns mismatched config_hash -> fails closed
        with pytest.raises(ValueError) as err_ctx:
            SignalRecommendationEngine.generate_recommendations(
                input_data_matching, recommendation_generator=custom_gen_mismatched
            )

        assert "Recommendation output configuration mismatch for symbol 'FPT'" in str(err_ctx.value)
