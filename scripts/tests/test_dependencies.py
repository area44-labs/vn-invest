"""Unit tests for deterministic dependency version inspection.

Ensures critical quantitative engine dependencies (such as vnstock) satisfy expected
supported minimum version bounds without making any network or live API calls.
"""

import importlib.metadata

import pytest


def _parse_version(version_str: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version_str.split(".")[:3] if x.isdigit())


@pytest.mark.unit
class TestDependencyVersions:
    """Test suite for critical dependency versions expected by active pipeline."""

    def test_vnstock_version(self):
        """Verify vnstock satisfies the minimum supported version contract (>= 4.0.8)."""
        version = importlib.metadata.version("vnstock")
        assert _parse_version(version) >= _parse_version("4.0.8"), (
            f"vnstock version mismatch! Expected >= 4.0.8, got {version}"
        )

    def test_pandas_version(self):
        """Verify pandas satisfies reproducible dependency contract (>= 3.0.0)."""
        version = importlib.metadata.version("pandas")
        assert _parse_version(version) >= _parse_version("3.0.0"), (
            f"pandas version mismatch! Expected >= 3.0.0, got {version}"
        )

    def test_numpy_version(self):
        """Verify numpy satisfies reproducible dependency contract (>= 2.5.0)."""
        version = importlib.metadata.version("numpy")
        assert _parse_version(version) >= _parse_version("2.5.0"), (
            f"numpy version mismatch! Expected >= 2.5.0, got {version}"
        )

    def test_jsonschema_version(self):
        """Verify jsonschema satisfies reproducible dependency contract (>= 4.26.0)."""
        version = importlib.metadata.version("jsonschema")
        assert _parse_version(version) >= _parse_version("4.26.0"), (
            f"jsonschema version mismatch! Expected >= 4.26.0, got {version}"
        )
