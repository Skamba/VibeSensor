import assert from "node:assert/strict";

import { render } from "preact";
import { expect } from "vitest";

import type { EspFlashFeatureDeps } from "../src/app/features/esp_flash_feature";
import { createEspFlashFeature } from "../src/app/features/esp_flash_feature";
import type { UpdateFeatureDeps } from "../src/app/features/update_feature";
import { createUpdateFeature } from "../src/app/features/update_feature";
import { type ReadonlySignal, signal } from "../src/app/ui_signals";
import type {
  EspFlashPanelActionHandlers,
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
import type { TimerHarness } from "./async_test_helpers";
import { flushAsyncWork } from "./async_test_helpers";
import { installMountedDomGlobals } from "./dom_render_test_support";
import {
  createEspFlashPort,
  createHealthyUpdateStatus,
  createIdleUpdateStatus,
  createUsbInternetStatus,
} from "./maintenance_payload_test_support";
import { http } from "./msw/http";
import { createUiMswTestScope } from "./msw/node";
import { createTestQueryClient } from "./query_client_test_support";

type FeatureServices = UpdateFeatureDeps["services"];

const activeMaintenanceCleanups: Array<() => void> = [];
const MAINTENANCE_TEST_TRANSLATIONS: Readonly<Record<string, string>> = {
  "maintenance.readiness.blocked": "Blocked",
  "maintenance.readiness.ready": "Ready",
  "maintenance.readiness.running": "Running",
  "maintenance.stage_state.active": "Active",
  "maintenance.stage_state.attention": "Needs attention",
  "maintenance.stage_state.done": "Complete",
  "maintenance.stage_state.upcoming": "Upcoming",
  "settings.esp_flash.auto_detect": "Auto-detect",
  "settings.esp_flash.history_empty_title": "No flash attempts yet",
  "settings.esp_flash.journey.detail.done": "Confirm flash finished.",
  "settings.esp_flash.journey.detail.erasing": "Erase old firmware.",
  "settings.esp_flash.journey.detail.flashing": "Write firmware.",
  "settings.esp_flash.journey.detail.preparing": "Prepare the device.",
  "settings.esp_flash.journey.detail.validating": "Validate the selected port.",
  "settings.esp_flash.journey_terminal.failed": "Flash failed.",
  "settings.esp_flash.journey_title": "Flash progress",
  "settings.esp_flash.logs_failed_title": "Flash log failed",
  "settings.esp_flash.logs_idle_title": "Flash log idle",
  "settings.esp_flash.logs_running_title": "Flash log running",
  "settings.esp_flash.phase.done": "Done",
  "settings.esp_flash.phase.erasing": "Erasing",
  "settings.esp_flash.phase.flashing": "Flashing",
  "settings.esp_flash.phase.preparing": "Preparing",
  "settings.esp_flash.phase.validating": "Validating",
  "settings.esp_flash.readiness.current_step": "Current step",
  "settings.esp_flash.readiness.one_port": "1 port available",
  "settings.esp_flash.readiness.summary.ready_ports": "Ready ports",
  "settings.esp_flash.recovery.flashing.detail":
    "Reconnect the ESP and retry flashing.",
  "settings.esp_flash.recovery.title": "Flash recovery",
  "settings.esp_flash.retry": "Retry flash",
  "settings.esp_flash.start": "Start flash",
  "settings.esp_flash.start_readiness.item.connection_blocked":
    "No ESP port found.",
  "settings.esp_flash.start_readiness.item.connection_ready": "ESP port ready.",
  "settings.esp_flash.start_readiness.summary_blocked": "Flash blocked",
  "settings.esp_flash.start_readiness.summary_ready": "Ready to flash",
  "settings.esp_flash.start_readiness.summary_running": "Flash running",
  "settings.internet.card_title": "USB internet",
  "settings.internet.summary.not_detected": "No USB internet detected",
  "settings.update.attempt_title": "Latest update attempt",
  "settings.update.current_status_summary.ready": "Update service ready",
  "settings.update.current_status_title": "Current update status",
  "settings.update.details_caption_usb": "USB internet details",
  "settings.update.details_caption_wifi": "Wi-Fi details",
  "settings.update.health.subsystem_state.unhealthy": "Unhealthy",
  "settings.update.health.subsystems": "Subsystems",
  "settings.update.health_card_title": "Update health",
  "settings.update.issues": "Update issues",
  "settings.update.issues_empty_title": "No update issues",
  "settings.update.journey.detail.checking": "Check for a release.",
  "settings.update.journey.detail.connecting_usb_internet": "Use USB internet.",
  "settings.update.journey.detail.connecting_wifi": "Connect to Wi-Fi.",
  "settings.update.journey.detail.done": "Finish update.",
  "settings.update.journey.detail.downloading": "Download update.",
  "settings.update.journey.detail.installing": "Install update.",
  "settings.update.journey.detail.restoring_hotspot": "Restore hotspot.",
  "settings.update.journey.detail.stopping_hotspot": "Stop hotspot.",
  "settings.update.journey.detail.validating": "Validate update request.",
  "settings.update.journey_intro": "Update progress details",
  "settings.update.journey_title": "Update progress",
  "settings.update.log_empty_title": "No update log yet",
  "settings.update.log_failed_title": "Update log failed",
  "settings.update.log_running_title": "Update log running",
  "settings.update.phase.checking": "Checking",
  "settings.update.phase.connecting_usb_internet": "Connecting USB internet",
  "settings.update.phase.connecting_wifi": "Connecting Wi-Fi",
  "settings.update.phase.done": "Done",
  "settings.update.phase.downloading": "Downloading",
  "settings.update.phase.installing": "Installing",
  "settings.update.phase.restoring_hotspot": "Restoring hotspot",
  "settings.update.phase.stopping_hotspot": "Stopping hotspot",
  "settings.update.phase.validating": "Validating",
  "settings.update.preflight_note_usb":
    "USB internet will be used for update checks.",
  "settings.update.readiness.item.connection_usb_ready":
    "USB internet ready on {interface}.",
  "settings.update.readiness.item.connection_wifi_ready":
    "Wi-Fi connection ready.",
  "settings.update.readiness.item.health_blocked":
    "Health blocks update start.",
  "settings.update.readiness.summary_ready": "Ready to update",
  "settings.update.recovery.title": "Update recovery",
  "settings.update.recovery.wifi.detail":
    "Reconnect Wi-Fi or use USB internet.",
  "settings.update.recovery.wifi.title": "Restore network connection",
  "settings.update.retry": "Retry update",
  "settings.update.start": "Start update",
  "settings.update.transport.selected_badge": "Selected",
  "settings.update.transport.usb_summary_interface":
    "USB interface {interface}",
  "settings.update.transport.usb_summary_unavailable":
    "USB internet unavailable",
  "settings.update.transport.wifi_summary": "Use Wi-Fi for the update.",
};

function requireElement<T extends Element = HTMLElement>(
  root: ParentNode,
  selector: string,
): T {
  const element =
    root.querySelector<T>(selector) ??
    globalThis.document?.querySelector<T>(selector);
  assert.ok(element, `Expected element matching ${selector}`);
  return element;
}

function ensureMutableValueProperty<T extends Element & { value: string }>(
  element: T,
  initialValue = element.getAttribute("value") ?? "",
): T {
  const descriptor =
    Object.getOwnPropertyDescriptor(element, "value") ??
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "value");
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
  const descriptor =
    Object.getOwnPropertyDescriptor(element, "checked") ??
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "checked");
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
    t: (key: string, vars?: Record<string, unknown>) =>
      translateMaintenanceTestText(key, vars),
  };
}

function translateMaintenanceTestText(
  key: string,
  vars?: Record<string, unknown>,
): string {
  const template = MAINTENANCE_TEST_TRANSLATIONS[key] ?? key;
  return template.replaceAll(/\{([a-zA-Z0-9_]+)\}/g, (_, name: string) =>
    String(vars?.[name] ?? ""),
  );
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
  return timers
    .pendingDelays()
    .filter((delay) => delay !== 10_000 && delay >= 100);
}

function createMountedHost(): HTMLElement {
  const host = globalThis.document.createElement("div");
  globalThis.document.body.appendChild(host);
  return host;
}

async function createEspFlashFeatureDeps() {
  const navigation = createFeatureNavigationHarness("espFlashTab");
  const root = createMountedHost();
  const { mountEspFlashPanel } = await import(
    "../src/app/views/esp_flash_panel"
  );
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
      return requireElement<HTMLButtonElement>(
        root,
        "#espFlashRefreshPortsBtn",
      );
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
  };

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
  const { mountInternetPanel } = await import(
    "../src/app/views/internet_panel"
  );
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
      return requireElement<HTMLButtonElement>(
        root,
        "#updateTogglePasswordBtn",
      );
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

function installFeatureFetchMock(
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

async function expectPollDelays(
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

async function expectTimerDelays(
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
