import { describe, expect, test } from "vitest";
import { installDocumentStub } from "./spectrum_test_support";

describe("spectrum_css_vars", () => {
  test("refreshes spectrum colors when the theme changes", async () => {
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
    globalThis.getComputedStyle = (() => {
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

      styleValues["--surface"] = "#222222";
      expect(getSpectrumCssVars().surface).toBe("#101820");

      dispatchThemeChange();
      const refreshed = getSpectrumCssVars();
      expect(refreshed.surface).toBe("#222222");

      styleValues["--surface"] = "#444444";
      dispatchThemeChange();
      expect(getSpectrumCssVars().surface).toBe("#444444");
    } finally {
      restoreDocument();
    }
  });
});
