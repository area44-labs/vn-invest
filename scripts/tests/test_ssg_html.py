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

        self.assertTrue(
            os.path.exists(index_html_path),
            f"Build artifact missing: {index_html_path}. Run `pnpm build` before running SSG tests.",
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

        # 3. Must contain rendered recommendation fields from generated recommendations
        recommendations = rec_data.get("recommendations", [])
        self.assertTrue(
            len(recommendations) > 0,
            "No recommendations found in public/generated/recommendations.json",
        )

        # Test fields for top recommendations
        for rec in recommendations[:3]:
            symbol = rec.get("symbol")
            action = rec.get("action")
            self.assertIn(
                symbol,
                html_content,
                f"Dashboard static HTML missing recommendation symbol '{symbol}'",
            )
            if action:
                self.assertIn(
                    action,
                    html_content,
                    f"Dashboard static HTML missing recommendation action '{action}' for symbol '{symbol}'",
                )

    def test_stock_detail_static_html_contains_symbol_data(self):
        rec_json_path = os.path.join(os.getcwd(), "public", "generated", "recommendations.json")
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

        # Select a real generated symbol dynamically
        target_rec = recommendations[0]
        symbol = target_rec.get("symbol")
        self.assertTrue(bool(symbol), "First recommendation does not contain a symbol.")

        stock_html_path = os.path.join(os.getcwd(), "dist", "client", "stock", symbol, "index.html")

        self.assertTrue(
            os.path.exists(stock_html_path),
            f"Build stock HTML missing: {stock_html_path}. Ensure route /stock/{symbol} is prerendered in vite.config.ts.",
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
            f"Stock detail HTML for '{symbol}' does not contain symbol string.",
        )


if __name__ == "__main__":
    unittest.main()
