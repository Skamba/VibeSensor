import { expect, test } from "@playwright/test";

import { createAppState } from "../src/app/ui_app_state";
import type { UiDomElements } from "../src/app/ui_dom_registry";
import {
  createUiShellLanguageRefreshModule,
} from "../src/app/runtime/ui_shell_language_refresh_module";
import {
  DEFAULT_SHELL_VIEW_ID,
  createUiShellNavigationModule,
} from "../src/app/runtime/ui_shell_navigation_module";
import { createUiShellNotificationModule } from "../src/app/runtime/ui_shell_notification_module";
import { createUiShellPreferencesModule } from "../src/app/runtime/ui_shell_preferences_module";
import { createUiShellStatusModule } from "../src/app/runtime/ui_shell_status_module";

type ClassListStub = {
  toggle(name: string, force?: boolean): void;
  contains(name: string): boolean;
};

type EventStub = {
  key?: string;
  defaultPrevented: boolean;
  preventDefault(): void;
};

type SelectStub = HTMLSelectElement & {
  triggerChange(nextValue: string): void;
};

type ButtonStub = HTMLButtonElement & {
  triggerClick(): void;
  triggerKeydown(key: string): EventStub;
  focused: boolean;
  ariaSelected: string | null;
};

function createClassList(initial: string[] = []): ClassListStub {
  const active = new Set(initial);
  return {
    toggle(name: string, force?: boolean): void {
      if (typeof force === "boolean") {
        if (force) active.add(name);
        else active.delete(name);
        return;
      }
      if (active.has(name)) active.delete(name);
      else active.add(name);
    },
    contains(name: string): boolean {
      return active.has(name);
    },
  };
}

function triggerListener(
  listener: EventListenerOrEventListenerObject | undefined,
  event: EventStub,
): void {
  if (!listener) return;
  if (typeof listener === "function") {
    listener(event as unknown as Event);
    return;
  }
  listener.handleEvent(event as unknown as Event);
}

function createView(id: string): HTMLElement {
  return {
    id,
    hidden: true,
    classList: createClassList(),
  } as unknown as HTMLElement;
}

function createMenuButton(viewId: string): ButtonStub {
  let clickListener: EventListenerOrEventListenerObject | undefined;
  let keydownListener: EventListenerOrEventListenerObject | undefined;
  const button = {
    dataset: { view: viewId },
    tabIndex: -1,
    classList: createClassList(),
    focused: false,
    ariaSelected: null as string | null,
    addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
      if (type === "click") clickListener = listener;
      if (type === "keydown") keydownListener = listener;
    },
    setAttribute(name: string, value: string) {
      if (name === "aria-selected") {
        this.ariaSelected = value;
      }
    },
    focus() {
      this.focused = true;
    },
    triggerClick() {
      triggerListener(clickListener, {
        defaultPrevented: false,
        preventDefault() {
          this.defaultPrevented = true;
        },
      });
    },
    triggerKeydown(key: string) {
      const event: EventStub = {
        key,
        defaultPrevented: false,
        preventDefault() {
          this.defaultPrevented = true;
        },
      };
      triggerListener(keydownListener, event);
      return event;
    },
  } as unknown as ButtonStub;
  return button;
}

function createSelect(value: string): SelectStub {
  let changeListener: EventListenerOrEventListenerObject | undefined;
  const select = {
    value,
    addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
      if (type === "change") changeListener = listener;
    },
    triggerChange(nextValue: string) {
      this.value = nextValue;
      triggerListener(changeListener, {
        defaultPrevented: false,
        preventDefault() {
          this.defaultPrevented = true;
        },
      });
    },
  } as unknown as SelectStub;
  return select;
}

function createTextElement(): HTMLElement {
  return {
    textContent: "",
    className: "",
    hidden: false,
    classList: createClassList(),
  } as unknown as HTMLElement;
}

function createI18nElement(key: string): Element {
  return {
    textContent: "",
    getAttribute(name: string) {
      return name === "data-i18n" ? key : null;
    },
  } as unknown as Element;
}

function createShellDeps(overrides?: Partial<UiDomElements>): {
  els: UiDomElements;
  dashboardView: HTMLElement;
  historyView: HTMLElement;
  dashboardButton: ButtonStub;
  historyButton: ButtonStub;
  languageSelect: SelectStub;
  speedUnitSelect: SelectStub;
  speed: HTMLElement;
  linkState: HTMLElement;
  connectionBanner: HTMLElement;
  appErrorBanner: HTMLElement;
  carSelectionBanner: HTMLElement;
  appShellWrap: HTMLElement;
} {
  const dashboardView = createView(DEFAULT_SHELL_VIEW_ID);
  const historyView = createView("historyView");
  const dashboardButton = createMenuButton(DEFAULT_SHELL_VIEW_ID);
  const historyButton = createMenuButton("historyView");
  const languageSelect = createSelect("en");
  const speedUnitSelect = createSelect("kmh");
  const speed = createTextElement();
  const linkState = createTextElement();
  const connectionBanner = createTextElement();
  const appErrorBanner = createTextElement();
  const carSelectionBanner = createTextElement();
  const appShellWrap = createTextElement();

  const els = {
    menuButtons: [dashboardButton, historyButton],
    views: [dashboardView, historyView],
    languageSelect,
    speedUnitSelect,
    speed,
    linkState,
    connectionBanner,
    appErrorBanner,
    carSelectionBanner,
    appShellWrap,
    ...overrides,
  } as unknown as UiDomElements;

  return {
    els,
    dashboardView,
    historyView,
    dashboardButton,
    historyButton,
    languageSelect,
    speedUnitSelect,
    speed,
    linkState,
    connectionBanner,
    appErrorBanner,
    carSelectionBanner,
    appShellWrap,
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function testTranslation(key: string, vars?: Record<string, unknown>): string {
  return vars ? `${key}:${JSON.stringify(vars)}` : key;
}

function installShellDocument(elements: Element[]) {
  const originalDocument = (globalThis as { document?: Document }).document;
  const documentElement = { lang: "" } as HTMLElement;
  (globalThis as { document?: Document }).document = {
    documentElement,
    querySelectorAll(selector: string) {
      if (selector === "[data-i18n]") {
        return elements;
      }
      return [];
    },
  } as unknown as Document;
  return {
    documentElement,
    restore() {
      (globalThis as { document?: Document }).document = originalDocument;
    },
  };
}

test.describe("createUiShellNavigationModule", () => {
  test("setActiveView toggles views and falls back to dashboard", () => {
    const state = createAppState();
    const { els, dashboardView, historyView, dashboardButton, historyButton } = createShellDeps();
    let resizeCalls = 0;
    const module = createUiShellNavigationModule({
      shell: state.shell,
      els,
      onDashboardViewActivated: () => {
        resizeCalls += 1;
      },
    });

    module.setActiveView("historyView");
    expect(state.shell.activeViewId).toBe("historyView");
    expect(historyView.hidden).toBe(false);
    expect(dashboardView.hidden).toBe(true);
    expect(historyButton.classList.contains("active")).toBe(true);
    expect(historyButton.ariaSelected).toBe("true");
    expect(dashboardButton.tabIndex).toBe(-1);
    expect(resizeCalls).toBe(0);

    module.setActiveView("missingView");
    expect(state.shell.activeViewId).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(dashboardView.hidden).toBe(false);
    expect(dashboardButton.classList.contains("active")).toBe(true);
    expect(resizeCalls).toBe(1);
  });

  test("bindHandlers supports keyboard navigation", () => {
    const state = createAppState();
    const { els, historyButton } = createShellDeps();
    const module = createUiShellNavigationModule({ shell: state.shell, els });

    module.bindHandlers();
    const event = historyButton.triggerKeydown("ArrowLeft");

    expect(event.defaultPrevented).toBe(true);
    expect(state.shell.activeViewId).toBe(DEFAULT_SHELL_VIEW_ID);
  });
});

test.describe("createUiShellPreferencesModule", () => {
  test.beforeEach(() => {
    (globalThis as { window?: Window & typeof globalThis }).window = globalThis as unknown as Window &
      typeof globalThis;
  });

  test("hydrates persisted language and speed unit without shell navigation", async () => {
    const state = createAppState();
    const { els, speedUnitSelect } = createShellDeps();
    const originalFetch = globalThis.fetch;
    const requests: string[] = [];
    globalThis.fetch = (async (input: string | URL | RequestInfo) => {
      const url = String(typeof input === "string" ? input : input instanceof URL ? input : input.url);
      requests.push(url);
      if (url.endsWith("/api/settings/language")) {
        return jsonResponse({ language: "nl" });
      }
      if (url.endsWith("/api/settings/speed-unit")) {
        return jsonResponse({ speed_unit: "mps" });
      }
      throw new Error(`Unexpected request: ${url}`);
    }) as typeof fetch;

    const applyLanguageCalls: boolean[] = [];
    let renderSpeedReadoutCalls = 0;
    const module = createUiShellPreferencesModule({
      shell: state.shell,
      els,
      t: (key) => key,
      normalizeLanguage: (lang) => lang,
      applyLanguage: (forceReloadInsights = false) => {
        applyLanguageCalls.push(forceReloadInsights);
      },
      renderSpeedReadout: () => {
        renderSpeedReadoutCalls += 1;
      },
      showError: () => {},
    });

    try {
      await module.hydratePersistedPreferences();
    } finally {
      globalThis.fetch = originalFetch;
    }

    expect(requests).toEqual(["/api/settings/language", "/api/settings/speed-unit"]);
    expect(state.shell.lang).toBe("nl");
    expect(state.shell.speedUnit).toBe("mps");
    expect(speedUnitSelect.value).toBe("mps");
    expect(applyLanguageCalls).toEqual([true]);
    expect(renderSpeedReadoutCalls).toBe(1);
  });

  test("bindHandlers persists speed unit changes independently from navigation", async () => {
    const state = createAppState();
    const { els, speedUnitSelect } = createShellDeps();
    const originalFetch = globalThis.fetch;
    const requests: Array<{ url: string; method: string; body: string }> = [];
    globalThis.fetch = (async (input: string | URL | RequestInfo, init?: RequestInit) => {
      const url = String(typeof input === "string" ? input : input instanceof URL ? input : input.url);
      requests.push({
        url,
        method: init?.method ?? "GET",
        body: String(init?.body ?? ""),
      });
      return jsonResponse({ speed_unit: "mps" });
    }) as typeof fetch;

    let renderSpeedReadoutCalls = 0;
    const module = createUiShellPreferencesModule({
      shell: state.shell,
      els,
      t: (key) => key,
      normalizeLanguage: (lang) => lang,
      applyLanguage: () => {},
      renderSpeedReadout: () => {
        renderSpeedReadoutCalls += 1;
      },
      showError: () => {},
    });

    try {
      module.bindHandlers();
      speedUnitSelect.triggerChange("mps");
      await expect.poll(() => state.shell.speedUnit).toBe("mps");
      await expect.poll(() => renderSpeedReadoutCalls).toBe(1);
    } finally {
      globalThis.fetch = originalFetch;
    }

    expect(requests).toEqual([
      {
        url: "/api/settings/speed-unit",
        method: "PUT",
        body: JSON.stringify({ speed_unit: "mps" }),
      },
    ]);
    expect(state.shell.speedUnit).toBe("mps");
    expect(renderSpeedReadoutCalls).toBe(1);
  });

  test("save failure restores the previous value and reports via showError", async () => {
    const state = createAppState();
    const { els, speedUnitSelect } = createShellDeps();
    const originalFetch = globalThis.fetch;
    const errors: string[] = [];
    globalThis.fetch = (async () => {
      throw new Error("save failed");
    }) as typeof fetch;

    const module = createUiShellPreferencesModule({
      shell: state.shell,
      els,
      t: (key) => key,
      normalizeLanguage: (lang) => lang,
      applyLanguage: () => {},
      renderSpeedReadout: () => {},
      showError: (message) => {
        errors.push(message);
      },
    });

    try {
      module.bindHandlers();
      speedUnitSelect.triggerChange("mps");
      await expect.poll(() => errors).toEqual(["save failed"]);
    } finally {
      globalThis.fetch = originalFetch;
    }

    expect(state.shell.speedUnit).toBe("kmh");
    expect(speedUnitSelect.value).toBe("kmh");
  });
});

test.describe("createUiShellNotificationModule", () => {
  test("shows and clears the shared error banner", () => {
    const { els, appErrorBanner } = createShellDeps();
    const module = createUiShellNotificationModule({ els });

    module.showError("save failed");

    expect(appErrorBanner.hidden).toBe(false);
    expect(appErrorBanner.textContent).toBe("save failed");
    expect(appErrorBanner.className).toBe("connection-banner connection-banner--bad app-error-banner");

    module.clearError();

    expect(appErrorBanner.hidden).toBe(true);
    expect(appErrorBanner.textContent).toBe("");
    expect(appErrorBanner.className).toBe("connection-banner app-error-banner");
  });
});

test.describe("createUiShellStatusModule", () => {
  test("renders websocket state without bootstrap wiring", () => {
    const state = createAppState();
    state.transport.wsState = "stale";
    const { els, linkState, connectionBanner, appShellWrap } = createShellDeps();
    const module = createUiShellStatusModule({
      shell: state.shell,
      transport: state.transport,
      realtime: state.realtime,
      settings: state.settings,
      els,
      t: (key) => key,
      setPillState: (el, variant, text) => {
        if (!el) return;
        el.className = `pill pill--${variant}`;
        el.textContent = text;
      },
    });

    module.renderWsState();

    expect(linkState.className).toBe("pill pill--bad");
    expect(linkState.textContent).toBe("ws.stale");
    expect(connectionBanner.hidden).toBe(false);
    expect(connectionBanner.textContent).toBe("ws.banner.stale");
    expect(appShellWrap.classList.contains("wrap--stale")).toBe(true);
  });

  test("renders speed override and car-selection warning", () => {
    const state = createAppState();
    state.realtime.speedMps = 12;
    state.settings.speedSource = "manual";
    state.settings.manualSpeedKph = 43.2;
    state.shell.speedUnit = "kmh";
    state.settings.cars = [];
    state.settings.activeCarId = null;
    const { els, speed, carSelectionBanner } = createShellDeps();
    const module = createUiShellStatusModule({
      shell: state.shell,
      transport: state.transport,
      realtime: state.realtime,
      settings: state.settings,
      els,
      t: testTranslation,
      setPillState: () => {},
    });

    module.renderSpeedReadout();
    module.renderCarSelectionWarning();

    expect(speed.textContent).toContain("speed.override");
    expect(speed.textContent).toContain("\"unit\":\"speed.unit.kmh\"");
    expect(carSelectionBanner.hidden).toBe(false);
    expect(carSelectionBanner.textContent).toContain("header.no_car_selected");
  });
});

test.describe("createUiShellLanguageRefreshModule", () => {
  test("applies the cross-feature language refresh sequence", () => {
    const state = createAppState();
    state.shell.lang = "nl";
    state.shell.speedUnit = "mps";
    state.realtime.locationCodes = ["front_left_wheel"];
    state.realtime.sensorsSettingsSignature = "stale";
    let destroyCalls = 0;
    state.spectrum.spectrumPlot = {
      destroy() {
        destroyCalls += 1;
      },
    } as unknown as NonNullable<typeof state.spectrum.spectrumPlot>;

    const { els, languageSelect, speedUnitSelect } = createShellDeps();
    const documentHarness = installShellDocument([
      createI18nElement("header.title"),
      createI18nElement("nav.history"),
    ]);
    const i18nElements = documentHarness.documentElement
      ? ((globalThis as { document?: Document }).document?.querySelectorAll("[data-i18n]") ?? [])
      : [];

    let renderSpeedReadoutCalls = 0;
    let renderWsStateCalls = 0;
    let renderCarSelectionWarningCalls = 0;
    let renderSpectrumCalls = 0;
    let updateSpectrumOverlayCalls = 0;
    const portCalls: string[] = [];

    const module = createUiShellLanguageRefreshModule({
      state,
      els,
      t: testTranslation,
      renderSpeedReadout: () => {
        renderSpeedReadoutCalls += 1;
      },
      renderWsState: () => {
        renderWsStateCalls += 1;
      },
      renderCarSelectionWarning: () => {
        renderCarSelectionWarningCalls += 1;
      },
      renderSpectrum: () => {
        renderSpectrumCalls += 1;
      },
      updateSpectrumOverlay: () => {
        updateSpectrumOverlayCalls += 1;
      },
    });

    try {
      module.applyLanguage({
        realtime: {
          buildLocationOptions(codes) {
            portCalls.push("buildLocationOptions");
            return codes.map((code) => ({ code, label: `${code}-label` }));
          },
          maybeRenderSensorsSettingsList(force = false) {
            portCalls.push(`maybeRenderSensorsSettingsList:${String(force)}`);
          },
          renderLoggingStatus() {
            portCalls.push("renderLoggingStatus");
          },
        },
        history: {
          renderHistoryTable() {
            portCalls.push("renderHistoryTable");
          },
          reloadExpandedRunOnLanguageChange() {
            portCalls.push("reloadExpandedRunOnLanguageChange");
          },
        },
      }, true);
    } finally {
      documentHarness.restore();
    }

    expect(documentHarness.documentElement.lang).toBe("nl");
    expect(Array.from(i18nElements, (element) => element.textContent)).toEqual([
      "header.title",
      "nav.history",
    ]);
    expect(languageSelect.value).toBe("nl");
    expect(speedUnitSelect.value).toBe("mps");
    expect(state.realtime.locationOptions).toEqual([
      { code: "front_left_wheel", label: "front_left_wheel-label" },
    ]);
    expect(state.realtime.sensorsSettingsSignature).toBe("");
    expect(portCalls).toEqual([
      "buildLocationOptions",
      "maybeRenderSensorsSettingsList:true",
      "renderLoggingStatus",
      "renderHistoryTable",
      "reloadExpandedRunOnLanguageChange",
    ]);
    expect(renderSpeedReadoutCalls).toBe(1);
    expect(renderWsStateCalls).toBe(1);
    expect(renderCarSelectionWarningCalls).toBe(1);
    expect(destroyCalls).toBe(1);
    expect(state.spectrum.spectrumPlot).toBeNull();
    expect(renderSpectrumCalls).toBe(1);
    expect(updateSpectrumOverlayCalls).toBe(1);
  });

  test("skips spectrum rebuild and history reload when not needed", () => {
    const state = createAppState();
    state.shell.lang = "en";
    state.shell.speedUnit = "kmh";
    state.realtime.locationCodes = ["rear_left_wheel"];
    state.spectrum.spectrumPlot = null;

    const { els } = createShellDeps();
    const documentHarness = installShellDocument([createI18nElement("status.ready")]);

    let renderSpectrumCalls = 0;
    let updateSpectrumOverlayCalls = 0;
    const portCalls: string[] = [];

    const module = createUiShellLanguageRefreshModule({
      state,
      els,
      t: testTranslation,
      renderSpeedReadout: () => undefined,
      renderWsState: () => undefined,
      renderCarSelectionWarning: () => undefined,
      renderSpectrum: () => {
        renderSpectrumCalls += 1;
      },
      updateSpectrumOverlay: () => {
        updateSpectrumOverlayCalls += 1;
      },
    });

    try {
      module.applyLanguage({
        realtime: {
          buildLocationOptions(codes) {
            portCalls.push("buildLocationOptions");
            return codes.map((code) => ({ code, label: code }));
          },
          maybeRenderSensorsSettingsList(force = false) {
            portCalls.push(`maybeRenderSensorsSettingsList:${String(force)}`);
          },
          renderLoggingStatus() {
            portCalls.push("renderLoggingStatus");
          },
        },
        history: {
          renderHistoryTable() {
            portCalls.push("renderHistoryTable");
          },
          reloadExpandedRunOnLanguageChange() {
            portCalls.push("reloadExpandedRunOnLanguageChange");
          },
        },
      });
    } finally {
      documentHarness.restore();
    }

    expect(portCalls).toEqual([
      "buildLocationOptions",
      "maybeRenderSensorsSettingsList:true",
      "renderLoggingStatus",
      "renderHistoryTable",
    ]);
    expect(renderSpectrumCalls).toBe(0);
    expect(updateSpectrumOverlayCalls).toBe(1);
  });
});
