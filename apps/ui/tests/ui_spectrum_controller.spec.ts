import type uPlot from "uplot";
import { expect, test } from "@playwright/test";

import { UiSpectrumController } from "../src/app/runtime/ui_spectrum_controller";
import { createAppState } from "../src/app/ui_app_state";
import type { UiDomElements } from "../src/app/ui_dom_registry";
import { installWindowGlobal } from "./async_test_helpers";

type ElementStub = HTMLElement & {
  children: ElementStub[];
  className: string;
  textContent: string;
  hidden: boolean;
  disabled: boolean;
  title: string;
  type: string;
  style: CSSStyleDeclaration;
  appendChild(child: ElementStub): ElementStub;
  insertBefore(child: ElementStub, before: ElementStub | null): ElementStub;
  remove(): void;
  addEventListener(type: string, handler: () => void): void;
  click(): void;
  getAttribute(name: string): string | null;
  setAttribute(name: string, value: string): void;
  innerHTML: string;
};

type ElementState = {
  parent: ElementStub | null;
  children: ElementStub[];
  attributes: Record<string, string>;
  styles: Record<string, string>;
  listeners: Record<string, Array<() => void>>;
};

function createElementStub(tagName = "div"): ElementStub {
  const state: ElementState = {
    parent: null,
    children: [],
    attributes: {},
    styles: {},
    listeners: {},
  };
  const element = {
    className: "",
    textContent: "",
    hidden: false,
    disabled: false,
    title: "",
    type: "",
    style: {
      setProperty(name: string, value: string): void {
        state.styles[name] = value;
      },
      getPropertyValue(name: string): string {
        return state.styles[name] ?? "";
      },
    } as unknown as CSSStyleDeclaration,
    get children(): ElementStub[] {
      return state.children;
    },
    appendChild(child: ElementStub): ElementStub {
      return this.insertBefore(child, null);
    },
    insertBefore(child: ElementStub, before: ElementStub | null): ElementStub {
      child.remove();
      childState.get(child)!.parent = element;
      const index = before ? state.children.indexOf(before) : -1;
      if (index >= 0) {
        state.children.splice(index, 0, child);
      } else {
        state.children.push(child);
      }
      return child;
    },
    remove(): void {
      if (!state.parent) return;
      const siblings = childState.get(state.parent)!.children;
      const index = siblings.indexOf(element);
      if (index >= 0) {
        siblings.splice(index, 1);
      }
      state.parent = null;
    },
    addEventListener(type: string, handler: () => void): void {
      state.listeners[type] ??= [];
      state.listeners[type].push(handler);
    },
    click(): void {
      for (const handler of state.listeners.click ?? []) {
        handler();
      }
    },
    getAttribute(name: string): string | null {
      return state.attributes[name] ?? null;
    },
    setAttribute(name: string, value: string): void {
      state.attributes[name] = value;
    },
    get innerHTML(): string {
      return "";
    },
    set innerHTML(value: string) {
      if (value !== "") {
        throw new Error("ElementStub only supports clearing innerHTML");
      }
      for (const child of [...state.children]) {
        child.remove();
      }
    },
  } as unknown as ElementStub;
  childState.set(element, state);
  void tagName;
  return element;
}

const childState = new WeakMap<ElementStub, ElementState>();

function installDocumentStub(): () => void {
  const originalDocument = globalThis.document;
  const originalGetComputedStyle = globalThis.getComputedStyle;
  (globalThis as { document?: Document }).document = {
    documentElement: {} as HTMLElement,
    createElement(tagName: string) {
      return createElementStub(tagName);
    },
  } as Document;
  globalThis.getComputedStyle = (() =>
    ({
      getPropertyValue: () => "",
    }) as CSSStyleDeclaration) as typeof getComputedStyle;
  return () => {
    (globalThis as { document?: Document }).document = originalDocument;
    globalThis.getComputedStyle = originalGetComputedStyle;
  };
}

test.describe("UiSpectrumController", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("reuses the same band plugin across repeated plugin reads", () => {
    const restoreDocument = installDocumentStub();
    try {
      const controller = new UiSpectrumController({
        state: createAppState(),
        els: {
          spectrumBandToggle: null,
        } as unknown as UiDomElements,
        t: (key) => key,
      });

      const internals = controller as unknown as {
        spectrumPlugins(): uPlot.Plugin[];
      };

      const [firstPlugin] = internals.spectrumPlugins();
      const [secondPlugin] = internals.spectrumPlugins();

      expect(firstPlugin).toBe(secondPlugin);
    } finally {
      restoreDocument();
    }
  });

  test("reuses legend buttons across live refreshes and click toggles", () => {
    const restoreDocument = installDocumentStub();
    try {
      const state = createAppState();
      state.transport.wsState = "connected";
      state.spectrum.spectra.clients = {
        "sensor-a": {
          freq: [10, 20],
          combined: [1, 0.8],
          strength_metrics: {
            noise_floor_amp_g: 0.1,
            peak_amp_g: 1,
            strength_bucket: null,
            top_peaks: [{
              amp: 1,
              hz: 10,
              strength_bucket: null,
              vibration_strength_db: 12,
            }],
            vibration_strength_db: 12,
          },
        },
        "sensor-b": {
          freq: [10, 20],
          combined: [0.6, 0.5],
          strength_metrics: {
            noise_floor_amp_g: 0.1,
            peak_amp_g: 0.6,
            strength_bucket: null,
            top_peaks: [{
              amp: 0.6,
              hz: 20,
              strength_bucket: null,
              vibration_strength_db: 8,
            }],
            vibration_strength_db: 8,
          },
        },
      };

      const legend = createElementStub("div");
      const inspector = createElementStub("div");
      const bandToggle = createElementStub("button");

      const controller = new UiSpectrumController({
        state,
        els: {
          legend,
          spectrumInspector: inspector,
          spectrumBandToggle: bandToggle,
        } as unknown as UiDomElements,
        t: (key, vars) => {
          if (key === "spectrum.legend.sensor_level") {
            return `Sensor level: ${String(vars?.value)} dB`;
          }
          return vars?.sensor ? `${key}:${String(vars.sensor)}` : key;
        },
      });

      const internals = controller as unknown as {
        currentEntries: Array<{ id: string; label: string; color: string; values: number[] }>;
        currentFreqAxis: number[];
        renderSensorLegend(entries: Array<{ id: string; label: string; color: string; values: number[] }>): void;
      };
      const entries = [
        { id: "sensor-a", label: "Front Right Wheel", color: "#ff5500", values: [12, 11] },
        { id: "sensor-b", label: "Rear Left Wheel", color: "#3366ff", values: [8, 7] },
      ];

      internals.currentEntries = entries;
      internals.currentFreqAxis = [10, 20];
      internals.renderSensorLegend(entries);

      const allButton = legend.children[0];
      const sensorButton = legend.children[1];
      const sensorMeta = sensorButton.children[1].children[1];
      expect(sensorMeta.textContent).toBe("Sensor level: 12.0 dB");

      sensorButton.click();
      expect(legend.children[0]).toBe(allButton);
      expect(legend.children[1]).toBe(sensorButton);
      expect(sensorButton.getAttribute("aria-pressed")).toBe("true");

      state.spectrum.spectra.clients["sensor-a"].strength_metrics.vibration_strength_db = 13;
      state.spectrum.spectra.clients["sensor-a"].strength_metrics.top_peaks[0].vibration_strength_db = 13;
      const refreshedEntries = [
        { ...entries[0], values: [13, 12] },
        entries[1],
      ];
      internals.currentEntries = refreshedEntries;
      internals.renderSensorLegend(refreshedEntries);

      expect(legend.children[0]).toBe(allButton);
      expect(legend.children[1]).toBe(sensorButton);
      expect(sensorMeta.textContent).toBe("Sensor level: 13.0 dB");
      expect(sensorButton.getAttribute("aria-pressed")).toBe("true");

      sensorButton.click();
      expect(legend.children[0]).toBe(allButton);
      expect(legend.children[1]).toBe(sensorButton);
      expect(sensorButton.getAttribute("aria-pressed")).toBe("false");
    } finally {
      restoreDocument();
    }
  });
});
