import { expect, test } from "@playwright/test";

import type { UiShellDom } from "../src/app/dom/shell_dom";
import { createAppState } from "../src/app/ui_app_state";
import {
  bindUiShellFeatureEvents,
  type UiShellFeaturePorts,
} from "../src/app/runtime/ui_shell_feature_ports";
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
  const button = {
    dataset: { view: viewId },
    tabIndex: -1,
    classList: createClassList(),
    focused: false,
    ariaSelected: null as string | null,
    setAttribute(name: string, value: string) {
      if (name === "aria-selected") {
        this.ariaSelected = value;
      }
    },
    focus() {
      this.focused = true;
    },
  } as unknown as ButtonStub;
  return button;
}

function createSelect(value: string): SelectStub {
  let changeListener: EventListenerOrEventListenerObject | undefined;
  const attributes = new Map<string, string>();
  const select = {
    value,
    options: [],
    addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
      if (type === "change") changeListener = listener;
    },
    setAttribute(name: string, nextValue: string) {
      attributes.set(name, nextValue);
    },
    removeAttribute(name: string) {
      attributes.delete(name);
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
  const attributes = new Map<string, string>();
  return {
    textContent: "",
    innerHTML: "",
    className: "",
    hidden: false,
    classList: createClassList(),
    setAttribute(name: string, value: string) {
      attributes.set(name, value);
    },
    removeAttribute(name: string) {
      attributes.delete(name);
    },
    getAttribute(name: string) {
      return attributes.get(name) ?? null;
    },
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

function createShellDeps(overrides?: Partial<UiShellDom>): {
  dom: UiShellDom;
  els: UiShellDom;
  dashboardView: HTMLElement;
  historyView: HTMLElement;
  dashboardButton: ButtonStub;
  historyButton: ButtonStub;
  languageSelect: SelectStub;
  languageFeedback: HTMLElement;
  speedUnitSelect: SelectStub;
  speedUnitFeedback: HTMLElement;
  linkState: HTMLElement;
  appErrorBanner: HTMLElement;
  appShellWrap: HTMLElement;
} {
  const dashboardView = createView(DEFAULT_SHELL_VIEW_ID);
  const historyView = createView("historyView");
  const dashboardButton = createMenuButton(DEFAULT_SHELL_VIEW_ID);
  const historyButton = createMenuButton("historyView");
  const languageSelect = createSelect("en");
  const languageFeedback = createTextElement();
  const speedUnitSelect = createSelect("kmh");
  const speedUnitFeedback = createTextElement();
  const linkState = createTextElement();
  const appErrorBanner = createTextElement();
  const appShellWrap = createTextElement();

  const dom = {
    menuButtons: [dashboardButton, historyButton],
    views: [dashboardView, historyView],
    languageSelect,
    languageFeedback,
    speedUnitSelect,
    speedUnitFeedback,
    linkState,
    appErrorBanner,
    appShellWrap,
    ...overrides,
  } as unknown as UiShellDom;

  return {
    dom,
    els: dom,
    dashboardView,
    historyView,
    dashboardButton,
    historyButton,
    languageSelect,
    languageFeedback,
    speedUnitSelect,
    speedUnitFeedback,
    linkState,
    appErrorBanner,
    appShellWrap,
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function requestUrl(input: string | URL | RequestInfo): string {
  return String(typeof input === "string" ? input : input instanceof URL ? input : input.url);
}

async function withMockFetch(
  mockFetch: typeof fetch,
  run: () => Promise<void>,
): Promise<void> {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = mockFetch;
  try {
    await run();
  } finally {
    globalThis.fetch = originalFetch;
  }
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
    const { els, dashboardView, historyView, dashboardButton, historyButton, appShellWrap } = createShellDeps();
    let resizeCalls = 0;
    const module = createUiShellNavigationModule({
      shell: state.shell,
      dom: els,
      onDashboardViewActivated: () => {
        resizeCalls += 1;
      },
    });

    module.setActiveView("historyView");
    expect(state.shell.activeViewId).toBe("historyView");
    expect(historyView.hidden).toBe(false);
    expect(dashboardView.hidden).toBe(true);
    expect(historyButton.ariaSelected).toBe("true");
    expect(dashboardButton.tabIndex).toBe(-1);
    expect(appShellWrap.getAttribute("data-active-view")).toBe("historyView");
    expect(resizeCalls).toBe(0);

    module.setActiveView("missingView");
    expect(state.shell.activeViewId).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(dashboardView.hidden).toBe(false);
    expect(dashboardButton.ariaSelected).toBe("true");
    expect(appShellWrap.getAttribute("data-active-view")).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(resizeCalls).toBe(1);
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
    const requests: string[] = [];

    const applyLanguageCalls: boolean[] = [];
    let renderSpeedReadoutCalls = 0;
    const module = createUiShellPreferencesModule({
      shell: state.shell,
      dom: els,
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

    await withMockFetch((async (input: string | URL | RequestInfo) => {
      const url = requestUrl(input);
      requests.push(url);
      if (url.endsWith("/api/settings/language")) {
        return jsonResponse({ language: "nl" });
      }
      if (url.endsWith("/api/settings/speed-unit")) {
        return jsonResponse({ speed_unit: "mps" });
      }
      throw new Error(`Unexpected request: ${url}`);
    }) as typeof fetch, async () => {
      await module.hydratePersistedPreferences();
    });

    expect(requests).toEqual(["/api/settings/language", "/api/settings/speed-unit"]);
    expect(state.shell.lang).toBe("nl");
    expect(state.shell.speedUnit).toBe("mps");
    expect(speedUnitSelect.value).toBe("mps");
    expect(applyLanguageCalls).toEqual([true]);
    expect(renderSpeedReadoutCalls).toBe(1);
  });

  test("saveLanguage persists the selected language independently from shell navigation", async () => {
    const state = createAppState();
    const { els, languageSelect } = createShellDeps();
    const requests: Array<{ url: string; method: string; body: string }> = [];

    const applyLanguageCalls: boolean[] = [];
    const module = createUiShellPreferencesModule({
      shell: state.shell,
      dom: els,
      t: (key) => key,
      normalizeLanguage: (lang) => lang,
      applyLanguage: (forceReloadInsights = false) => {
        applyLanguageCalls.push(forceReloadInsights);
      },
      renderSpeedReadout: () => {},
      showError: () => {},
    });

    await withMockFetch((async (input: string | URL | RequestInfo, init?: RequestInit) => {
      requests.push({
        url: requestUrl(input),
        method: init?.method ?? "GET",
        body: String(init?.body ?? ""),
      });
      return jsonResponse({ language: "nl" });
    }) as typeof fetch, async () => {
      await module.saveLanguage("nl");
    });

    expect(requests).toEqual([
      {
        url: "/api/settings/language",
        method: "PUT",
        body: JSON.stringify({ language: "nl" }),
      },
    ]);
    expect(state.shell.lang).toBe("nl");
    expect(languageSelect.value).toBe("nl");
    expect(applyLanguageCalls).toEqual([true]);
  });

  test("saveSpeedUnit persists speed unit changes independently from navigation", async () => {
    const state = createAppState();
    const { els, speedUnitSelect } = createShellDeps();
    const requests: Array<{ url: string; method: string; body: string }> = [];

    let renderSpeedReadoutCalls = 0;
    const module = createUiShellPreferencesModule({
      shell: state.shell,
      dom: els,
      t: (key) => key,
      normalizeLanguage: (lang) => lang,
      applyLanguage: () => {},
      renderSpeedReadout: () => {
        renderSpeedReadoutCalls += 1;
      },
      showError: () => {},
    });

    await withMockFetch((async (input: string | URL | RequestInfo, init?: RequestInit) => {
      requests.push({
        url: requestUrl(input),
        method: init?.method ?? "GET",
        body: String(init?.body ?? ""),
      });
      return jsonResponse({ speed_unit: "mps" });
    }) as typeof fetch, async () => {
      await module.saveSpeedUnit("mps");
    });

    expect(requests).toEqual([
      {
        url: "/api/settings/speed-unit",
        method: "PUT",
        body: JSON.stringify({ speed_unit: "mps" }),
      },
    ]);
    expect(state.shell.speedUnit).toBe("mps");
    expect(speedUnitSelect.value).toBe("mps");
    expect(renderSpeedReadoutCalls).toBe(1);
  });

  test("save failure restores the previous value and reports inline field feedback", async () => {
    const state = createAppState();
    const { els, speedUnitSelect, speedUnitFeedback } = createShellDeps();
    const errors: string[] = [];

    const module = createUiShellPreferencesModule({
      shell: state.shell,
      dom: els,
      t: (key) => key,
      normalizeLanguage: (lang) => lang,
      applyLanguage: () => {},
      renderSpeedReadout: () => {},
      showError: (message) => {
        errors.push(message);
      },
    });

    await withMockFetch((async () => {
      throw new Error("save failed");
    }) as typeof fetch, async () => {
      await module.saveSpeedUnit("mps");
    });

    expect(errors).toEqual([]);
    expect(state.shell.speedUnit).toBe("kmh");
    expect(speedUnitSelect.value).toBe("kmh");
    expect(speedUnitFeedback.hidden).toBe(false);
    expect(speedUnitFeedback.innerHTML).toContain("save failed");
  });
});

test.describe("createUiShellNotificationModule", () => {
  test("shows and clears the shared error banner", () => {
    const { els, appErrorBanner } = createShellDeps();
    const module = createUiShellNotificationModule({ dom: els });

    module.showError("save failed");

    expect(appErrorBanner.hidden).toBe(false);
    expect(appErrorBanner.textContent).toBe("save failed");
    expect(appErrorBanner.className).toBe("connection-banner app-error-banner");
    expect(appErrorBanner.getAttribute("data-variant")).toBe("bad");

    module.clearError();

    expect(appErrorBanner.hidden).toBe(true);
    expect(appErrorBanner.textContent).toBe("");
    expect(appErrorBanner.className).toBe("connection-banner app-error-banner");
    expect(appErrorBanner.getAttribute("data-variant")).toBeNull();
  });
});

test.describe("createUiShellStatusModule", () => {
  test("renders websocket state without bootstrap wiring", () => {
    const state = createAppState();
    state.transport.wsState = "stale";
    const { els, linkState, appShellWrap } = createShellDeps();
    const module = createUiShellStatusModule({
      shell: state.shell,
      transport: state.transport,
      realtime: state.realtime,
      settings: state.settings,
      dom: els,
      t: (key) => key,
      setPillState: (el, variant, text) => {
        if (!el) return;
        el.className = "pill";
        el.setAttribute("data-variant", variant);
        el.textContent = text;
      },
    });

    module.renderWsState();

    expect(linkState.className).toBe("pill");
    expect(linkState.getAttribute("data-variant")).toBe("bad");
    expect(linkState.textContent).toBe("ws.stale");
    expect(appShellWrap.getAttribute("data-connection-state")).toBe("degraded");
  });

  test("renders speed override after car bootstrap resolves", () => {
    const state = createAppState();
    state.realtime.speedMps = 12;
    state.settings.speedSource = "manual";
    state.settings.manualSpeedKph = 43.2;
    state.shell.speedUnit = "kmh";
    state.settings.carsLoaded = true;
    state.settings.cars = [];
    state.settings.activeCarId = null;
    const { els } = createShellDeps();
    let renderedSpeedText = "";
    const module = createUiShellStatusModule({
      shell: state.shell,
      transport: state.transport,
      realtime: state.realtime,
      settings: state.settings,
      dom: els,
      t: testTranslation,
      setPillState: () => {},
      renderLiveOverviewSpeed: (text) => {
        renderedSpeedText = text;
      },
    });

    module.renderSpeedReadout();

    expect(renderedSpeedText).toContain("speed.override");
    expect(renderedSpeedText).toContain("\"unit\":\"speed.unit.kmh\"");
  });

  test("renders OBD2 when OBD2 is the resolved speed source", () => {
    const state = createAppState();
    state.realtime.speedMps = 22.5;
    state.settings.speedSource = "obd2";
    state.settings.resolvedSpeedSource = "obd2";
    state.shell.speedUnit = "kmh";
    const { els } = createShellDeps();
    let renderedSpeedText = "";
    const module = createUiShellStatusModule({
      shell: state.shell,
      transport: state.transport,
      realtime: state.realtime,
      settings: state.settings,
      dom: els,
      t: testTranslation,
      setPillState: () => {},
      renderLiveOverviewSpeed: (text) => {
        renderedSpeedText = text;
      },
    });

    module.renderSpeedReadout();

    expect(renderedSpeedText).toContain("speed.obd2");
    expect(renderedSpeedText).toContain("\"unit\":\"speed.unit.kmh\"");
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
    let renderSpectrumCalls = 0;
    let updateSpectrumOverlayCalls = 0;
    const portCalls: string[] = [];

    const module = createUiShellLanguageRefreshModule({
      state,
      dom: els,
      t: testTranslation,
      renderSpeedReadout: () => {
        renderSpeedReadoutCalls += 1;
      },
      renderWsState: () => {
        renderWsStateCalls += 1;
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
          renderStatus() {
            portCalls.push("renderStatus");
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
        settings: {
          syncSettingsInputs() {
            portCalls.push("syncSettingsInputs");
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
      "syncSettingsInputs",
      "maybeRenderSensorsSettingsList:true",
      "renderLoggingStatus",
      "renderStatus",
      "renderHistoryTable",
      "reloadExpandedRunOnLanguageChange",
    ]);
    expect(renderSpeedReadoutCalls).toBe(1);
    expect(renderWsStateCalls).toBe(1);
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
      dom: els,
      t: testTranslation,
      renderSpeedReadout: () => undefined,
      renderWsState: () => undefined,
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
          renderStatus() {
            portCalls.push("renderStatus");
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
        settings: {
          syncSettingsInputs() {
            portCalls.push("syncSettingsInputs");
          },
        },
      });
    } finally {
      documentHarness.restore();
    }

    expect(portCalls).toEqual([
      "buildLocationOptions",
      "syncSettingsInputs",
      "maybeRenderSensorsSettingsList:true",
      "renderLoggingStatus",
      "renderStatus",
      "renderHistoryTable",
    ]);
    expect(renderSpectrumCalls).toBe(0);
    expect(updateSpectrumOverlayCalls).toBe(1);
  });
});

test.describe("bindUiShellFeatureEvents", () => {
  test("invokes the narrow shell binding hooks without needing an AppFeatureBundle", () => {
    const portCalls: string[] = [];
    const ports = {
      bindSettingsHandlers() {
        portCalls.push("bindSettingsHandlers");
      },
      bindCarWizardHandlers() {
        portCalls.push("bindCarWizardHandlers");
      },
      bindRealtimeHandlers() {
        portCalls.push("bindRealtimeHandlers");
      },
      bindHistoryHandlers() {
        portCalls.push("bindHistoryHandlers");
      },
      bindUpdateHandlers() {
        portCalls.push("bindUpdateHandlers");
      },
      bindEspFlashHandlers() {
        portCalls.push("bindEspFlashHandlers");
      },
      languageRefresh: {
        realtime: {
          buildLocationOptions: () => [],
          maybeRenderSensorsSettingsList: () => undefined,
          renderLoggingStatus: () => undefined,
          renderStatus: () => undefined,
        },
        history: {
          renderHistoryTable: () => undefined,
          reloadExpandedRunOnLanguageChange: () => undefined,
        },
      },
    } satisfies UiShellFeaturePorts;

    bindUiShellFeatureEvents(ports);

    expect(portCalls).toEqual([
      "bindSettingsHandlers",
      "bindCarWizardHandlers",
      "bindRealtimeHandlers",
      "bindHistoryHandlers",
      "bindUpdateHandlers",
      "bindEspFlashHandlers",
    ]);
  });
});
