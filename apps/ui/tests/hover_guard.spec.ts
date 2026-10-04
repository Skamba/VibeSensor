import { expect, test } from "vitest";

// Touch screens keep :hover on the last tapped element (a tapped button stays
// highlighted), so every :hover rule must sit inside `@media (hover: hover)`.
const STYLESHEETS = import.meta.glob<string>("../src/**/*.css", {
  eager: true,
  import: "default",
  query: "?raw",
});
const HOVER_GUARD = /^@media\b[^{]*\(\s*hover\s*:\s*hover\s*\)/;

function unguardedHoverSelectors(css: string): string[] {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const guards: boolean[] = [];
  const found: string[] = [];
  let start = 0;
  for (let i = 0; i < source.length; i += 1) {
    const ch = source[i];
    if (ch === "{") {
      const prelude = source.slice(start, i).trim();
      if (
        !prelude.startsWith("@") &&
        prelude.includes(":hover") &&
        !guards.includes(true)
      ) {
        found.push(prelude.replace(/\s+/g, " "));
      }
      guards.push(HOVER_GUARD.test(prelude));
      start = i + 1;
    } else if (ch === "}") {
      guards.pop();
      start = i + 1;
    } else if (ch === ";") {
      start = i + 1;
    }
  }
  return found;
}

test("the scanner flags :hover rules outside a hover media guard", () => {
  const css = [
    "/* a:hover { } */",
    ".a:hover { color: red; }",
    "@media (max-width: 720px) { .b:hover td { color: red; } }",
    "@media (hover: hover) { .c:hover { color: red; } }",
    "@media (max-width: 720px) { @media (hover: hover) { .d:hover { x: y; } } }",
    ".e { color: red; }",
  ].join("\n");

  expect(unguardedHoverSelectors(css)).toEqual([".a:hover", ".b:hover td"]);
});

test("every :hover rule applies only where a pointer can hover", () => {
  expect(Object.keys(STYLESHEETS).length).toBeGreaterThan(0);
  const unguarded = Object.entries(STYLESHEETS).flatMap(([file, css]) =>
    unguardedHoverSelectors(css).map((selector) => `${file}: ${selector}`),
  );

  expect(unguarded).toEqual([]);
});
