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

        # 3. Must contain rendered quantitative fields for top recommendations displayed in cards
        recommendations = rec_data.get("recommendations", [])
        self.assertTrue(
            len(recommendations) > 0,
            "No recommendations found in public/generated/recommendations.json",
        )

        # Filter top Buys & Sells as rendered on Dashboard cards
        buy_list = [r for r in recommendations if r.get("action") in ("BUY", "WATCH")]
        sell_list = [r for r in recommendations if r.get("action") in ("SELL", "AVOID", "HOLD")]

        sorted_buys = sorted(
            buy_list,
            key=lambda x: (
                x.get("risk_adjusted_alpha")
                if x.get("risk_adjusted_alpha") is not None
                else (x.get("alpha_score") or 0)
            ),
            reverse=True,
        )
        sorted_sells = sorted(
            sell_list,
            key=lambda x: (
                x.get("risk_adjusted_alpha")
                if x.get("risk_adjusted_alpha") is not None
                else (x.get("alpha_score") or 0)
            ),
            reverse=True,
        )

        rendered_top_recs = sorted_buys[:4] + sorted_sells[:4]
        self.assertTrue(len(rendered_top_recs) > 0, "No top recommendations rendered.")

        for rec in rendered_top_recs[:3]:
            symbol = rec.get("symbol")
            action = rec.get("action")
            alpha_score = rec.get("alpha_score")
            risk_adj_alpha = rec.get("risk_adjusted_alpha")

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

            if alpha_score is not None:
                formatted_alpha = f"{alpha_score:.1f}"
                self.assertIn(
                    formatted_alpha,
                    html_content,
                    f"Dashboard static HTML missing formatted alpha_score '{formatted_alpha}' for '{symbol}'",
                )

            if risk_adj_alpha is not None:
                formatted_risk_adj = f"{risk_adj_alpha:.1f}"
                self.assertIn(
                    formatted_risk_adj,
                    html_content,
                    f"Dashboard static HTML missing formatted risk_adjusted_alpha '{formatted_risk_adj}' for '{symbol}'",
                )

    def test_stock_detail_static_html_for_all_prerendered_symbols(self):
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

        # Get list of stock symbols actually prerendered under dist/client/stock/
        stock_dir = os.path.join(os.getcwd(), "dist", "client", "stock")
        self.assertTrue(
            os.path.exists(stock_dir),
            f"Stock output directory missing: {stock_dir}. Run `pnpm build` first.",
        )

        prerendered_symbols = [
            d for d in os.listdir(stock_dir) if os.path.isdir(os.path.join(stock_dir, d))
        ]
        self.assertTrue(
            len(prerendered_symbols) > 0,
            "No prerendered stock directories found under dist/client/stock/",
        )

        rec_by_symbol = {r.get("symbol"): r for r in recommendations if r.get("symbol")}

        tested_count = 0
        for symbol in prerendered_symbols:
            rec = rec_by_symbol.get(symbol, {})
            stock_html_path = os.path.join(stock_dir, symbol, "index.html")

            self.assertTrue(
                os.path.exists(stock_html_path),
                f"Build stock HTML missing for symbol '{symbol}' at: {stock_html_path}.",
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

            # Must contain at least one quantitative value (alpha_score or risk_adjusted_alpha)
            alpha_score = rec.get("alpha_score")
            risk_adj_alpha = rec.get("risk_adjusted_alpha")
            if alpha_score is not None:
                self.assertIn(
                    f"{alpha_score:.1f}",
                    html_content,
                    f"Stock detail static HTML for '{symbol}' missing alpha_score.",
                )
            elif risk_adj_alpha is not None:
                self.assertIn(
                    f"{risk_adj_alpha:.1f}",
                    html_content,
                    f"Stock detail static HTML for '{symbol}' missing risk_adjusted_alpha.",
                )

            tested_count += 1

        self.assertTrue(tested_count > 0, "No stock detail static HTML pages were tested.")


if __name__ == "__main__":
    unittest.main()
