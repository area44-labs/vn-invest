import json
import os
import unittest


class TestSSGStaticHTML(unittest.TestCase):
    """
    Automated regression test suite verifying true SSG static HTML pre-rendering.
    Prevents regression back to initial loading placeholders and useEffect-only loading.
    """

    def test_dashboard_static_html_contains_recommendation_data(self):
        index_html_path = os.path.join(os.getcwd(), "dist", "client", "index.html")
        rec_json_path = os.path.join(os.getcwd(), "public", "generated", "recommendations.json")

        if not os.path.exists(index_html_path):
            self.skipTest("dist/client/index.html not found. Run `pnpm build` first.")

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

        # 2. Must contain market regime
        regime = rec_data.get("market", {}).get("regime")
        if regime:
            self.assertIn(
                regime,
                html_content,
                f"Dashboard static HTML missing market regime '{regime}'",
            )

        # 3. Must contain source date
        source_date = rec_data.get("source_date")
        if source_date:
            self.assertIn(
                source_date,
                html_content,
                f"Dashboard static HTML missing source_date '{source_date}'",
            )

        # 4. Must contain at least one real recommendation symbol from generated data
        recommendations = rec_data.get("recommendations", [])
        if recommendations:
            symbol = recommendations[0].get("symbol")
            action = recommendations[0].get("action")
            self.assertIn(
                symbol,
                html_content,
                f"Dashboard static HTML missing recommendation symbol '{symbol}'",
            )
            if action:
                self.assertIn(
                    action,
                    html_content,
                    f"Dashboard static HTML missing recommendation action '{action}'",
                )

    def test_stock_detail_static_html_contains_symbol_data(self):
        stock_html_path = os.path.join(os.getcwd(), "dist", "client", "stock", "ACB", "index.html")
        if not os.path.exists(stock_html_path):
            self.skipTest("dist/client/stock/ACB/index.html not found. Run `pnpm build` first.")

        with open(stock_html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        self.assertNotIn(
            "Đang tải phân tích định lượng cổ phiếu",
            html_content,
            "Stock detail static HTML contains loading placeholder!",
        )
        self.assertIn("ACB", html_content)


if __name__ == "__main__":
    unittest.main()
