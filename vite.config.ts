import tailwindcss from "@tailwindcss/vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite-plus";

const base = process.env.BASE || process.env.BASE_URL || "/";

export function resolveGeneratedFilePath(
  urlPath: string,
  rootDir: string = process.cwd(),
): string | null {
  if (!urlPath) return null;

  const relativeUrl = urlPath.split("?")[0].split("#")[0];
  const match = relativeUrl.match(/\/?(?:.*\/)?(generated\/.*)$/);
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

function generatedDataPlugin() {
  return {
    name: "vite-plugin-generated-data",
    configureServer(server: import("vite-plus").ViteDevServer) {
      server.middlewares.use((req, res, next) => {
        if (req.url) {
          const filePath = resolveGeneratedFilePath(req.url);
          if (filePath) {
            res.setHeader("Content-Type", "application/json");
            res.end(fs.readFileSync(filePath));
            return;
          }
        }
        next();
      });
    },
    closeBundle() {
      const generatedSrc = path.join(process.cwd(), "generated");
      const clientOutDir = path.join(process.cwd(), "dist", "client", "generated");
      if (fs.existsSync(generatedSrc)) {
        fs.cpSync(generatedSrc, clientOutDir, { recursive: true });
      }
    },
  };
}

function getPrerenderStockSymbols(): string[] {
  const recPath = path.join(process.cwd(), "generated", "recommendations.json");
  if (!fs.existsSync(recPath)) {
    throw new Error(
      `[SSG Build Error] Canonical data artifact missing at '${recPath}'. ` +
        `Run python scripts/generate_report.py before building frontend.`,
    );
  }

  let data: any;
  try {
    const content = fs.readFileSync(recPath, "utf-8");
    data = JSON.parse(content);
  } catch (err) {
    throw new Error(`[SSG Build Error] Failed to parse '${recPath}': ${(err as Error).message}`);
  }

  if (!data || !Array.isArray(data.recommendations) || data.recommendations.length === 0) {
    throw new Error(`[SSG Build Error] Invalid or empty recommendations array in '${recPath}'.`);
  }

  const symbols: string[] = data.recommendations
    .map((r: { symbol?: string }) => r.symbol && r.symbol.trim())
    .filter((sym: string | undefined): sym is string => Boolean(sym));

  if (symbols.length === 0) {
    throw new Error(`[SSG Build Error] No valid non-empty stock symbols found in '${recPath}'.`);
  }

  return Array.from(new Set(symbols));
}

const prerenderStockSymbols = getPrerenderStockSymbols();

const prerenderPages = [
  { path: "/" },
  { path: "/history" },
  { path: "/methodology" },
  ...prerenderStockSymbols.map((sym) => ({ path: `/stock/${sym}` })),
];

const ignorePatterns = [
  "*.min.*",
  "*.map",
  "**/public",
  "**/build",
  "**/dist",
  "**/out",
  "**/.github",
  "**/.next",
  "**/.astro",
  "**/.netlify",
  "**/*.gen.*",
  "**/generated",
];

// https://viteplus.dev/config/
export default defineConfig({
  base,
  fmt: {
    ignorePatterns,
    sortImports: {
      groups: [
        "type-import",
        ["value-builtin", "value-external"],
        "type-internal",
        "value-internal",
        ["type-parent", "type-sibling", "type-index"],
        ["value-parent", "value-sibling", "value-index"],
        "unknown",
      ],
    },
    sortTailwindcss: {
      stylesheet: "./src/index.css",
      attributes: ["class", "className"],
      functions: ["clsx", "cn", "cva", "tv"],
    },
  },
  lint: {
    ignorePatterns,
    plugins: [
      "typescript",
      "unicorn",
      "react",
      "react-perf",
      "import",
      "jsx-a11y",
      "node",
      "promise",
      "vitest",
      "vue",
    ],
  },
  plugins: [
    tanstackStart({
      pages: prerenderPages,
      prerender: {
        enabled: true,
        pages: prerenderPages,
      },
    }),
    react(),
    tailwindcss(),
    generatedDataPlugin(),
  ],
  resolve: {
    tsconfigPaths: true,
  },
});
