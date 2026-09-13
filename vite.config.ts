import tailwindcss from "@tailwindcss/vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";

const base = process.env.BASE || process.env.BASE_URL || "/";

function getPrerenderStockSymbols(): string[] {
  const defaultSymbols = ["ACB", "FPT", "VCB", "HPG", "MBB", "TCB", "VNM", "SSI", "VHM", "MWG"];

  try {
    const recPath = path.join(process.cwd(), "public", "generated", "recommendations.json");
    if (fs.existsSync(recPath)) {
      const content = fs.readFileSync(recPath, "utf-8");
      const data = JSON.parse(content);
      if (Array.isArray(data.recommendations)) {
        const symbols = data.recommendations
          .map((r: { symbol: string }) => r.symbol)
          .filter(Boolean);
        if (symbols.length > 0) {
          return Array.from(new Set([...symbols, ...defaultSymbols]));
        }
      }
    }
  } catch (err) {
    console.warn(
      "[vite.config] Could not dynamically load generated recommendations for SSG prerender:",
      err,
    );
  }

  return defaultSymbols;
}

const prerenderStockSymbols = getPrerenderStockSymbols();

const prerenderPages = [
  { path: "/" },
  { path: "/history" },
  { path: "/methodology" },
  ...prerenderStockSymbols.map((sym) => ({ path: `/stock/${sym}` })),
];

// https://vite.dev/config/
export default defineConfig({
  base,
  plugins: [
    tanstackStart({
      prerender: {
        enabled: true,
        pages: prerenderPages,
      },
    }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    tsconfigPaths: true,
  },
});
