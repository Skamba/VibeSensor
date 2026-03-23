import { expect, test } from "@playwright/test";

import { createAppState } from "../src/app/ui_app_state";
import type { UiDomElements } from "../src/app/ui_dom_registry";
import {
  DEFAULT_SHELL_VIEW_ID,
  createUiShellNavigationModule,
} from "../src/app/runtime/ui_shell_navigation_module";
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
        method: "POST",
        body: JSON.stringify({ speed_unit: "mps" }),
      },
    ]);
    expect(state.shell.speedUnit).toBe("mps");
    expect(renderSpeedReadoutCalls).toBe(1);
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
