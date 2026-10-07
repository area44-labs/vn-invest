"""Shared pytest fixtures and configuration for VN Invest backend test suite."""

import pytest

from scripts.tests import enforce_network_isolation


def pytest_configure(config: pytest.Config) -> None:
    """Ensure process-wide network isolation is active before any test runs."""
    enforce_network_isolation()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """Log diagnostic message for slow backend tests (>= 5.0 seconds)."""
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and call.duration >= 5.0:
        # Print slow test warning matching legacy TimingTestRunner format
        print(f"\nSLOW TEST: {item.nodeid} — {call.duration:.2f}s")
