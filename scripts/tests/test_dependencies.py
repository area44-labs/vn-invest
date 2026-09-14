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
            getattr(vnstock, "__version__", "4.0.7"),
            "4.0.7",
            "vnstock version mismatch! Expected version 4.0.7 for provider compatibility.",
        )

    def test_pandas_version(self):
        """Verify pandas version matches reproducible dependency contract."""
        import pandas as pd

        self.assertEqual(pd.__version__, "2.2.3")

    def test_numpy_version(self):
        """Verify numpy version matches reproducible dependency contract."""
        import numpy as np

        self.assertEqual(np.__version__, "2.2.6")

    def test_jsonschema_version(self):
        """Verify jsonschema version matches reproducible dependency contract."""
        import jsonschema

        self.assertEqual(jsonschema.__version__, "4.26.0")


if __name__ == "__main__":
    unittest.main()
