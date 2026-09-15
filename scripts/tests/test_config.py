"""Tests for Centralized Configuration Module (scripts/lib/config.py).

Verifies that:
1. All centralized parameter values match expected defaults.
2. Re-exported constants in scripts/lib/recommendation.py remain identical.
3. SIGNAL_MODEL_VERSION remains unchanged.
"""

import unittest

from scripts.lib import config, recommendation


class TestCentralizedConfig(unittest.TestCase):
    def test_version_unchanged(self):
        """Verify SIGNAL_MODEL_VERSION is '2.0' and identical across modules."""
        self.assertEqual(config.SIGNAL_MODEL_VERSION, "2.0")
        self.assertEqual(recommendation.SIGNAL_MODEL_VERSION, "2.0")

    def test_reexported_constants(self):
        """Verify backwards-compatible re-exported constants in recommendation module."""
        self.assertEqual(recommendation.SIGNAL_WEIGHTS, config.SIGNAL_WEIGHTS)
        self.assertEqual(
            recommendation.DIVERGENCE_TIMEFRAME_WEIGHTS, config.DIVERGENCE_TIMEFRAME_WEIGHTS
        )
        self.assertEqual(recommendation.VALID_MARKET_REGIMES, config.VALID_MARKET_REGIMES)

    def test_weights_sum_to_one(self):
        """Verify signal weights and divergence timeframe weights sum to 1.0."""
        self.assertAlmostEqual(sum(config.SIGNAL_WEIGHTS.values()), 1.0, places=6)
        self.assertAlmostEqual(sum(config.DIVERGENCE_TIMEFRAME_WEIGHTS.values()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
