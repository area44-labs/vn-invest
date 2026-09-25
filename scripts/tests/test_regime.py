"""Unit tests for Market Regime in scripts/lib/regime.py."""

import unittest

import numpy as np
import pandas as pd

from scripts.lib.regime import detect_market_regime


class TestMarketRegime(unittest.TestCase):
    def test_strong_bull_regime(self):
        n = 60
        close_prices = np.linspace(1200, 1500, n)
        df_vnindex = pd.DataFrame({"close": close_prices, "volume": [1e8] * n})

        res = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.80)
        self.assertIn(res["regime"], ["STRONG_BULL", "BULL"])
        self.assertGreaterEqual(res["regime_score"], 60.0)

    def test_panic_or_bear_regime(self):
        n = 60
        close_prices = np.linspace(1500, 1000, n)
        close_prices[-1] = close_prices[-2] * 0.95
        df_vnindex = pd.DataFrame({"close": close_prices, "volume": [1e8] * n})

        res = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.10)
        self.assertIn(res["regime"], ["BEAR", "PANIC"])
        self.assertLessEqual(res["regime_score"], 40.0)

    def test_insufficient_data_regime(self):
        res = detect_market_regime(df_vnindex=None)
        self.assertEqual(res["regime"], "DEFENSIVE")
        self.assertLess(res["confidence"], 0.5)

    def test_volume_validation_cases(self):
        """Test volume validation: valid volume, NaN, Inf, negative, 0 mean, and NaN/Inf leak checks."""
        n = 30
        close_prices = np.linspace(1200, 1300, n)

        # 1. Valid volume
        df_valid = pd.DataFrame({"close": close_prices, "volume": [100.0] * n})
        res_valid = detect_market_regime(df_vnindex=df_valid, breadth_ratio=0.5)
        self.assertEqual(res_valid["metrics"]["volume_20d_ratio"], 1.0)

        # 2. Volume with NaN
        df_nan = pd.DataFrame({"close": close_prices, "volume": [100.0] * n})
        df_nan.loc[5, "volume"] = np.nan
        res_nan = detect_market_regime(df_vnindex=df_nan, breadth_ratio=0.5)
        self.assertIsNone(res_nan["metrics"]["volume_20d_ratio"])

        # 3. Volume with Inf
        df_inf = pd.DataFrame({"close": close_prices, "volume": [100.0] * n})
        df_inf.loc[5, "volume"] = np.inf
        res_inf = detect_market_regime(df_vnindex=df_inf, breadth_ratio=0.5)
        self.assertIsNone(res_inf["metrics"]["volume_20d_ratio"])

        # 4. Negative volume
        df_neg = pd.DataFrame({"close": close_prices, "volume": [100.0] * n})
        df_neg.loc[5, "volume"] = -50.0
        res_neg = detect_market_regime(df_vnindex=df_neg, breadth_ratio=0.5)
        self.assertIsNone(res_neg["metrics"]["volume_20d_ratio"])

        # 5. Volume with 20d mean = 0
        df_zero_mean = pd.DataFrame({"close": close_prices, "volume": [0.0] * n})
        res_zero = detect_market_regime(df_vnindex=df_zero_mean, breadth_ratio=0.5)
        self.assertIsNone(res_zero["metrics"]["volume_20d_ratio"])

        # 6. Verify all output metrics contain no NaN or Inf across all cases
        import math

        for res in [res_valid, res_nan, res_inf, res_neg, res_zero]:
            for k, v in res["metrics"].items():
                if v is not None:
                    self.assertFalse(math.isnan(v), f"Metric {k} is NaN")
                    self.assertFalse(math.isinf(v), f"Metric {k} is Inf")

    def test_regime_module_independent_of_backtest(self):
        """Verify scripts.lib.regime can be imported without importing scripts.lib.backtest."""
        import sys

        # Remove backtest from sys.modules if present to test independent import
        sys.modules.pop("scripts.lib.backtest", None)
        import scripts.lib.regime as regime_mod

        self.assertTrue(hasattr(regime_mod, "detect_market_regime"))
        self.assertNotIn("RegimeObservation", regime_mod.__all__)
        self.assertNotIn("evaluate_market_regimes", regime_mod.__all__)


if __name__ == "__main__":
    unittest.main()
