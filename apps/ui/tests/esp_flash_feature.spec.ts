import { expect, test } from "@playwright/test";

import type { UiEspFlashDom } from "../src/app/dom/esp_flash_dom";
import type { UiUpdateDom } from "../src/app/dom/update_dom";
import { createEspFlashFeature } from "../src/app/features/esp_flash_feature";
import { createUpdateFeature } from "../src/app/features/update_feature";
import {
  createDeferred,
  flushAsyncWork,
  installTimerHarness,
  installWindowGlobal,
  jsonResponse,
} from "./async_test_helpers";
import type { TimerHarness } from "./async_test_helpers";

type ClickListener = (() => void) | null;

function pendingPollDelays(timers: TimerHarness): number[] {
  return timers.pendingDelays().filter((delay) => delay !== 10_000);
}

function installFetchMock(
  handler: (url: URL, method: string, body: string) => Promise<Response> | Response,
): () => void {
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async (input: string | URL | RequestInfo, init?: RequestInit) => {
    const requestUrl =
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const requestMethod = init?.method ?? (input instanceof Request ? input.method : "GET");
    const requestBody = typeof init?.body === "string" ? init.body : "";
    return handler(new URL(requestUrl, "http://vibesensor.test"), requestMethod, requestBody);
  }) as typeof fetch;

  return () => {
    globalThis.fetch = originalFetch;
  };
}

function createButton(): HTMLButtonElement {
  let onClick: ClickListener = null;

  return {
    disabled: false,
    hidden: false,
    addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
      if (type !== "click") return;
      onClick = () => {
        const event = new Event("click");
        if (typeof listener === "function") {
          listener(event);
          return;
        }
        listener.handleEvent(event);
      };
    },
    click() {
      onClick?.();
    },
    querySelector() {
      return null;
    },
  } as unknown as HTMLButtonElement;
}

function createSelect(value: string): HTMLSelectElement {
  const listeners = new Map<string, Array<EventListenerOrEventListenerObject>>();
  return {
    value,
    disabled: false,
    innerHTML: "",
    addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
      const typeListeners = listeners.get(type) ?? [];
      typeListeners.push(listener);
      listeners.set(type, typeListeners);
    },
    dispatchEvent(event: Event) {
      const typeListeners = listeners.get(event.type) ?? [];
      for (const listener of typeListeners) {
        if (typeof listener === "function") {
          listener(event);
          continue;
        }
        listener.handleEvent(event);
      }
      return true;
    },
  } as unknown as HTMLSelectElement;
}

function createInput(value = "", type = "text"): HTMLInputElement {
  const listeners = new Map<string, Array<EventListenerOrEventListenerObject>>();
  return {
    value,
    type,
    disabled: false,
    focus() {},
    addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
      const typeListeners = listeners.get(type) ?? [];
      typeListeners.push(listener);
      listeners.set(type, typeListeners);
    },
    dispatchEvent(event: Event) {
      const typeListeners = listeners.get(event.type) ?? [];
      for (const listener of typeListeners) {
        if (typeof listener === "function") {
          listener(event);
          continue;
        }
        listener.handleEvent(event);
      }
      return true;
    },
  } as unknown as HTMLInputElement;
}

function createPanel(): HTMLElement {
  let textContent = "";
  let innerHTML = "";
  let className = "";
  const classes = new Set<string>();

  function syncClassName(): void {
    className = Array.from(classes).join(" ");
  }

  const classList = {
    add(...tokens: string[]) {
      for (const token of tokens) {
        classes.add(token);
      }
      syncClassName();
    },
    remove(...tokens: string[]) {
      for (const token of tokens) {
        classes.delete(token);
      }
      syncClassName();
    },
    toggle(token: string, force?: boolean) {
      const shouldAdd = force ?? !classes.has(token);
      if (shouldAdd) {
        classes.add(token);
      } else {
        classes.delete(token);
      }
      syncClassName();
      return classes.has(token);
    },
    contains(token: string) {
      return classes.has(token);
    },
  };

  return {
    get textContent() {
      return textContent;
    },
    set textContent(value: string | null) {
      textContent = value ?? "";
      innerHTML = textContent;
    },
    get innerHTML() {
      return innerHTML;
    },
    set innerHTML(value: string) {
      innerHTML = value;
      textContent = value;
    },
    get className() {
      return className;
    },
    set className(value: string) {
      classes.clear();
      for (const token of value.split(/\s+/).filter(Boolean)) {
        classes.add(token);
      }
      syncClassName();
    },
    classList,
    hidden: false,
    scrollTop: 0,
    scrollHeight: 0,
  } as unknown as HTMLElement;
}

function createDeps() {
  const espFlashPortSelect = createSelect("__auto__");
  const espFlashRefreshPortsBtn = createButton();
  const espFlashStartBtn = createButton();
  const espFlashCancelBtn = createButton();
  const espFlashStartSummary = createPanel();
  const espFlashStatusBanner = createPanel();
  const espFlashReadinessPanel = createPanel();
  const espFlashJourneyPanel = createPanel();
  const espFlashLogPanel = createPanel();
  const espFlashHistoryPanel = createPanel();

  const dom = {
    menuButtons: [],
    views: [],
    settingsTabs: [],
    settingsTabPanels: [],
    espFlashPortSelect,
    espFlashRefreshPortsBtn,
    espFlashStartBtn,
    espFlashCancelBtn,
    espFlashStartSummary,
    espFlashStatusBanner,
    espFlashReadinessPanel,
    espFlashJourneyPanel,
    espFlashLogPanel,
    espFlashHistoryPanel,
  } as unknown as UiEspFlashDom;

  return {
    dom,
    els: dom,
    espFlashStartBtn,
    espFlashCancelBtn,
    espFlashStartSummary,
    espFlashReadinessPanel,
    espFlashJourneyPanel,
    t: (key: string) => key,
    escapeHtml: (value: unknown) => String(value ?? ""),
    showError: () => {},
  };
}

async function expectDelays(readDelays: () => number[], expected: number[]): Promise<void> {
  for (let attempt = 0; attempt < 25; attempt += 1) {
    const actual = readDelays();
    if (actual.length === expected.length && actual.every((delay, index) => delay === expected[index])) {
      expect(actual).toEqual(expected);
      return;
    }
    await flushAsyncWork(1);
  }
  expect(readDelays()).toEqual(expected);
}

async function expectPollDelays(timers: TimerHarness, expected: number[]): Promise<void> {
  await expectDelays(() => pendingPollDelays(timers), expected);
}

async function expectTimerDelays(timers: TimerHarness, expected: number[]): Promise<void> {
  await expectDelays(() => timers.pendingDelays(), expected);
}

function createIdleUpdateStatus() {
  return {
    state: "idle",
    phase: "idle",
    transport: "wifi",
    ssid: null,
    uplink_interface: null,
    started_at: null,
    phase_started_at: null,
    phase_elapsed_s: null,
    finished_at: null,
    last_success_at: null,
    updated_at: null,
    issues: [],
    log_tail: [],
    exit_code: null,
    runtime: {
      version: "1.2.3",
      commit: "abcdef1234567890",
      ui_source_hash: "ui-hash",
      static_assets_hash: "feedfacecafebeef",
      static_build_source_hash: "build-hash",
      static_build_commit: "build-commit",
      assets_verified: true,
      has_packaged_static: true,
    },
  };
}

function createHealthyUpdateStatus() {
  return {
    status: "ok",
    processing_state: "idle",
    processing_failures: 0,
    degradation_reasons: [],
    data_loss: {
      affected_clients: 0,
      tracked_clients: 0,
      frames_dropped: 0,
      queue_overflow_drops: 0,
      server_queue_drops: 0,
      parse_errors: 0,
    },
    persistence: {
      analysis_in_progress: false,
      analysis_queue_depth: 0,
      write_error: null,
      analysis_active_run_id: null,
      analysis_started_at: null,
      analysis_elapsed_s: null,
    },
  };
}

function createUpdateDeps() {
  const internetStatusPanel = createPanel();
  const updateTransportOptions = createPanel();
  const updateTransportChoiceWifi = createPanel();
  const updateTransportChoiceUsb = createPanel();
  const updateWifiFields = createPanel();
  const updateReadinessSummary = createPanel();
  const updateDetailsCaption = createPanel();
  const updateTransportNote = createPanel();
  const updateUsbTransportSummary = createPanel();
  const updateTransportWifiRadio = createInput("", "radio");
  updateTransportWifiRadio.checked = true;
  const updateTransportUsbRadio = createInput("", "radio");
  updateTransportUsbRadio.checked = false;
  const updateSsidInput = createInput("MyWiFi");
  const updatePasswordInput = createInput("secret", "password");
  const updateTogglePasswordBtn = createButton();
  const updateStartBtn = createButton();
  const updateCancelBtn = createButton();
  const updateStatusPanel = createPanel();

  const dom = {
    menuButtons: [],
    views: [],
    settingsTabs: [],
    settingsTabPanels: [],
    internetStatusPanel,
    updateTransportOptions,
    updateTransportChoiceWifi,
    updateTransportChoiceUsb,
    updateWifiFields,
    updateReadinessSummary,
    updateDetailsCaption,
    updateTransportNote,
    updateTransportWifiRadio,
    updateTransportUsbRadio,
    updateUsbTransportSummary,
    updateSsidInput,
    updatePasswordInput,
    updateTogglePasswordBtn,
    updateStartBtn,
    updateCancelBtn,
    updateStatusPanel,
  } as unknown as UiUpdateDom;

  return {
    dom,
    els: dom,
    internetStatusPanel,
    updateTransportOptions,
    updateTransportChoiceWifi,
    updateTransportChoiceUsb,
    updateWifiFields,
    updateReadinessSummary,
    updateDetailsCaption,
    updateTransportNote,
    updateTransportWifiRadio,
    updateTransportUsbRadio,
    updateUsbTransportSummary,
    updatePasswordInput,
    updateStartBtn,
    updateCancelBtn,
    t: (key: string) => key,
    escapeHtml: (value: unknown) => String(value ?? ""),
    showError: () => {},
  };
}

function createUsbInternetStatus(overrides: Record<string, unknown> = {}) {
  return {
    detected: false,
    usable: false,
    interface_name: null,
    connection_name: null,
    driver: null,
    ipv4_addresses: [],
    gateway: null,
    has_default_route: false,
    diagnostic: "No USB network interface is currently detected.",
    ...overrides,
  };
}

test.beforeEach(() => {
  installWindowGlobal();
});

test.describe("createEspFlashFeature polling", () => {
  test("idle state renders readiness, empty log, and empty history context", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [{ port: "/dev/ttyUSB0", description: "USB UART", vid: 1, pid: 2, serial_number: "abc" }] });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", phase: "idle", selected_port: null, auto_detect: true, last_success_at: null, error: null, log_count: 0 });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.summary_ready",
      );
      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.item.connection_ready",
      );
      expect(deps.espFlashStartBtn.disabled).toBe(false);
      expect(deps.espFlashCancelBtn.hidden).toBe(true);
      expect(deps.espFlashReadinessPanel.innerHTML).toContain("settings.esp_flash.readiness.summary.ready_ports");
      expect(deps.espFlashReadinessPanel.innerHTML).toContain("settings.esp_flash.readiness.one_port");
      expect(deps.espFlashReadinessPanel.innerHTML).toContain("settings.esp_flash.auto_detect");
      expect(deps.espFlashReadinessPanel.innerHTML).not.toContain("settings.esp_flash.journey_title");
      expect(deps.espFlashReadinessPanel.innerHTML).not.toContain("settings.esp_flash.phase.validating");
      expect(deps.espFlashJourneyPanel.innerHTML).toContain("settings.esp_flash.phase.validating");
      expect((deps.els.espFlashLogPanel as HTMLElement).innerHTML).toContain("settings.esp_flash.logs_idle_title");
      expect((deps.els.espFlashHistoryPanel as HTMLElement).innerHTML).toContain("settings.esp_flash.history_empty_title");
    } finally {
      restoreFetch();
    }
  });

  test("no detected ports keep the flash action blocked until hardware is present", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [] });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", phase: "idle", selected_port: null, auto_detect: true, last_success_at: null, error: null, log_count: 0 });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.summary_blocked",
      );
      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.item.connection_blocked",
      );
      expect(deps.espFlashStartBtn.disabled).toBe(true);
      expect(deps.espFlashCancelBtn.hidden).toBe(true);
    } finally {
      restoreFetch();
    }
  });

  test("running state highlights the active stage and marks completed stages done", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [{ port: "/dev/ttyUSB0", description: "USB UART", vid: 1, pid: 2, serial_number: "abc" }] });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({
          state: "running",
          phase: "flashing",
          selected_port: "/dev/ttyUSB0",
          auto_detect: false,
          last_success_at: null,
          error: null,
          log_count: 0,
        });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.summary_running",
      );
      expect(deps.espFlashStartBtn.hidden).toBe(true);
      expect(deps.espFlashCancelBtn.hidden).toBe(false);
      expect((deps.els.espFlashLogPanel as HTMLElement).innerHTML).toContain(
        "settings.esp_flash.logs_running_title",
      );
      const html = deps.espFlashJourneyPanel.innerHTML;
      expect(html).toMatch(/data-stage-phase="flashing" data-stage-state="active" aria-current="step"/);
      expect(deps.espFlashReadinessPanel.innerHTML).toContain("settings.esp_flash.readiness.current_step");
      expect(html.match(/data-stage-state="done"/g)).toHaveLength(3);
      expect(html.match(/<span class="maintenance-stage__marker">✓<\/span>/g)).toHaveLength(3);
    } finally {
      restoreFetch();
    }
  });

  test("failed refresh keeps the last running stage marked as stopped here", async () => {
    let status = {
      state: "running",
      phase: "flashing",
      selected_port: "/dev/ttyUSB0",
      auto_detect: false,
      last_success_at: null,
      error: null,
      log_count: 0,
    };
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [{ port: "/dev/ttyUSB0", description: "USB UART", vid: 1, pid: 2, serial_number: "abc" }] });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse(status);
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      status = {
        ...status,
        state: "failed",
        phase: "failed",
        error: "serial port disconnected",
      };
      feature.stopPolling();
      feature.startPolling();
      await flushAsyncWork();

      const html = deps.espFlashJourneyPanel.innerHTML;
      expect(html).toMatch(/data-stage-phase="flashing" data-stage-state="attention"/);
      expect(deps.espFlashStartSummary.innerHTML).toContain("settings.esp_flash.recovery.title");
      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.recovery.flashing.detail",
      );
      expect(deps.espFlashStartBtn.textContent).toBe("settings.esp_flash.retry");
      expect((deps.els.espFlashLogPanel as HTMLElement).innerHTML).toContain(
        "settings.esp_flash.logs_failed_title",
      );
      expect((deps.els.espFlashHistoryPanel as HTMLElement).innerHTML).toContain(
        "serial port disconnected",
      );
      expect(html.match(/data-stage-state="done"/g)).toHaveLength(3);
      expect(deps.espFlashReadinessPanel.innerHTML).toContain("serial port disconnected");
    } finally {
      restoreFetch();
    }
  });

  test("start replaces the previous poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFetchMock(async (url, method) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [{ port: "/dev/ttyUSB0", description: "USB UART", vid: 1, pid: 2, serial_number: "abc" }] });
      }
      if (url.pathname === "/api/esp-flash/start" && method === "POST") {
        return jsonResponse({ status: "started", job_id: 1 });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", log_count: 0, error: null });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.bindHandlers();
      feature.startPolling();
      await expectPollDelays(timers, [4_000]);

      deps.espFlashStartBtn.click();
      await expectPollDelays(timers, [4_000]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("cancel replaces the previous poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFetchMock(async (url, method) => {
      if (url.pathname === "/api/esp-flash/ports") return jsonResponse({ ports: [] });
      if (url.pathname === "/api/esp-flash/cancel" && method === "POST") {
        return jsonResponse({ status: "cancelled" });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", log_count: 0, error: null });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.bindHandlers();
      feature.startPolling();
      await expectPollDelays(timers, [4_000]);

      deps.espFlashCancelBtn.click();
      await expectPollDelays(timers, [4_000]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("stopPolling prevents an in-flight poll from reviving the loop", async () => {
    const timers = installTimerHarness();
    const deferredStatus = createDeferred<Response>();
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") return jsonResponse({ ports: [] });
      if (url.pathname === "/api/esp-flash/status") return deferredStatus.promise;
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();
      expect(pendingPollDelays(timers)).toEqual([]);

      feature.stopPolling();
      deferredStatus.resolve(jsonResponse({ state: "idle", log_count: 0, error: null }));
      await flushAsyncWork();

      expect(pendingPollDelays(timers)).toEqual([]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });
});

test.describe("createUpdateFeature polling", () => {
  test("idle update status renders readiness and the expected journey", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("settings.update.current_status_title");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("settings.update.current_status_summary.ready");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("settings.update.journey_title");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("settings.update.phase.validating");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).not.toContain("settings.update.issues_empty_title");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("settings.update.log_empty_title");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("1.2.3");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain("settings.update.health_card_title");
      expect((deps.internetStatusPanel as HTMLElement).innerHTML).toContain("settings.internet.card_title");
      expect((deps.internetStatusPanel as HTMLElement).innerHTML).toContain("settings.internet.summary.not_detected");
      expect(deps.updateTransportOptions.hidden).toBe(false);
      expect(deps.updateTransportChoiceWifi.classList.contains("speed-source-choice--selected")).toBe(true);
      expect(deps.updateTransportChoiceUsb.classList.contains("speed-source-choice--disabled")).toBe(true);
      expect(deps.updateTransportUsbRadio.disabled).toBe(true);
      expect(deps.updateReadinessSummary.innerHTML).toContain("settings.update.readiness.summary_ready");
      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.readiness.item.connection_wifi_ready",
      );
      expect(deps.updateDetailsCaption.textContent).toBe("settings.update.details_caption_wifi");
      expect(deps.updateStartBtn.disabled).toBe(false);
      expect(deps.updateUsbTransportSummary.textContent).toBe(
        "settings.update.transport.usb_summary_unavailable",
      );
    } finally {
      restoreFetch();
    }
  });

  test("degraded health blocks update start until maintenance issues are resolved", async () => {
    const healthy = createHealthyUpdateStatus();
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse({
          ...healthy,
          status: "degraded",
          degradation_reasons: ["persistence_write_error"],
          persistence: {
            ...healthy.persistence,
            write_error: "database locked",
          },
        });
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.readiness.item.health_blocked",
      );
      expect(deps.updateStartBtn.disabled).toBe(true);
    } finally {
      restoreFetch();
    }
  });

  test("running update state highlights the active journey stage", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") {
        return jsonResponse({
          ...createIdleUpdateStatus(),
          state: "running",
          phase: "installing",
          transport: "wifi",
          ssid: "MyWiFi",
        });
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      const html = (deps.els.updateStatusPanel as HTMLElement).innerHTML;
      expect(html).toContain("settings.update.log_running_title");
      expect(html).toMatch(/data-stage-phase="installing" data-stage-state="active" aria-current="step"/);
      expect(html.match(/data-stage-state="done"/g)).toHaveLength(5);
      expect(html.match(/<span class="maintenance-stage__marker">✓<\/span>/g)).toHaveLength(5);
    } finally {
      restoreFetch();
    }
  });

  test("failed update state surfaces the failed stage and issue details", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") {
        return jsonResponse({
          ...createIdleUpdateStatus(),
          state: "failed",
          phase: "restoring_hotspot",
          transport: "wifi",
          issues: [
            {
              phase: "restoring_hotspot",
              message: "Hotspot restart timed out",
              detail: "NetworkManager is still reconnecting to the uplink.",
            },
          ],
        });
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      const html = (deps.els.updateStatusPanel as HTMLElement).innerHTML;
      expect(deps.updateReadinessSummary.innerHTML).toContain("settings.update.recovery.title");
      expect(deps.updateReadinessSummary.innerHTML).toContain("settings.update.recovery.wifi.title");
      expect(deps.updateReadinessSummary.innerHTML).toContain("settings.update.recovery.wifi.detail");
      expect(deps.updateStartBtn.textContent).toBe("settings.update.retry");
      expect(html).toContain("settings.update.issues");
      expect(html).toContain("settings.update.attempt_title");
      expect(html).toContain("settings.update.log_failed_title");
      expect(html).toContain("Hotspot restart timed out");
      expect(html).toContain("NetworkManager is still reconnecting to the uplink.");
      expect(html).toMatch(/data-stage-phase="restoring_hotspot" data-stage-state="attention"/);
    } finally {
      restoreFetch();
    }
  });

  test("start replaces the previous update poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    let startBody = "";
    const restoreFetch = installFetchMock(async (url, method, body) => {
      if (url.pathname === "/api/update/start" && method === "POST") {
        startBody = body;
        return jsonResponse({ status: "started", transport: "wifi", ssid: "MyWiFi" });
      }
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.bindUpdateHandlers();
      feature.startPolling();
      await expectTimerDelays(timers, [10_000]);

      deps.updateStartBtn.click();
      await expectTimerDelays(timers, [10_000]);
      expect(deps.updatePasswordInput.value).toBe("");
      expect(JSON.parse(startBody)).toEqual({
        transport: "wifi",
        ssid: "MyWiFi",
        password: "secret",
      });
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("usable USB internet shows the USB option and starts with the USB transport payload", async () => {
    let startBody = "";
    const restoreFetch = installFetchMock(async (url, method, body) => {
      if (url.pathname === "/api/update/start" && method === "POST") {
        startBody = body;
        return jsonResponse({ status: "started", transport: "usb_internet", ssid: null });
      }
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(
          createUsbInternetStatus({
            detected: true,
            usable: true,
            interface_name: "usb0",
            connection_name: "iPhone USB",
            driver: "ipheth",
            ipv4_addresses: ["172.20.10.2/28"],
            gateway: "172.20.10.1",
            has_default_route: true,
            diagnostic: "USB internet is ready on 'usb0'.",
          }),
        );
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      deps.updateTransportWifiRadio.checked = false;
      deps.updateTransportUsbRadio.checked = true;
      const feature = createUpdateFeature(deps);

      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();
      deps.updateTransportWifiRadio.checked = false;
      deps.updateTransportUsbRadio.checked = true;
      deps.updateTransportUsbRadio.dispatchEvent(new Event("change"));

      expect(deps.updateTransportOptions.hidden).toBe(false);
      expect(deps.updateWifiFields.hidden).toBe(true);
      expect(deps.updateStartBtn.disabled).toBe(false);
      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.readiness.item.connection_usb_ready",
      );
      expect(deps.updateDetailsCaption.textContent).toBe("settings.update.details_caption_usb");
      expect(deps.updateTransportNote.textContent).toBe("settings.update.preflight_note_usb");
      expect(deps.updateUsbTransportSummary.textContent).toBe(
        "settings.update.transport.usb_summary_interface",
      );
      expect(deps.updateTransportChoiceWifi.classList.contains("speed-source-choice--selected")).toBe(false);
      expect(deps.updateTransportChoiceUsb.classList.contains("speed-source-choice--selected")).toBe(true);
      expect(deps.updateTransportChoiceUsb.classList.contains("speed-source-choice--disabled")).toBe(false);
      expect((deps.internetStatusPanel as HTMLElement).innerHTML).toContain("usb0");

      deps.updateStartBtn.click();
      await flushAsyncWork();

      expect(JSON.parse(startBody)).toEqual({ transport: "usb_internet", password: "" });
    } finally {
      restoreFetch();
    }
  });

  test("cancel replaces the previous update poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFetchMock(async (url, method) => {
      if (url.pathname === "/api/update/cancel" && method === "POST") {
        return jsonResponse({ status: "cancelled" });
      }
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.bindUpdateHandlers();
      feature.startPolling();
      await expectTimerDelays(timers, [10_000]);

      deps.updateCancelBtn.click();
      await expectTimerDelays(timers, [10_000]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("stopPolling prevents an in-flight update poll from reviving the loop", async () => {
    const timers = installTimerHarness();
    const deferredStatus = createDeferred<Response>();
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") return deferredStatus.promise;
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.startPolling();
      await expectTimerDelays(timers, [10_000]);

      feature.stopPolling();
      deferredStatus.resolve(jsonResponse(createIdleUpdateStatus()));
      await expectTimerDelays(timers, []);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });
});
