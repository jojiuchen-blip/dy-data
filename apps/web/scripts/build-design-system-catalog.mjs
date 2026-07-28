import path from "node:path";
import {
  existsSync,
  lstatSync,
  readdirSync,
  rmdirSync,
  unlinkSync,
} from "node:fs";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { build } from "vite";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(webRoot, "..", "..");
const outDir = path.resolve(repoRoot, "docs", "design-system", "runtime-catalog");

const expectedOutDir = path.resolve(repoRoot, "docs", "design-system", "runtime-catalog");
if (outDir !== expectedOutDir) {
  throw new Error(`Refusing to clean unexpected catalog output: ${outDir}`);
}

function removeTree(target) {
  if (!existsSync(target)) return;
  if (lstatSync(target).isDirectory()) {
    for (const entry of readdirSync(target)) {
      removeTree(path.resolve(target, entry));
    }
    rmdirSync(target);
    return;
  }
  unlinkSync(target);
}

removeTree(outDir);

await build({
  configFile: false,
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  root: webRoot,
  publicDir: false,
  plugins: [react()],
  build: {
    assetsInlineLimit: 0,
    copyPublicDir: false,
    cssCodeSplit: false,
    emptyOutDir: true,
    lib: {
      entry: path.resolve(webRoot, "src", "design-system", "catalog-entry.tsx"),
      formats: ["iife"],
      fileName: () => "catalog.js",
      name: "DyDataDesignSystemCatalog",
    },
    outDir,
    rollupOptions: {
      output: {
        assetFileNames: (assetInfo) => assetInfo.name?.endsWith(".css")
          ? "catalog.css"
          : "assets/[name]-[hash][extname]",
      },
    },
  },
});

const catalogOutputs = new Set(["catalog.css", "catalog.js"]);
for (const entry of readdirSync(outDir)) {
  if (!catalogOutputs.has(entry)) {
    removeTree(path.resolve(outDir, entry));
  }
}
