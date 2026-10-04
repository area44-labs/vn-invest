"""Test Runner for VN Invest v2 Unit Tests."""

import os
import sys
import time
import unittest

from scripts.tests import enforce_network_isolation

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

enforce_network_isolation()


def filter_suite(suite: unittest.TestSuite) -> unittest.TestSuite:
    """Filter out frontend SSG HTML tests when build artifacts (dist/client) are absent."""
    index_html_path = os.path.join(ROOT_DIR, "dist", "client", "index.html")
    has_ssg_build = os.path.exists(index_html_path)

    filtered = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            filtered.addTest(filter_suite(item))
        else:
            if "TestSSGStaticHTML" in type(item).__name__ and not has_ssg_build:
                continue
            filtered.addTest(item)
    return filtered


class TimingTestResult(unittest.TextTestResult):
    """Test result class that logs diagnostic messages for slow tests (>5s)."""

    def startTest(self, test: unittest.TestCase) -> None:
        self._test_start_time = time.time()
        super().startTest(test)

    def stopTest(self, test: unittest.TestCase) -> None:
        elapsed = time.time() - getattr(self, "_test_start_time", time.time())
        super().stopTest(test)
        if elapsed >= 5.0:
            self.stream.writeln(f"SLOW TEST: {test} — {elapsed:.2f}s")
            self.stream.flush()


class TimingTestRunner(unittest.TextTestRunner):
    resultclass = TimingTestResult


if __name__ == "__main__":
    loader = unittest.TestLoader()
    raw_suite = loader.discover(
        start_dir=os.path.dirname(os.path.abspath(__file__)), pattern="test_*.py"
    )
    suite = filter_suite(raw_suite)
    runner = TimingTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
