"""Orchestration Contract Tests for Daily Automated Production Data Update Workflow."""

import json
import os
import unittest

import jsonschema

from scripts.generate_report import GENERATED_DIR, SCHEMA_PATH, load_history_index, run_pipeline
from scripts.lib.monitoring import evaluate_production_monitoring

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOW_PATH = os.path.join(ROOT_DIR, ".github", "workflows", "daily-update.yml")


class TestDailyUpdateOrchestration(unittest.TestCase):
    """Test suite verifying daily update workflow orchestration contract and safety constraints."""

    def test_a_production_command_contract(self):
        """Test A: Verify workflow exists, uses python scripts/generate_report.py --update, has schedule and workflow_dispatch, and forbids --as-of."""
        self.assertTrue(os.path.exists(WORKFLOW_PATH), f"Workflow file missing at {WORKFLOW_PATH}")

        with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("python scripts/generate_report.py --update", content)
        self.assertNotIn("--as-of", content, "Daily production workflow must NOT use --as-of flag")
        self.assertIn("workflow_dispatch:", content)
        self.assertIn("schedule:", content)
        self.assertIn('cron: "0 11 * * 1-5"', content)
        self.assertIn("contents: write", content)
        self.assertIn("group: daily-update-${{ github.ref }}", content)

    def test_b_and_c_no_fake_data_or_error_swallowing(self):
        """Test B & C: Verify workflow does NOT swallow step errors or use continue-on-error / || true."""
        with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("continue-on-error: true", content.lower())
        self.assertNotIn("|| true", content)
        self.assertNotIn("|| exit 0", content)

        # Verify monitoring fail-closed check step fails if monitoring status != PASS
        self.assertIn("if status != 'PASS':", content)
        self.assertIn("sys.exit(1)", content)

    def test_d_no_empty_commit_and_stage_scope_contract(self):
        """Test D: Verify git commit step strictly restricts staged files to generated/ and skips empty commits."""
        with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("git add generated/", content)
        self.assertNotIn("git add .", content)
        self.assertNotIn("git add -A", content)
        self.assertIn("No changes to generated artifacts to commit.", content)

    def test_e_generated_artifacts_contract(self):
        """Test E: Verify production pipeline execution produces valid recommendations.json, market.json, monitoring.json, and history/index.json."""
        pipeline_res = run_pipeline(update_data=False)
        recs_data, market_data, _history_data = pipeline_res

        # 1. Schema validation
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(instance=recs_data, schema=schema)

        # 2. Key requirements
        self.assertIn("schema_version", recs_data)
        self.assertIn("signal_model_version", recs_data)
        self.assertIn("generated_at", recs_data)
        self.assertIn("data_as_of", recs_data)
        self.assertIn("summary", recs_data)
        self.assertIn("recommendations", recs_data)

        # 3. Market regime validation
        self.assertIn("regime", market_data.get("market", market_data))

        # 4. Monitoring evaluation contract
        monitoring_res = evaluate_production_monitoring(
            generated_dir=GENERATED_DIR,
            recommendations_payload=recs_data,
            market_payload=market_data,
            df_vnindex=pipeline_res.df_vnindex,
            df_vn30=pipeline_res.df_vn30,
        )
        # Should evaluate to a valid status (PASS/WARNING/FAIL)
        self.assertIn(monitoring_res.overall_status, {"PASS", "WARNING", "FAIL"})

        # 5. History index contract
        index_data = load_history_index()
        self.assertIsInstance(index_data, dict)
        self.assertIn("dates", index_data)
        self.assertIsInstance(index_data["dates"], list)


if __name__ == "__main__":
    unittest.main()
