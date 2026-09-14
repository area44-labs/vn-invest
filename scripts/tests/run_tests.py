"""Test Runner for VN Invest v2 Unit Tests."""

import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


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


if __name__ == "__main__":
    loader = unittest.TestLoader()
    raw_suite = loader.discover(
        start_dir=os.path.dirname(os.path.abspath(__file__)), pattern="test_*.py"
    )
    suite = filter_suite(raw_suite)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
