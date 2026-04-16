import { expect, test } from "@playwright/test";

import { createAppState } from "../src/app/ui_app_state";
import {
  DEFAULT_SHELL_VIEW_ID,
  createUiShellNavigationModule,
} from "../src/app/runtime/ui_shell_navigation_module";
import { createUiShellNotificationModule } from "../src/app/runtime/ui_shell_notification_module";
import { createUiShellPreferencesModule } from "../src/app/runtime/ui_shell_preferences_module";
import { createUiShellStatusModule } from "../src/app/runtime/ui_shell_status_module";

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

test.describe("createUiShellNavigationModule", () => {
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
    expect(state.shell.activeViewId).toBe("historyView");
    expect(module.activeViewId.value).toBe("historyView");
    expect(activatedViews).toEqual(["historyView"]);
    expect(resizeCalls).toBe(0);

    module.setActiveView("missingView");
    expect(state.shell.activeViewId).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(module.activeViewId.value).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(activatedViews).toEqual(["historyView"]);
    expect(resizeCalls).toBe(1);
  });

  test("waits for async lazy-view activation before switching views", async () => {
    const state = createAppState();
    let resolveActivation: (() => void) | null = null;

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
    expect(state.shell.activeViewId).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(module.activeViewId.value).toBe(DEFAULT_SHELL_VIEW_ID);

    resolveActivation?.();
    await Promise.resolve();

    expect(state.shell.activeViewId).toBe("settingsView");
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

    expect(state.shell.activeViewId).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(module.activeViewId.value).toBe(DEFAULT_SHELL_VIEW_ID);
    expect(activationErrors).toEqual(["settingsView:chunk failed"]);
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

    const module = createUiShellPreferencesModule({
      shell: state.shell,
      t: (key) => key,
      normalizeLanguage: (lang) => String(lang),
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
    expect(module.selectedLanguage.value).toBe("nl");
    expect(module.selectedSpeedUnit.value).toBe("mps");
  });

  test("keeps the pending language selection visible until the save resolves", async () => {
    const state = createAppState();
    let resolveResponse: ((response: Response) => void) | null = null;

    const module = createUiShellPreferencesModule({
      shell: state.shell,
      t: (key) => key,
      normalizeLanguage: (lang) => String(lang),
    });

    await withMockFetch(
      (async () =>
        new Promise<Response>((resolve) => {
          resolveResponse = resolve;
        })) as typeof fetch,
      async () => {
        const savePromise = module.saveLanguage("nl");
        expect(module.selectedLanguage.value).toBe("nl");
        expect(state.shell.lang).toBe("en");
        resolveResponse?.(jsonResponse({ language: "nl" }));
        await savePromise;
      },
    );

    expect(state.shell.lang).toBe("nl");
    expect(module.selectedLanguage.value).toBe("nl");
  });

  test("save failure restores the previous speed unit and reports inline field feedback", async () => {
    const state = createAppState();

    const module = createUiShellPreferencesModule({
      shell: state.shell,
      t: testTranslation,
      normalizeLanguage: (lang) => String(lang),
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
    expect(module.selectedSpeedUnit.value).toBe("kmh");
    expect(module.speedUnitFeedback.value?.detail).toBe("save failed");
  });
});

test.describe("createUiShellNotificationModule", () => {
  test("shows and clears the shared error banner model signal", () => {
    let pendingHide: (() => void) | null = null;

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

    pendingHide?.();
    expect(module.bannerModel.value).toEqual({
      hidden: true,
      text: "",
      variant: null,
    });
  });
});

test.describe("createUiShellStatusModule", () => {
  test("builds websocket badge state and degraded shell status signals without bootstrap wiring", () => {
    const state = createAppState();
    state.transport.wsState = "stale";

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

    state.transport.wsState = "stale";
    expect(module.wsLinkState.value).toEqual({
      text: "ws.stale",
      variant: "bad",
    });

    state.transport.payloadError = "bad frame";
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
      t: (key) => `${state.shell.lang}:${key}`,
      transport: state.transport,
    });

    expect(module.wsLinkState.value).toEqual({
      text: "en:ws.connecting",
      variant: "muted",
    });

    state.shell.lang = "nl";

    expect(module.wsLinkState.value).toEqual({
      text: "nl:ws.connecting",
      variant: "muted",
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
    state.realtime.speedMps = 22.5;
    state.settings.speedSource = "obd2";
    state.settings.resolvedSpeedSource = "obd2";
    state.shell.speedUnit = "kmh";

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
