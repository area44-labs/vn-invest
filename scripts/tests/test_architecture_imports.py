"""Static Architecture Import Tests for VN Invest Backend.

Verifies unidirectional import hierarchy:
- scripts.lib.risk MUST NOT import or reference scripts.lib.recommendation
- scripts.lib.scoring MUST NOT import or reference scripts.lib.recommendation
- scripts.lib.config MUST NOT import any other lib module
"""

import ast
import os
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB_DIR = os.path.join(ROOT_DIR, "scripts", "lib")


def parse_file_ast_imports(filepath: str) -> set[str]:
    """Parse a python file AST and return all imported module names."""
    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filepath)

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


class TestArchitectureImports(unittest.TestCase):
    """Enforce static architecture import boundaries."""

    def test_risk_module_has_no_recommendation_import(self):
        """Verify scripts.lib.risk does not import scripts.lib.recommendation."""
        risk_path = os.path.join(LIB_DIR, "risk.py")
        imports = parse_file_ast_imports(risk_path)

        forbidden = "scripts.lib.recommendation"
        self.assertNotIn(
            forbidden,
            imports,
            f"Architecture violation: {risk_path} must not import {forbidden}",
        )

    def test_scoring_module_has_no_recommendation_import(self):
        """Verify scripts.lib.scoring does not import scripts.lib.recommendation."""
        scoring_path = os.path.join(LIB_DIR, "scoring.py")
        imports = parse_file_ast_imports(scoring_path)

        forbidden = "scripts.lib.recommendation"
        self.assertNotIn(
            forbidden,
            imports,
            f"Architecture violation: {scoring_path} must not import {forbidden}",
        )

    def test_config_module_has_no_lib_imports(self):
        """Verify scripts.lib.config is leaf configuration without internal lib imports."""
        config_path = os.path.join(LIB_DIR, "config.py")
        imports = parse_file_ast_imports(config_path)

        for imp in imports:
            self.assertFalse(
                imp.startswith("scripts.lib"),
                f"Architecture violation: {config_path} must not import lib module '{imp}'",
            )


if __name__ == "__main__":
    unittest.main()
