import assert from "node:assert/strict";

import { h, render } from "preact";

import type { FeatureServices } from "../src/app/feature_deps_base";
import { createUpdateFeature } from "../src/app/features/update_feature";
import { type ReadonlySignal, signal } from "../src/app/ui_signals";
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
import { installMountedDomGlobals } from "./dom_render_test_support";
import { createTestQueryClient } from "./query_client_test_support";

const activeMaintenanceCleanups: Array<() => void> = [];
const MAINTENANCE_TEST_TRANSLATIONS: Readonly<Record<string, string>> = {
  "maintenance.readiness.blocked": "Blocked",
  "maintenance.readiness.ready": "Ready",
  "maintenance.readiness.running": "Running",
  "maintenance.stage_state.active": "Active",
  "maintenance.stage_state.attention": "Needs attention",
  "maintenance.stage_state.done": "Complete",
  "maintenance.stage_state.upcoming": "Upcoming",
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

function createMountedHost(): HTMLElement {
  const host = globalThis.document.createElement("div");
  globalThis.document.body.appendChild(host);
  return host;
}

async function createUpdateFeatureDeps() {
  const navigation = createFeatureNavigationHarness("updateTab");
  const root = createMountedHost();
  const { createInternetPanel } = await import(
    "../src/app/views/internet_panel"
  );
  const { UpdatePanel } = await import("../src/app/views/update_panel");
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
  const internetPanel = createInternetPanel(internetBindings);
  const internet: InternetPanelView = { ...internetBindings, ...internetPanel };
  render(h(internetPanel.Panel, null), internetHost);
  render(h(UpdatePanel, update), updateHost);
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
    ...navigation.ports,
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

export function installMaintenanceFeatureGlobals(): () => void {
  drainMaintenanceCleanups();
  const restoreDomGlobals = installMountedDomGlobals();
  return () => {
    drainMaintenanceCleanups();
    restoreDomGlobals();
  };
}

export async function createUpdateFeatureHarness() {
  const deps = await createUpdateFeatureDeps();
  const feature = createUpdateFeature(deps);
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
