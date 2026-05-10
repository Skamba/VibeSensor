import { describe, expect, test } from "vitest";
import { installDocumentStub } from "./spectrum_test_support";

describe("spectrum_css_vars", () => {
  test("reuses the cached spectrum css snapshot until values actually change", async () => {
    const restoreDocument = installDocumentStub();
    const styleValues: Record<string, string> = {
      "--surface": "#101820",
      "--muted": "#556677",
      "--border": "#c0ffee",
      "--tooltip-bg": "rgba(1, 2, 3, 0.9)",
      "--tooltip-fg": "#fefefe",
    };
    let themeChangeHandler: ((event: MediaQueryListEvent) => void) | null =
      null;
    let readCount = 0;
    globalThis.getComputedStyle = (() => {
      readCount += 1;
      return {
        getPropertyValue(name: string): string {
          return styleValues[name] ?? "";
        },
      } as unknown as CSSStyleDeclaration;
    }) as typeof getComputedStyle;
    globalThis.matchMedia = (() => ({
      matches: false,
      media: "(prefers-color-scheme: dark)",
      onchange: null,
      addEventListener: (
        _type: string,
        handler: (event: MediaQueryListEvent) => void,
      ) => {
        themeChangeHandler = handler;
      },
      removeEventListener: () => undefined,
      addListener: () => {
        throw new Error(
          "Deprecated MediaQueryList.addListener should not be used",
        );
      },
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })) as typeof matchMedia;

    try {
      const { getSpectrumCssVars } = await import("../src/spectrum_css_vars");
      const dispatchThemeChange = (): void => {
        const handler = themeChangeHandler;
        if (!handler) {
          throw new Error("theme change handler was not registered");
        }
        handler({
          matches: true,
          media: "(prefers-color-scheme: dark)",
        } as MediaQueryListEvent);
      };

      const first = getSpectrumCssVars();
      expect(first).toEqual({
        surface: "#101820",
        muted: "#556677",
        border: "#c0ffee",
        tooltipBg: "rgba(1, 2, 3, 0.9)",
        tooltipFg: "#fefefe",
      });
      expect(readCount).toBe(1);

      dispatchThemeChange();
      const unchangedRefresh = getSpectrumCssVars();
      expect(unchangedRefresh).toBe(first);
      expect(readCount).toBe(2);

      styleValues["--surface"] = "#222222";
      expect(getSpectrumCssVars()).toBe(first);
      expect(getSpectrumCssVars().surface).toBe("#101820");
      expect(readCount).toBe(2);

      dispatchThemeChange();
      const refreshed = getSpectrumCssVars();
      expect(refreshed.surface).toBe("#222222");
      expect(refreshed).not.toBe(first);
      expect(getSpectrumCssVars()).toBe(refreshed);
      expect(readCount).toBe(3);

      dispatchThemeChange();
      const unchangedThemeRefresh = getSpectrumCssVars();
      expect(unchangedThemeRefresh).toBe(refreshed);
      expect(readCount).toBe(4);

      styleValues["--surface"] = "#444444";
      dispatchThemeChange();
      const autoRefreshed = getSpectrumCssVars();
      expect(autoRefreshed.surface).toBe("#444444");
      expect(autoRefreshed).not.toBe(refreshed);
      expect(readCount).toBe(5);
    } finally {
      restoreDocument();
    }
  });
});
