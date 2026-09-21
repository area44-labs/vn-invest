import json
import os
import unittest


class TestSSGStaticHTML(unittest.TestCase):
    """
    Automated regression test suite verifying true SSG static HTML pre-rendering.
    Prevents regression back to initial loading placeholders and useEffect-only loading.
    """

    def test_single_source_of_truth_no_duplicate_public_generated(self):
        """Verify generated/ is the single source of truth and public/generated does not exist."""
        public_generated_path = os.path.join(os.getcwd(), "public", "generated")
        self.assertFalse(
            os.path.exists(public_generated_path),
            f"Duplicate data source found at '{public_generated_path}'. "
            "generated/ must be the single source of truth; public/generated/ must not exist.",
        )

    def test_generated_data_plugin_path_boundary_security(self):
        """Verify resolveGeneratedFilePath path boundary security invariants in Vite dev server."""
        import subprocess

        node_script = """
const path = require("path");
const fs = require("fs");

function resolveGeneratedFilePath(urlPath, rootDir = process.cwd()) {
  if (!urlPath) return null;
  const relativeUrl = urlPath.split("?")[0].split("#")[0];
  const match = relativeUrl.match(/\\/?(?:.*\\/)?(generated\\/.*)$/);
  if (!match) return null;

  const subPath = match[1];
  const generatedDir = path.resolve(rootDir, "generated");
  const resolvedPath = path.resolve(rootDir, subPath);

  const rel = path.relative(generatedDir, resolvedPath);
  const isInside = rel !== "" && !rel.startsWith("..") && !path.isAbsolute(rel);
  if (!isInside) return null;

  try {
    if (fs.existsSync(resolvedPath) && fs.statSync(resolvedPath).isFile()) {
      return resolvedPath;
    }
  } catch {
    return null;
  }
  return null;
}

const tests = {
  valid: resolveGeneratedFilePath("/generated/recommendations.json"),
  traversal: resolveGeneratedFilePath("/generated/../package.json"),
  outside: resolveGeneratedFilePath("/package.json"),
  directory: resolveGeneratedFilePath("/generated/history"),
  sibling: resolveGeneratedFilePath("/generated-secret/file.json"),
};

console.log(JSON.stringify(tests));
"""

        res = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True,
            text=True,
            check=True,
        )
        results = json.loads(res.stdout)

        # 1. Valid generated JSON file can be served
        self.assertIsNotNone(results.get("valid"))
        self.assertTrue(
            results["valid"].endswith(os.path.join("generated", "recommendations.json"))
        )

        # 2. Path traversal cannot escape generated/
        self.assertIsNone(results.get("traversal"))

        # 3. Path outside generated/ is not served
        self.assertIsNone(results.get("outside"))

        # 4. Directory is not served as a JSON file
        self.assertIsNone(results.get("directory"))

        # 5. Sibling directory with shared prefix is not served
        self.assertIsNone(results.get("sibling"))

    def test_dashboard_static_html_contains_recommendation_data(self):
        index_html_path = os.path.join(os.getcwd(), "dist", "client", "index.html")
        rec_json_path = os.path.join(os.getcwd(), "generated", "recommendations.json")

        self.assertTrue(
            os.path.exists(index_html_path),
            f"Build artifact missing: {index_html_path}. Run `vp build` before running SSG tests.",
        )
        self.assertTrue(
            os.path.exists(rec_json_path),
            f"Canonical data artifact missing: {rec_json_path}.",
        )

        with open(rec_json_path, "r", encoding="utf-8") as f:
            rec_data = json.load(f)

        with open(index_html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # 1. Must NOT contain initial loading placeholder
        self.assertNotIn(
            "Đang tải dữ liệu phân tích thị trường VN Invest...",
            html_content,
            "Dashboard HTML contains loading placeholder instead of SSG pre-rendered content!",
        )

        # 2. Must contain market regime & source_date
        market_regime = rec_data.get("market", {}).get("regime")
        if market_regime:
            self.assertIn(
                market_regime,
                html_content,
                f"Dashboard static HTML missing market regime '{market_regime}'",
            )

        source_date = rec_data.get("source_date")
        if source_date:
            self.assertIn(
                source_date,
                html_content,
                f"Dashboard static HTML missing source_date '{source_date}'",
            )

        # 3. Must contain rendered quantitative fields for top recommendations displayed in cards
        recommendations = rec_data.get("recommendations", [])
        self.assertTrue(
            len(recommendations) > 0,
            "No recommendations found in generated/recommendations.json",
        )

        # Filter top Buys & Sells as rendered on Dashboard cards
        buy_list = [r for r in recommendations if r.get("action") in ("BUY", "WATCH")]
        sell_list = [r for r in recommendations if r.get("action") in ("SELL", "AVOID", "HOLD")]

        sorted_buys = sorted(
            buy_list,
            key=lambda x: (
                x.get("risk_adjusted_score")
                if x.get("risk_adjusted_score") is not None
                else (x.get("signal_score") or 0)
            ),
            reverse=True,
        )
        sorted_sells = sorted(
            sell_list,
            key=lambda x: (
                x.get("risk_adjusted_score")
                if x.get("risk_adjusted_score") is not None
                else (x.get("signal_score") or 0)
            ),
            reverse=True,
        )

        rendered_top_recs = sorted_buys[:4] + sorted_sells[:4]
        self.assertTrue(len(rendered_top_recs) > 0, "No top recommendations rendered.")

        for rec in rendered_top_recs:
            symbol = rec.get("symbol")
            action = rec.get("action")
            signal_score = rec.get("signal_score")
            risk_adj_score = rec.get("risk_adjusted_score")

            self.assertIn(
                symbol,
                html_content,
                f"Dashboard static HTML missing recommendation symbol '{symbol}'",
            )

            if action:
                self.assertIn(
                    action,
                    html_content,
                    f"Dashboard static HTML missing action '{action}' for '{symbol}'",
                )

            if signal_score is not None:
                formatted_signal = f"{signal_score:.1f}"
                self.assertIn(
                    formatted_signal,
                    html_content,
                    f"Dashboard static HTML missing formatted signal_score '{formatted_signal}' for '{symbol}'",
                )

            if risk_adj_score is not None:
                formatted_risk_adj = f"{risk_adj_score:.1f}"
                self.assertIn(
                    formatted_risk_adj,
                    html_content,
                    f"Dashboard static HTML missing formatted risk_adjusted_score '{formatted_risk_adj}' for '{symbol}'",
                )

    def test_stock_detail_static_html_for_all_prerendered_symbols(self):
        rec_json_path = os.path.join(os.getcwd(), "generated", "recommendations.json")
        self.assertTrue(
            os.path.exists(rec_json_path),
            f"Canonical data artifact missing: {rec_json_path}.",
        )

        with open(rec_json_path, "r", encoding="utf-8") as f:
            rec_data = json.load(f)

        recommendations = rec_data.get("recommendations", [])
        self.assertTrue(
            len(recommendations) > 0, "No recommendations found in recommendations.json"
        )

        # 1. Derive EXPECTED stock symbols directly from generated/recommendations.json
        expected_symbols = sorted(
            {
                r.get("symbol").strip()
                for r in recommendations
                if r.get("symbol") and r.get("symbol").strip()
            }
        )
        self.assertTrue(
            len(expected_symbols) > 0,
            "Expected stock symbols list from recommendations.json is empty.",
        )

        stock_dir = os.path.join(os.getcwd(), "dist", "client", "stock")
        self.assertTrue(
            os.path.exists(stock_dir),
            f"Stock output directory missing: {stock_dir}. Run `vp build` first.",
        )

        # 2. Check actual prerendered directories in dist/client/stock/
        actual_directories = sorted(
            [d for d in os.listdir(stock_dir) if os.path.isdir(os.path.join(stock_dir, d))]
        )

        self.assertEqual(
            actual_directories,
            expected_symbols,
            f"Prerendered stock directories in dist/client/stock/ ({actual_directories}) "
            f"do not match expected symbols from recommendations.json ({expected_symbols})",
        )

        rec_by_symbol = {r.get("symbol"): r for r in recommendations if r.get("symbol")}

        # 3. Assert for every expected symbol that static HTML exists and contains real data
        for symbol in expected_symbols:
            rec = rec_by_symbol[symbol]
            stock_html_path = os.path.join(stock_dir, symbol, "index.html")

            self.assertTrue(
                os.path.exists(stock_html_path),
                f"Expected stock HTML missing for symbol '{symbol}' at: {stock_html_path}.",
            )

            with open(stock_html_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            # Must NOT contain loading placeholder
            self.assertNotIn(
                "Đang tải phân tích định lượng cổ phiếu",
                html_content,
                f"Stock detail static HTML for '{symbol}' contains loading placeholder!",
            )

            # Must contain symbol
            self.assertIn(
                symbol,
                html_content,
                f"Stock detail HTML for '{symbol}' missing symbol string.",
            )

            # Must contain at least one quantitative value (signal_score or risk_adjusted_score)
            signal_score = rec.get("signal_score")
            risk_adj_score = rec.get("risk_adjusted_score")
            if signal_score is not None:
                self.assertIn(
                    f"{signal_score:.1f}",
                    html_content,
                    f"Stock detail static HTML for '{symbol}' missing signal_score.",
                )
            elif risk_adj_score is not None:
                self.assertIn(
                    f"{risk_adj_score:.1f}",
                    html_content,
                    f"Stock detail static HTML for '{symbol}' missing risk_adjusted_score.",
                )


if __name__ == "__main__":
    unittest.main()
