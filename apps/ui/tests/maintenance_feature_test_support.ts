import assert from "node:assert/strict";

import { render } from "preact";
import { expect } from "vitest";

import type {
  EspFlashFeatureDeps,
} from "../src/app/features/esp_flash_feature";
import { createEspFlashFeature } from "../src/app/features/esp_flash_feature";
import type {
  UpdateFeatureDeps,
} from "../src/app/features/update_feature";
import { createUpdateFeature } from "../src/app/features/update_feature";
import type {
  EspSerialPortPayload,
  HealthStatusPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../src/api/types";
import type {
  EspFlashPanelActionHandlers,
  EspFlashPanelDom,
  EspFlashPanelRenderModel,
  EspFlashPanelView,
} from "../src/app/views/esp_flash_panel";
import type {
  InternetPanelActionHandlers,
  InternetPanelRenderModel,
  InternetPanelView,
} from "../src/app/views/internet_panel";
import type {
  UpdatePanelActionHandlers,
  UpdatePanelRenderModel,
  UpdatePanelView,
} from "../src/app/views/update_panel";
import { signal, type ReadonlySignal } from "../src/app/ui_signals";
import { flushAsyncWork } from "./async_test_helpers";
import type { TimerHarness } from "./async_test_helpers";
import {
  installMountedDomGlobals,
} from "./dom_render_test_support";
import { http } from "./msw/http";
import { createUiMswTestScope } from "./msw/node";
import { createTestQueryClient } from "./query_client_test_support";

type FeatureServices = UpdateFeatureDeps["services"];

const activeMaintenanceCleanups: Array<() => void> = [];

function requireElement<T extends Element = HTMLElement>(
  root: ParentNode,
  selector: string,
): T {
  const element = root.querySelector<T>(selector) ?? globalThis.document?.querySelector<T>(selector);
  assert.ok(element, `Expected element matching ${selector}`);
  return element;
}

function ensureMutableValueProperty<T extends Element & { value: string }>(
  element: T,
  initialValue = element.getAttribute("value") ?? "",
): T {
  const descriptor = Object.getOwnPropertyDescriptor(element, "value")
    ?? Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "value");
  if (descriptor?.set) {
    return element;
  }
  let currentValue = initialValue;
  Object.defineProperty(element, "value", {
    configurable: true,
    enumerable: true,
    get() {
      return currentValue;
    },
    set(nextValue: string) {
      currentValue = String(nextValue);
    },
  });
  return element;
}

function ensureMutableCheckedProperty<T extends Element & { checked: boolean }>(
  element: T,
  initialChecked = false,
): T {
  const descriptor = Object.getOwnPropertyDescriptor(element, "checked")
    ?? Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "checked");
  if (descriptor?.set) {
    return element;
  }
  let currentChecked = initialChecked;
  Object.defineProperty(element, "checked", {
    configurable: true,
    enumerable: true,
    get() {
      return currentChecked;
    },
    set(nextValue: boolean) {
      currentChecked = Boolean(nextValue);
    },
  });
  return element;
}

function registerMaintenanceCleanup(cleanup: () => void): () => void {
  let cleaned = false;
  const trackedCleanup = () => {
    if (cleaned) {
      return;
    }
    cleaned = true;
    const index = activeMaintenanceCleanups.indexOf(trackedCleanup);
    if (index >= 0) {
      activeMaintenanceCleanups.splice(index, 1);
    }
    cleanup();
  };
  activeMaintenanceCleanups.push(trackedCleanup);
  return trackedCleanup;
}

function drainMaintenanceCleanups(): void {
  while (activeMaintenanceCleanups.length > 0) {
    activeMaintenanceCleanups.pop()?.();
  }
}

function createFeatureServices(): FeatureServices {
  return {
    requestConfirmation: async () => true,
    showError: () => {},
    t: (key: string) => key,
  };
}

function createFeatureNavigationHarness(defaultTabId: string) {
  const activeViewId = signal("settingsView");
  const activeSettingsTabId = signal(defaultTabId);

  return {
    ports: {
      activeSettingsTabId,
      activeViewId,
    },
    setActiveSettingsTabId(nextTabId: string) {
      activeSettingsTabId.value = nextTabId;
    },
    setActiveViewId(nextViewId: string) {
      activeViewId.value = nextViewId;
    },
  };
}

function pendingPollDelays(timers: TimerHarness): number[] {
  return timers.pendingDelays().filter((delay) => delay !== 10_000 && delay >= 100);
}

function createMountedHost(): HTMLElement {
  const host = globalThis.document.createElement("div");
  globalThis.document.body.appendChild(host);
  return host;
}

async function createEspFlashFeatureDeps() {
  const navigation = createFeatureNavigationHarness("espFlashTab");
  const root = createMountedHost();
  const { mountEspFlashPanel } = await import("../src/app/views/esp_flash_panel");
  const panel: EspFlashPanelView = {
    actions: signal<EspFlashPanelActionHandlers | null>(null),
    model: signal<ReadonlySignal<EspFlashPanelRenderModel> | null>(null),
  };
  mountEspFlashPanel(root, panel);
  const cleanup = registerMaintenanceCleanup(() => {
    render(null, root);
    root.remove();
  });
  const els = {
    get espFlashCancelBtn() {
      return requireElement<HTMLButtonElement>(root, "#espFlashCancelBtn");
    },
    get espFlashHistoryPanel() {
      return requireElement(root, "#espFlashHistoryPanel");
    },
    get espFlashJourneyPanel() {
      return requireElement(root, "#espFlashJourneyPanel");
    },
    get espFlashLogPanel() {
      return requireElement(root, "#espFlashLogPanel");
    },
    get espFlashPortSelect() {
      return ensureMutableValueProperty(
        requireElement<HTMLSelectElement>(root, "#espFlashPortSelect"),
        "__auto__",
      );
    },
    get espFlashReadinessPanel() {
      return requireElement(root, "#espFlashReadinessPanel");
    },
    get espFlashRefreshPortsBtn() {
      return requireElement<HTMLButtonElement>(root, "#espFlashRefreshPortsBtn");
    },
    get espFlashStartBtn() {
      return requireElement<HTMLButtonElement>(root, "#espFlashStartBtn");
    },
    get espFlashStartSummary() {
      return requireElement(root, "#espFlashStartSummary");
    },
    get espFlashStatusBanner() {
      return requireElement(root, "#espFlashStatusBanner");
    },
    menuButtons: [],
    settingsTabPanels: [],
    settingsTabs: [],
    views: [],
  } satisfies EspFlashPanelDom;

  return {
    cleanup,
    els,
    get espFlashCancelBtn() {
      return els.espFlashCancelBtn;
    },
    get espFlashJourneyPanel() {
      return els.espFlashJourneyPanel;
    },
    get espFlashPortSelect() {
      return els.espFlashPortSelect;
    },
    get espFlashReadinessPanel() {
      return els.espFlashReadinessPanel;
    },
    get espFlashRefreshPortsBtn() {
      return els.espFlashRefreshPortsBtn;
    },
    get espFlashStartBtn() {
      return els.espFlashStartBtn;
    },
    get espFlashStartSummary() {
      return els.espFlashStartSummary;
    },
    panel,
    ports: navigation.ports,
    queryClient: createTestQueryClient(),
    services: createFeatureServices(),
    setActiveSettingsTabId: navigation.setActiveSettingsTabId,
    setActiveViewId: navigation.setActiveViewId,
  };
}

async function createUpdateFeatureDeps() {
  const navigation = createFeatureNavigationHarness("updateTab");
  const root = createMountedHost();
  const { mountInternetPanel } = await import("../src/app/views/internet_panel");
  const { mountUpdatePanel } = await import("../src/app/views/update_panel");
  const internetHost = globalThis.document.createElement("div");
  const updateHost = globalThis.document.createElement("div");
  root.append(internetHost, updateHost);
  const update: UpdatePanelView = {
    actions: signal<UpdatePanelActionHandlers | null>(null),
    model: signal<ReadonlySignal<UpdatePanelRenderModel> | null>(null),
  };
  const internetBindings = {
    actions: signal<InternetPanelActionHandlers | null>(null),
    model: signal<ReadonlySignal<InternetPanelRenderModel> | null>(null),
  };
  const internet: InternetPanelView = {
    ...internetBindings,
    ...mountInternetPanel(internetHost, internetBindings),
  };
  mountUpdatePanel(updateHost, update);
  const cleanup = registerMaintenanceCleanup(() => {
    render(null, internetHost);
    render(null, updateHost);
    root.remove();
  });
  const els = {
    get updateCancelBtn() {
      return requireElement<HTMLButtonElement>(root, "#updateCancelBtn");
    },
    get updateOverviewPanel() {
      return requireElement(root, "#updateOverviewPanel");
    },
    get updateStartBtn() {
      return requireElement<HTMLButtonElement>(root, "#updateStartBtn");
    },
    get updateStatusPanel() {
      return requireElement(root, "#updateStatusPanel");
    },
  };

  return {
    cleanup,
    els,
    get internetStatusPanel() {
      return requireElement(root, "#internetStatusPanel");
    },
    panels: {
      internet,
      update,
    },
    ports: navigation.ports,
    queryClient: createTestQueryClient(),
    services: createFeatureServices(),
    setActiveSettingsTabId: navigation.setActiveSettingsTabId,
    setActiveViewId: navigation.setActiveViewId,
    get updateCancelBtn() {
      return els.updateCancelBtn;
    },
    get updateDetailsCaption() {
      return requireElement(root, "#updateDetailsCaption");
    },
    get updatePasswordInput() {
      return ensureMutableValueProperty(
        requireElement<HTMLInputElement>(root, "#updatePasswordInput"),
      );
    },
    get updateReadinessSummary() {
      return requireElement(root, "#updateReadinessSummary");
    },
    get updateSsidInput() {
      return ensureMutableValueProperty(
        requireElement<HTMLInputElement>(root, "#updateSsidInput"),
      );
    },
    get updateStartBtn() {
      return els.updateStartBtn;
    },
    get updateTogglePasswordBtn() {
      return requireElement<HTMLButtonElement>(root, "#updateTogglePasswordBtn");
    },
    get updateTransportChoiceUsb() {
      return requireElement(root, "#updateTransportChoiceUsb");
    },
    get updateTransportChoiceWifi() {
      return requireElement(root, "#updateTransportChoiceWifi");
    },
    get updateTransportNote() {
      return requireElement(root, "#updateTransportNote");
    },
    get updateTransportOptions() {
      return requireElement(root, "#updateTransportOptions");
    },
    get updateTransportUsbRadio() {
      return ensureMutableCheckedProperty(
        ensureMutableValueProperty(
          requireElement<HTMLInputElement>(root, "#updateTransportUsbRadio"),
        ),
      );
    },
    get updateTransportWifiRadio() {
      return ensureMutableCheckedProperty(
        ensureMutableValueProperty(
          requireElement<HTMLInputElement>(root, "#updateTransportWifiRadio"),
        ),
        true,
      );
    },
    get updateUsbTransportSummary() {
      return requireElement(root, "#updateUsbTransportSummary");
    },
    get updateWifiFields() {
      return requireElement(root, "#updateWifiFields");
    },
  };
}

export function installFeatureFetchMock(
  handler: (
    url: URL,
    method: string,
    body: string,
  ) => Promise<Response> | Response,
): () => void {
  const scope = createUiMswTestScope();
  scope.server.use(
    http.all("*", async ({ request }) => {
      const requestBody =
        request.method === "GET" || request.method === "HEAD"
          ? ""
          : await request.text();
      return await handler(new URL(request.url), request.method, requestBody);
    }),
  );

  return () => {
    scope.close();
  };
}

export function installMaintenanceFeatureGlobals(): () => void {
  drainMaintenanceCleanups();
  const restoreDomGlobals = installMountedDomGlobals();
  return () => {
    drainMaintenanceCleanups();
    restoreDomGlobals();
  };
}

export async function expectPollDelays(
  timers: TimerHarness,
  expected: number[],
): Promise<void> {
  for (let attempt = 0; attempt < 25; attempt += 1) {
    const actual = pendingPollDelays(timers);
    if (
      actual.length === expected.length &&
      actual.every((delay, index) => delay === expected[index])
    ) {
      return;
    }
    await flushAsyncWork(1);
  }
  expect(pendingPollDelays(timers)).toEqual(expected);
}

export async function expectTimerDelays(
  timers: TimerHarness,
  expected: number[],
): Promise<void> {
  for (let attempt = 0; attempt < 25; attempt += 1) {
    const actual = timers.pendingDelays();
    if (
      actual.length === expected.length &&
      actual.every((delay, index) => delay === expected[index])
    ) {
      return;
    }
    await flushAsyncWork(1);
  }
  expect(timers.pendingDelays()).toEqual(expected);
}

export function createEspFlashPort(
  overrides: Partial<EspSerialPortPayload> = {},
): EspSerialPortPayload {
  return {
    description: "USB UART",
    pid: 2,
    port: "/dev/ttyUSB0",
    serial_number: "abc",
    vid: 1,
    ...overrides,
  };
}

export function createIdleUpdateStatus(
  overrides: Partial<UpdateStatusPayload> = {},
): UpdateStatusPayload {
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
    ...overrides,
  };
}

export function createHealthyUpdateStatus(
  overrides: Partial<HealthStatusPayload> = {},
): HealthStatusPayload {
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
      analysis_active_run_id: null,
      analysis_elapsed_s: null,
      analysis_in_progress: false,
      analysis_queue_depth: 0,
      analysis_started_at: null,
      write_error: null,
    },
    ...overrides,
  };
}

export function createUsbInternetStatus(
  overrides: Partial<UsbInternetStatusPayload> = {},
): UsbInternetStatusPayload {
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

export async function createEspFlashFeatureHarness() {
  const deps = await createEspFlashFeatureDeps();
  const feature = createEspFlashFeature(deps as EspFlashFeatureDeps);
  const disposeFeature = feature.dispose.bind(feature);

  return {
    deps,
    feature: {
      ...feature,
      startPolling(): void {
        deps.setActiveViewId("settingsView");
        deps.setActiveSettingsTabId("espFlashTab");
      },
      stopPolling(): void {
        deps.setActiveViewId("dashboardView");
      },
      dispose(): void {
        disposeFeature();
        deps.cleanup();
      },
    },
  };
}

export async function createUpdateFeatureHarness() {
  const deps = await createUpdateFeatureDeps();
  const feature = createUpdateFeature(deps as UpdateFeatureDeps);
  const disposeFeature = feature.dispose.bind(feature);

  return {
    deps,
    feature: {
      ...feature,
      startPolling(): void {
        deps.setActiveViewId("settingsView");
        deps.setActiveSettingsTabId("updateTab");
      },
      stopPolling(): void {
        deps.setActiveViewId("dashboardView");
      },
      dispose(): void {
        disposeFeature();
        deps.cleanup();
      },
    },
  };
}
