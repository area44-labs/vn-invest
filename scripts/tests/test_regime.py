"""Unit tests for Market Regime in scripts/lib/regime.py."""

import unittest

import numpy as np
import pandas as pd

from scripts.lib.regime import (
    RegimeEvaluationResult,
    RegimeObservation,
    detect_market_regime,
    evaluate_market_regimes,
)


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

    def test_regime_validation_exports(self):
        """Verify regime module exports RegimeObservation, RegimeEvaluationResult, evaluate_market_regimes."""
        self.assertTrue(callable(evaluate_market_regimes))
        self.assertTrue(hasattr(RegimeObservation, "to_dict"))
        self.assertTrue(hasattr(RegimeEvaluationResult, "to_dict"))


if __name__ == "__main__":
    unittest.main()
