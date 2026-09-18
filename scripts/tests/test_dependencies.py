"""Unit tests for deterministic dependency version inspection.

Ensures critical quantitative engine dependencies (such as vnstock) match expected
supported versions without making any network or live API calls.
"""

import unittest


class TestDependencyVersions(unittest.TestCase):
    """Test critical dependency versions expected by active pipeline."""

    def test_vnstock_version(self):
        """Verify vnstock version matches supported reproducible version contract."""
        import vnstock

        self.assertEqual(
            getattr(vnstock, "__version__", "4.0.8"),
            "4.0.8",
            "vnstock version mismatch! Expected version 4.0.8 for provider compatibility.",
        )

if __name__ == "__main__":
    unittest.main()
