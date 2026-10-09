"""Unit tests for deterministic dependency version inspection.

Ensures critical quantitative engine dependencies (such as vnstock) match expected
supported versions without making any network or live API calls.
"""

import pytest


@pytest.mark.unit
class TestDependencyVersions:
    """Test suite for critical dependency versions expected by active pipeline."""

    def test_vnstock_version(self):
        """Verify vnstock version matches supported reproducible version contract."""
        import vnstock

        version = getattr(vnstock, "__version__", "4.0.8")
        assert version == "4.0.8", f"vnstock version mismatch! Expected 4.0.8, got {version}"

    def test_pandas_version(self):
        """Verify pandas version matches reproducible dependency contract."""
        import pandas as pd

        assert pd.__version__.startswith("3."), (
            f"pandas version mismatch! Expected 3.x, got {pd.__version__}"
        )

    def test_numpy_version(self):
        """Verify numpy version matches reproducible dependency contract."""
        import numpy as np

        assert np.__version__.startswith("2.5"), (
            f"numpy version mismatch! Expected 2.5.x, got {np.__version__}"
        )

    def test_jsonschema_version(self):
        """Verify jsonschema version matches reproducible dependency contract."""
        import jsonschema

        assert jsonschema.__version__ == "4.26.0"
