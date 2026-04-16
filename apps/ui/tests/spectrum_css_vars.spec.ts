import { expect, test } from "@playwright/test";

import { installDocumentStub } from "./spectrum_test_support";

test.describe("spectrum_css_vars", () => {
  test("caches a plain spectrum css snapshot until refreshed", async () => {
    const restoreDocument = installDocumentStub();
    const styleValues: Record<string, string> = {
      "--surface": "#101820",
      "--muted": "#556677",
      "--border": "#c0ffee",
      "--tooltip-bg": "rgba(1, 2, 3, 0.9)",
      "--tooltip-fg": "#fefefe",
    };
    let readCount = 0;
    globalThis.getComputedStyle = (() => {
      readCount += 1;
      return {
        getPropertyValue(name: string): string {
          return styleValues[name] ?? "";
        },
      } as CSSStyleDeclaration;
    }) as typeof getComputedStyle;

    try {
      const { getSpectrumCssVars, refreshSpectrumCssVars } = await import(
        "../src/spectrum_css_vars"
      );

      const first = refreshSpectrumCssVars();
      expect(first).toEqual({
        surface: "#101820",
        muted: "#556677",
        border: "#c0ffee",
        tooltipBg: "rgba(1, 2, 3, 0.9)",
        tooltipFg: "#fefefe",
      });
      expect(readCount).toBe(1);

      styleValues["--surface"] = "#222222";
      expect(getSpectrumCssVars()).toBe(first);
      expect(getSpectrumCssVars().surface).toBe("#101820");
      expect(readCount).toBe(1);

      const refreshed = refreshSpectrumCssVars();
      expect(refreshed.surface).toBe("#222222");
      expect(refreshed).not.toBe(first);
      expect(getSpectrumCssVars()).toBe(refreshed);
      expect(readCount).toBe(2);
    } finally {
      restoreDocument();
    }
  });
});
