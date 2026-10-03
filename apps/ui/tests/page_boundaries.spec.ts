import { expect, test } from "vitest";

// Each page under src/pages/<page>/ stands alone; share code through src/
// modules outside pages/.
const PAGE_SOURCES = import.meta.glob<string>("../src/pages/**/*.{ts,tsx}", {
  eager: true,
  import: "default",
  query: "?raw",
});
const SPECIFIER = /(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)["']([^"']+)["']/g;

function resolvePath(from: string, specifier: string): string {
  const parts = from.split("/").slice(0, -1);
  for (const part of specifier.split("/")) {
    if (part === "..") parts.pop();
    else if (part !== ".") parts.push(part);
  }
  return parts.join("/");
}

function pageOf(path: string): string | null {
  return /^\.\.\/src\/pages\/([^/]+)\//.exec(path)?.[1] ?? null;
}

function crossPageImports(file: string, source: string): string[] {
  const page = pageOf(file);
  return Array.from(source.matchAll(SPECIFIER), (match) => match[1]).filter(
    (specifier) => {
      if (!specifier.startsWith(".")) return false;
      const target = pageOf(resolvePath(file, specifier));
      return target !== null && target !== page;
    },
  );
}

test("the import scanner flags a cross-page import", () => {
  const source = [
    'import { a } from "../cars/cars_store";',
    'import type { B } from "./history_store";',
    'export { c } from "../../api/http";',
    'const lazy = () => import("../update/Update");',
  ].join("\n");
  expect(crossPageImports("../src/pages/history/History.tsx", source)).toEqual([
    "../cars/cars_store",
    "../update/Update",
  ]);
});

test("pages do not import other pages", () => {
  const files = Object.entries(PAGE_SOURCES);
  expect(files.length).toBeGreaterThan(0);
  const violations = files.flatMap(([file, source]) =>
    crossPageImports(file, source).map(
      (specifier) => `${file} -> ${specifier}`,
    ),
  );
  expect(violations).toEqual([]);
});
