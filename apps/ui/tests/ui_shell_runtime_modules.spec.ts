import { beforeEach, describe, expect, test } from "vitest";
import { HttpResponse, http, uiTestUrl } from "./msw/http";
import { createUiMswTestServer } from "./msw/node";
import { createAppState } from "../src/app/ui_app_state";
import { UiShellController } from "../src/app/runtime/ui_shell_controller";
import {
  DEFAULT_UI_SHELL_CHROME_ACTIONS,
  type UiShellChromeActions,
  type UiShellChromeDialogModel,
  type UiShellChromeNavigationModel,
  type UiShellChromePreferencesModel,
  type UiShellChromeStatusModel,
} from "../src/app/runtime/ui_shell_chrome";
import {
  DEFAULT_SHELL_VIEW_ID,
  createUiShellNavigationModule,
} from "../src/app/runtime/ui_shell_navigation_module";
import { createUiShellNotificationModule } from "../src/app/runtime/ui_shell_notification_module";
import { createUiShellPreferencesModule } from "../src/app/runtime/ui_shell_preferences_module";
import { createUiShellStatusModule } from "../src/app/runtime/ui_shell_status_module";
import { signal, type ReadonlySignal } from "../src/app/ui_signals";
import { installDocumentStub } from "./spectrum_test_support";
import { createTestQueryClient } from "./query_client_test_support";

const mswServer = createUiMswTestServer();

function testTranslation(key: string, vars?: Record<string, unknown>): string {
  return vars ? `${key}:${JSON.stringify(vars)}` : key;
}

function installWindowStub(): void {
  (globalThis as { window?: Window & typeof globalThis }).window = {
    clearTimeout: () => undefined,
    setTimeout: (() =>
      1 as unknown as ReturnType<typeof setTimeout>) as Window["setTimeout"],
  } as unknown as Window & typeof globalThis;
}

function createChromeViewHarness() {
  const models: {
    dialog: ReadonlySignal<UiShellChromeDialogModel> | null;
    navigation: ReadonlySignal<UiShellChromeNavigationModel> | null;
    preferences: ReadonlySignal<UiShellChromePreferencesModel> | null;
    status: ReadonlySignal<UiShellChromeStatusModel> | null;
  } = {
    dialog: null,
    navigation: null,
    preferences: null,
    status: null,
  };

  return {
    models,
    view: {
      bindDialogModel(model: ReadonlySignal<UiShellChromeDialogModel>) {
        models.dialog = model;
      },
      bindNavigationModel(model: ReadonlySignal<UiShellChromeNavigationModel>) {
        models.navigation = model;
      },
      bindPreferencesModel(
        model: ReadonlySignal<UiShellChromePreferencesModel>,
      ) {
        models.preferences = model;
      },
      bindStatusModel(model: ReadonlySignal<UiShellChromeStatusModel>) {
        models.status = model;
      },
    },
  };
}

describe("createUiShellNavigationModule", () => {
  test("setActiveView updates signal-backed state and falls back to dashboard", () => {
    const state = createAppState();
    const activatedViews: string[] = [];
    let resizeCalls = 0;

    const module = createUiShellNavigationModule({
      shell: state.shell,
      viewIds: [DEFAULT_SHELL_VIEW_ID, "historyView"],
      onViewActivated: (viewId) => {
        activatedViews.push(viewId);
      },
      onDashboardViewActivated: () => {
        resizeCalls += 1;
      },
    });

    module.setActiveView("historyView");
    expect(state.shell.activeViewId.value).toBe("historyView");
    expect(module.activeViewId.value).toBe("historyView");
    expect(activatedViews).toEqual(["historyView"]);
    expect(resizeCalls).toBe(0);

    module.setActiveView("missingView");
    expect(state.shell.activeViewId.value).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(module.activeViewId.value).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(activatedViews).toEqual(["historyView"]);
    expect(resizeCalls).toBe(1);
  });

  test("waits for async lazy-view activation before switching views", async () => {
    const state = createAppState();
    let resolveActivation: () => void = () => {
      throw new Error("activation promise was not created");
    };

    const module = createUiShellNavigationModule({
      shell: state.shell,
      viewIds: [DEFAULT_SHELL_VIEW_ID, "settingsView"],
      onViewActivated: (viewId) =>
        viewId === "settingsView"
          ? new Promise<void>((resolve) => {
              resolveActivation = resolve;
            })
          : undefined,
    });

    module.setActiveView("settingsView");
    expect(state.shell.activeViewId.value).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(module.activeViewId.value).toBe(DEFAULT_SHELL_VIEW_ID);

    resolveActivation();
    await Promise.resolve();

    expect(state.shell.activeViewId.value).toBe("settingsView");
    expect(module.activeViewId.value).toBe("settingsView");
  });

  test("keeps the current view when lazy activation fails", async () => {
    const state = createAppState();
    const activationErrors: string[] = [];

    const module = createUiShellNavigationModule({
      shell: state.shell,
      viewIds: [DEFAULT_SHELL_VIEW_ID, "settingsView"],
      onViewActivated: async () => {
        throw new Error("chunk failed");
      },
      onViewActivationFailed: (viewId, error) => {
        activationErrors.push(
          `${viewId}:${error instanceof Error ? error.message : String(error)}`,
        );
      },
    });

    module.setActiveView("settingsView");
    await Promise.resolve();
    await Promise.resolve();

    expect(state.shell.activeViewId.value).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(module.activeViewId.value).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(activationErrors).toEqual(["settingsView:chunk failed"]);
  });
});

describe("UiShellController", () => {
  beforeEach(() => {
    installWindowStub();
  });

  test("publishes live shell actions through the provided signal", () => {
    const state = createAppState();
    const chrome = createChromeViewHarness();
    const chromeActions = signal<UiShellChromeActions>({
      ...DEFAULT_UI_SHELL_CHROME_ACTIONS,
    });
    new UiShellController({
      bindFeatureHandlers: () => undefined,
      chrome: chrome.view,
      chromeActions,
      liveOverview: {
        model: signal(null),
        speedText: signal<ReadonlySignal<string> | null>(null),
      },
      queryClient: createTestQueryClient(),
      state,
    });

    chromeActions.value.activateView("historyView");
    expect(state.shell.activeViewId.value).toBe("historyView");
  });

  test("binds live overview speed text to the shell status signal", () => {
    const state = createAppState();
    const chrome = createChromeViewHarness();
    const liveOverview = {
      model: signal(null),
      speedText: signal<ReadonlySignal<string> | null>(null),
    };

    state.realtime.speedMps.value = 12.3;
    new UiShellController({
      bindFeatureHandlers: () => undefined,
      chrome: chrome.view,
      chromeActions: signal<UiShellChromeActions>({
        ...DEFAULT_UI_SHELL_CHROME_ACTIONS,
      }),
      liveOverview,
      queryClient: createTestQueryClient(),
      state,
    });

    const speedText = liveOverview.speedText.value;
    expect(speedText).not.toBeNull();
    expect(speedText?.value).toBe("44.3 km/h · GPS");

    state.shell.speedUnit.value = "mps";
    expect(liveOverview.speedText.value).toBe(speedText);
    expect(speedText?.value).toBe("12.3 m/s · GPS");

    state.settings.speed.resolvedSource.value = "obd2";
    expect(speedText?.value).toBe("12.3 m/s · OBD2");
  });

  test("syncs the document language from shell state without a chrome component", () => {
    const restoreDocument = installDocumentStub();
    const state = createAppState();
    const chrome = createChromeViewHarness();
    try {
      new UiShellController({
        bindFeatureHandlers: () => undefined,
        chrome: chrome.view,
        chromeActions: signal<UiShellChromeActions>({
          ...DEFAULT_UI_SHELL_CHROME_ACTIONS,
        }),
        liveOverview: {
          model: signal(null),
          speedText: signal<ReadonlySignal<string> | null>(null),
        },
        queryClient: createTestQueryClient(),
        state,
      });

      expect(globalThis.document.documentElement.lang).toBe("en");

      state.shell.lang.value = "nl";

      expect(globalThis.document.documentElement.lang).toBe("nl");
    } finally {
      restoreDocument();
    }
  });

  test("publishes live status updates to the shell status model", () => {
    const state = createAppState();
    const chrome = createChromeViewHarness();
    const controller = new UiShellController({
      bindFeatureHandlers: () => undefined,
      chrome: chrome.view,
      chromeActions: signal<UiShellChromeActions>({
        ...DEFAULT_UI_SHELL_CHROME_ACTIONS,
      }),
      liveOverview: {
        model: signal(null),
        speedText: signal<ReadonlySignal<string> | null>(null),
      },
      queryClient: createTestQueryClient(),
      state,
    });

    expect(chrome.models.status?.value.shellLiveStatus).toEqual({
      text: "No live signal",
      variant: "muted",
    });
    expect(chrome.models.dialog?.value.appErrorBanner).toEqual({
      hidden: true,
      text: "",
      variant: null,
    });

    controller.setLiveStatus("warn", "Signal weak");

    expect(chrome.models.status?.value.shellLiveStatus).toEqual({
      text: "Signal weak",
      variant: "warn",
    });
    expect(chrome.models.dialog?.value.appErrorBanner).toEqual({
      hidden: true,
      text: "",
      variant: null,
    });
  });

  test("publishes controller errors to the shared banner model", () => {
    const state = createAppState();
    const chrome = createChromeViewHarness();
    const controller = new UiShellController({
      bindFeatureHandlers: () => undefined,
      chrome: chrome.view,
      chromeActions: signal<UiShellChromeActions>({
        ...DEFAULT_UI_SHELL_CHROME_ACTIONS,
      }),
      liveOverview: {
        model: signal(null),
        speedText: signal<ReadonlySignal<string> | null>(null),
      },
      queryClient: createTestQueryClient(),
      state,
    });

    expect(chrome.models.dialog?.value.appErrorBanner).toEqual({
      hidden: true,
      text: "",
      variant: null,
    });
    expect(chrome.models.status?.value.shellLiveStatus).toEqual({
      text: "No live signal",
      variant: "muted",
    });

    controller.showError("save failed");

    expect(chrome.models.dialog?.value.appErrorBanner).toEqual({
      hidden: false,
      text: "save failed",
      variant: "bad",
    });
    expect(chrome.models.status?.value.shellLiveStatus).toEqual({
      text: "No live signal",
      variant: "muted",
    });
  });
});

describe("createUiShellPreferencesModule", () => {
  beforeEach(() => {
    (globalThis as { window?: Window & typeof globalThis }).window =
      globalThis as unknown as Window & typeof globalThis;
  });

  test("hydrates persisted language and speed unit from the server", async () => {
    const state = createAppState();
    const requests: string[] = [];
    const preparedLanguages: string[] = [];

    const module = createUiShellPreferencesModule({
      queryClient: createTestQueryClient(),
      shell: state.shell,
      t: (key) => key,
      normalizeLanguage: (lang) => String(lang),
      prepareLanguage: async (lang) => {
        preparedLanguages.push(lang);
      },
    });

    mswServer.use(
      http.get(uiTestUrl("/api/settings/language"), ({ request }) => {
        requests.push(new URL(request.url).pathname);
        return HttpResponse.json({ language: "nl" });
      }),
      http.get(uiTestUrl("/api/settings/speed-unit"), ({ request }) => {
        requests.push(new URL(request.url).pathname);
        return HttpResponse.json({ speed_unit: "mps" });
      }),
    );

    await module.hydratePersistedPreferences();

    expect(requests).toEqual([
      "/api/settings/language",
      "/api/settings/speed-unit",
    ]);
    expect(preparedLanguages).toEqual(["nl"]);
    expect(state.shell.lang.value).toBe("nl");
    expect(state.shell.speedUnit.value).toBe("mps");
    expect(module.selectedLanguage.value).toBe("nl");
    expect(module.selectedSpeedUnit.value).toBe("mps");
  });

  test("keeps the pending language selection visible until the save resolves", async () => {
    const state = createAppState();
    let resolveResponse: ((response: Response) => void) | undefined;
    const preparedLanguages: string[] = [];

    const module = createUiShellPreferencesModule({
      queryClient: createTestQueryClient(),
      shell: state.shell,
      t: (key) => key,
      normalizeLanguage: (lang) => String(lang),
      prepareLanguage: async (lang) => {
        preparedLanguages.push(lang);
      },
    });

    mswServer.use(
      http.put(uiTestUrl("/api/settings/language"), () => {
        return new Promise<Response>((resolve) => {
          resolveResponse = resolve;
        });
      }),
    );

    const savePromise = module.saveLanguage("nl");
    expect(module.selectedLanguage.value).toBe("nl");
    expect(state.shell.lang.value).toBe("en");
    await expect.poll(() => typeof resolveResponse).toBe("function");
    if (!resolveResponse) {
      throw new Error("language response resolver was not created");
    }
    resolveResponse(HttpResponse.json({ language: "nl" }));
    await savePromise;

    expect(preparedLanguages).toEqual(["nl"]);
    expect(state.shell.lang.value).toBe("nl");
    expect(module.selectedLanguage.value).toBe("nl");
  });

  test("save failure restores the previous speed unit and reports inline field feedback", async () => {
    const state = createAppState();

    const module = createUiShellPreferencesModule({
      queryClient: createTestQueryClient(),
      shell: state.shell,
      t: testTranslation,
      normalizeLanguage: (lang) => String(lang),
      prepareLanguage: async () => undefined,
    });

    mswServer.use(
      http.put(uiTestUrl("/api/settings/speed-unit"), () =>
        HttpResponse.json({ detail: "save failed" }, { status: 500 }),
      ),
    );

    await module.saveSpeedUnit("mps");

    expect(state.shell.speedUnit.value).toBe("kmh");
    expect(module.selectedSpeedUnit.value).toBe("kmh");
    expect(module.speedUnitFeedback.value?.detail).toBe("save failed");
  });
});

describe("createUiShellNotificationModule", () => {
  test("shows and clears the shared error banner model signal", () => {
    let pendingHide: () => void = () => {
      throw new Error("hide timer was not scheduled");
    };

    const module = createUiShellNotificationModule({
      window: {
        clearTimeout: () => undefined,
        setTimeout: ((callback: TimerHandler) => {
          pendingHide = callback as () => void;
          return 1 as unknown as ReturnType<typeof setTimeout>;
        }) as Window["setTimeout"],
      },
    });

    module.showError("save failed");
    expect(module.bannerModel.value).toEqual({
      hidden: false,
      text: "save failed",
      variant: "bad",
    });

    pendingHide();
    expect(module.bannerModel.value).toEqual({
      hidden: true,
      text: "",
      variant: null,
    });
  });
});

describe("createUiShellStatusModule", () => {
  test("builds websocket badge state and degraded shell status signals without bootstrap wiring", () => {
    const state = createAppState();
    state.transport.wsState.value = "stale";

    const module = createUiShellStatusModule({
      realtime: state.realtime,
      settings: state.settings,
      shell: state.shell,
      t: testTranslation,
      transport: state.transport,
    });

    expect(module.wsLinkState.value).toEqual({
      text: "ws.stale",
      variant: "bad",
    });
    expect(module.connectionState.value).toBe("degraded");
  });

  test("derives updated websocket badge state after transport mutations", () => {
    const state = createAppState();
    const module = createUiShellStatusModule({
      realtime: state.realtime,
      settings: state.settings,
      shell: state.shell,
      t: testTranslation,
      transport: state.transport,
    });

    expect(module.wsLinkState.value).toEqual({
      text: "ws.connecting",
      variant: "muted",
    });

    state.transport.wsState.value = "stale";
    expect(module.wsLinkState.value).toEqual({
      text: "ws.stale",
      variant: "bad",
    });

    state.transport.payloadError.value = "bad frame";
    expect(module.wsLinkState.value).toEqual({
      text: "ws.payload_error_pill",
      variant: "bad",
    });
  });

  test("recomputes websocket badge copy when the shell language changes", () => {
    const state = createAppState();
    const module = createUiShellStatusModule({
      realtime: state.realtime,
      settings: state.settings,
      shell: state.shell,
      t: (key) => `${state.shell.lang.value}:${key}`,
      transport: state.transport,
    });

    expect(module.wsLinkState.value).toEqual({
      text: "en:ws.connecting",
      variant: "muted",
    });

    state.shell.lang.value = "nl";

    expect(module.wsLinkState.value).toEqual({
      text: "nl:ws.connecting",
      variant: "muted",
    });
  });

  test("renders speed override after car bootstrap resolves", () => {
    const state = createAppState();
    state.realtime.speedMps.value = 12;
    state.settings.speed.source.value = "manual";
    state.settings.speed.manualSpeedKph.value = 43.2;
    state.shell.speedUnit.value = "kmh";
    state.settings.car.carsLoaded.value = true;
    state.settings.car.cars.value = [];
    state.settings.car.activeCarId.value = null;

    const module = createUiShellStatusModule({
      realtime: state.realtime,
      settings: state.settings,
      shell: state.shell,
      t: testTranslation,
      transport: state.transport,
    });

    expect(module.speedReadoutText.value).toContain("speed.override");
    expect(module.speedReadoutText.value).toContain('"unit":"speed.unit.kmh"');
  });

  test("renders OBD2 when OBD2 is the resolved speed source", () => {
    const state = createAppState();
    state.realtime.speedMps.value = 22.5;
    state.settings.speed.source.value = "obd2";
    state.settings.speed.resolvedSource.value = "obd2";
    state.shell.speedUnit.value = "kmh";

    const module = createUiShellStatusModule({
      realtime: state.realtime,
      settings: state.settings,
      shell: state.shell,
      t: testTranslation,
      transport: state.transport,
    });

    expect(module.speedReadoutText.value).toContain("speed.obd2");
    expect(module.speedReadoutText.value).toContain('"unit":"speed.unit.kmh"');
  });
});
