import { expect, test } from "@playwright/test";

import { createAppState } from "../src/app/ui_app_state";
import {
  bindUiShellFeatureEvents,
  type UiShellFeaturePorts,
} from "../src/app/runtime/ui_shell_feature_ports";
import {
  createUiShellLanguageRefreshModule,
  type UiShellLanguageRefreshFeaturePorts,
} from "../src/app/runtime/ui_shell_language_refresh_module";
import {
  DEFAULT_SHELL_VIEW_ID,
  createUiShellNavigationModule,
} from "../src/app/runtime/ui_shell_navigation_module";
import { createUiShellNotificationModule } from "../src/app/runtime/ui_shell_notification_module";
import { createUiShellPreferencesModule } from "../src/app/runtime/ui_shell_preferences_module";
import { createUiShellStatusModule } from "../src/app/runtime/ui_shell_status_module";
import { createUiShellViewVisibilityModule } from "../src/app/runtime/ui_shell_view_visibility_module";

function createView(id: string): HTMLElement {
  return {
    dataset: {},
    hidden: true,
    id,
  } as unknown as HTMLElement;
}

function createWrap(): HTMLElement {
  return {
    dataset: {},
  } as unknown as HTMLElement;
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

function requestUrl(input: string | URL | RequestInfo): string {
  return String(
    typeof input === "string" ? input : input instanceof URL ? input : input.url,
  );
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

function installShellDocument() {
  const originalDocument = (globalThis as { document?: Document }).document;
  const documentElement = { lang: "" } as HTMLElement;
  (globalThis as { document?: Document }).document = {
    documentElement,
    querySelectorAll() {
      throw new Error("language refresh should not sweep [data-i18n] nodes");
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
  test("setActiveView updates signal-backed state and falls back to dashboard", () => {
    const state = createAppState();
    let resizeCalls = 0;

    const module = createUiShellNavigationModule({
      shell: state.shell,
      viewIds: [DEFAULT_SHELL_VIEW_ID, "historyView"],
      onDashboardViewActivated: () => {
        resizeCalls += 1;
      },
    });

    module.setActiveView("historyView");
    expect(state.shell.activeViewId).toBe("historyView");
    expect(module.activeViewId.value).toBe("historyView");
    expect(resizeCalls).toBe(0);

    module.setActiveView("missingView");
    expect(state.shell.activeViewId).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(module.activeViewId.value).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(resizeCalls).toBe(1);
  });
});

test.describe("createUiShellViewVisibilityModule", () => {
  test("syncs section visibility from the active view signal", () => {
    const state = createAppState();
    const dashboardView = createView(DEFAULT_SHELL_VIEW_ID);
    const historyView = createView("historyView");
    const navigation = createUiShellNavigationModule({
      shell: state.shell,
      viewIds: [DEFAULT_SHELL_VIEW_ID, "historyView"],
    });
    const visibility = createUiShellViewVisibilityModule({
      activeViewId: navigation.activeViewId,
      views: [dashboardView, historyView],
    });

    expect(dashboardView.hidden).toBe(false);
    expect(historyView.hidden).toBe(true);

    navigation.setActiveView("historyView");
    expect(dashboardView.hidden).toBe(true);
    expect(historyView.hidden).toBe(false);

    visibility.dispose();
  });
});

test.describe("createUiShellPreferencesModule", () => {
  test.beforeEach(() => {
    (globalThis as { window?: Window & typeof globalThis }).window =
      globalThis as unknown as Window & typeof globalThis;
  });

  test("hydrates persisted language and speed unit from the server", async () => {
    const state = createAppState();
    const requests: string[] = [];
    const applyLanguageCalls: boolean[] = [];
    let renderSpeedReadoutCalls = 0;

    const module = createUiShellPreferencesModule({
      shell: state.shell,
      t: (key) => key,
      normalizeLanguage: (lang) => String(lang),
      applyLanguage: (forceReloadInsights = false) => {
        applyLanguageCalls.push(forceReloadInsights);
      },
      renderSpeedReadout: () => {
        renderSpeedReadoutCalls += 1;
      },
    });

    await withMockFetch(
      (async (input: string | URL | RequestInfo) => {
        const url = requestUrl(input);
        requests.push(url);
        if (url.endsWith("/api/settings/language")) {
          return jsonResponse({ language: "nl" });
        }
        if (url.endsWith("/api/settings/speed-unit")) {
          return jsonResponse({ speed_unit: "mps" });
        }
        throw new Error(`Unexpected request: ${url}`);
      }) as typeof fetch,
      async () => {
        await module.hydratePersistedPreferences();
      },
    );

    expect(requests).toEqual([
      "/api/settings/language",
      "/api/settings/speed-unit",
    ]);
    expect(state.shell.lang).toBe("nl");
    expect(state.shell.speedUnit).toBe("mps");
    expect(module.getSelectedLanguage()).toBe("nl");
    expect(module.getSelectedSpeedUnit()).toBe("mps");
    expect(applyLanguageCalls).toEqual([true]);
    expect(renderSpeedReadoutCalls).toBe(1);
  });

  test("keeps the pending language selection visible until the save resolves", async () => {
    const state = createAppState();
    const applyLanguageCalls: boolean[] = [];
    let resolveResponse: ((response: Response) => void) | null = null;

    const module = createUiShellPreferencesModule({
      shell: state.shell,
      t: (key) => key,
      normalizeLanguage: (lang) => String(lang),
      applyLanguage: (forceReloadInsights = false) => {
        applyLanguageCalls.push(forceReloadInsights);
      },
      renderSpeedReadout: () => undefined,
    });

    await withMockFetch(
      (async () =>
        new Promise<Response>((resolve) => {
          resolveResponse = resolve;
        })) as typeof fetch,
      async () => {
        const savePromise = module.saveLanguage("nl");
        expect(module.getSelectedLanguage()).toBe("nl");
        expect(state.shell.lang).toBe("en");
        resolveResponse?.(jsonResponse({ language: "nl" }));
        await savePromise;
      },
    );

    expect(state.shell.lang).toBe("nl");
    expect(module.getSelectedLanguage()).toBe("nl");
    expect(applyLanguageCalls).toEqual([true]);
  });

  test("save failure restores the previous speed unit and reports inline field feedback", async () => {
    const state = createAppState();

    const module = createUiShellPreferencesModule({
      shell: state.shell,
      t: testTranslation,
      normalizeLanguage: (lang) => String(lang),
      applyLanguage: () => undefined,
      renderSpeedReadout: () => undefined,
    });

    await withMockFetch(
      (async () => {
        throw new Error("save failed");
      }) as typeof fetch,
      async () => {
        await module.saveSpeedUnit("mps");
      },
    );

    expect(state.shell.speedUnit).toBe("kmh");
    expect(module.getSelectedSpeedUnit()).toBe("kmh");
    expect(module.getSpeedUnitFeedback()?.detail).toBe("save failed");
  });
});

test.describe("createUiShellNotificationModule", () => {
  test("shows and clears the shared error banner model", () => {
    let onChangedCalls = 0;
    let pendingHide: (() => void) | null = null;

    const module = createUiShellNotificationModule({
      onChanged: () => {
        onChangedCalls += 1;
      },
      window: {
        clearTimeout: () => undefined,
        setTimeout: ((callback: TimerHandler) => {
          pendingHide = callback as () => void;
          return 1 as unknown as ReturnType<typeof setTimeout>;
        }) as Window["setTimeout"],
      },
    });

    module.showError("save failed");
    expect(module.getBannerModel()).toEqual({
      hidden: false,
      text: "save failed",
      variant: "bad",
    });

    pendingHide?.();
    expect(module.getBannerModel()).toEqual({
      hidden: true,
      text: "",
      variant: null,
    });
    expect(onChangedCalls).toBe(2);
  });
});

test.describe("createUiShellStatusModule", () => {
  test("builds websocket badge state and degraded shell status without bootstrap wiring", () => {
    const state = createAppState();
    state.transport.wsState = "stale";
    const appShellWrap = createWrap();

    const module = createUiShellStatusModule({
      appShellWrap,
      realtime: state.realtime,
      renderLiveOverviewSpeed: () => undefined,
      settings: state.settings,
      shell: state.shell,
      t: testTranslation,
      transport: state.transport,
    });

    expect(module.getWsLinkState()).toEqual({
      text: "ws.stale",
      variant: "bad",
    });
    module.syncConnectionState();
    expect(appShellWrap.dataset.connectionState).toBe("degraded");
  });

  test("derives updated websocket badge state after transport mutations", () => {
    const state = createAppState();
    const module = createUiShellStatusModule({
      appShellWrap: createWrap(),
      realtime: state.realtime,
      renderLiveOverviewSpeed: () => undefined,
      settings: state.settings,
      shell: state.shell,
      t: testTranslation,
      transport: state.transport,
    });

    expect(module.getWsLinkState()).toEqual({
      text: "ws.connecting",
      variant: "muted",
    });

    state.transport.wsState = "stale";
    expect(module.getWsLinkState()).toEqual({
      text: "ws.stale",
      variant: "bad",
    });

    state.transport.payloadError = "bad frame";
    expect(module.getWsLinkState()).toEqual({
      text: "ws.payload_error_pill",
      variant: "bad",
    });
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
    let renderedSpeedText = "";

    const module = createUiShellStatusModule({
      appShellWrap: createWrap(),
      realtime: state.realtime,
      renderLiveOverviewSpeed: (text) => {
        renderedSpeedText = text;
      },
      settings: state.settings,
      shell: state.shell,
      t: testTranslation,
      transport: state.transport,
    });

    module.renderSpeedReadout();

    expect(renderedSpeedText).toContain("speed.override");
    expect(renderedSpeedText).toContain('"unit":"speed.unit.kmh"');
  });

  test("renders OBD2 when OBD2 is the resolved speed source", () => {
    const state = createAppState();
    state.realtime.speedMps = 22.5;
    state.settings.speedSource = "obd2";
    state.settings.resolvedSpeedSource = "obd2";
    state.shell.speedUnit = "kmh";
    let renderedSpeedText = "";

    const module = createUiShellStatusModule({
      appShellWrap: createWrap(),
      realtime: state.realtime,
      renderLiveOverviewSpeed: (text) => {
        renderedSpeedText = text;
      },
      settings: state.settings,
      shell: state.shell,
      t: testTranslation,
      transport: state.transport,
    });

    module.renderSpeedReadout();

    expect(renderedSpeedText).toContain("speed.obd2");
    expect(renderedSpeedText).toContain('"unit":"speed.unit.kmh"');
  });
});

test.describe("createUiShellLanguageRefreshModule", () => {
  test("applies the cross-feature language refresh sequence without a global i18n sweep", () => {
    const state = createAppState();
    state.shell.lang = "nl";
    state.realtime.locationCodes = ["front_left_wheel"];
    let destroyCalls = 0;
    state.spectrum.spectrumPlot = {
      destroy() {
        destroyCalls += 1;
      },
    } as unknown as NonNullable<typeof state.spectrum.spectrumPlot>;

    const documentHarness = installShellDocument();
    let renderSpeedReadoutCalls = 0;
    let renderWsStateCalls = 0;
    let renderSpectrumCalls = 0;
    let updateSpectrumOverlayCalls = 0;
    const portCalls: string[] = [];

    const module = createUiShellLanguageRefreshModule({
      state,
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

    const ports: UiShellLanguageRefreshFeaturePorts = {
      history: {
        reloadExpandedRunOnLanguageChange() {
          portCalls.push("reloadExpandedRunOnLanguageChange");
        },
        renderHistoryTable() {
          portCalls.push("renderHistoryTable");
        },
      },
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
      settings: {
        syncSettingsInputs() {
          portCalls.push("syncSettingsInputs");
        },
      },
    };

    try {
      module.applyLanguage(ports, true);
    } finally {
      documentHarness.restore();
    }

    expect(documentHarness.documentElement.lang).toBe("nl");
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

  test("skips spectrum rebuild and expanded-history reload when not needed", () => {
    const state = createAppState();
    state.realtime.locationCodes = ["rear_left_wheel"];
    const documentHarness = installShellDocument();
    let renderSpectrumCalls = 0;
    let updateSpectrumOverlayCalls = 0;
    const portCalls: string[] = [];

    const module = createUiShellLanguageRefreshModule({
      state,
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
        history: {
          reloadExpandedRunOnLanguageChange() {
            portCalls.push("reloadExpandedRunOnLanguageChange");
          },
          renderHistoryTable() {
            portCalls.push("renderHistoryTable");
          },
        },
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
        history: {
          reloadExpandedRunOnLanguageChange: () => undefined,
          renderHistoryTable: () => undefined,
        },
        realtime: {
          buildLocationOptions: () => [],
          maybeRenderSensorsSettingsList: () => undefined,
          renderLoggingStatus: () => undefined,
          renderStatus: () => undefined,
        },
        settings: {
          syncSettingsInputs: () => undefined,
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
