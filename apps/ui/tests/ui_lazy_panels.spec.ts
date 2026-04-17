import { expect, test } from "@playwright/test";

import { createLazyUiPanels } from "../src/app/ui_lazy_panels";
import type { UiMountedDashboardPanels } from "../src/app/ui_panel_bootstrap";
import type { UiPanelHostRegistry } from "../src/app/ui_panel_host_registry";
import { signal } from "../src/app/ui_signals";
import type { HistoryPanelView } from "../src/app/views/history_table_view";
import type { InternetPanelView } from "../src/app/views/internet_panel";
import type { SettingsShellView } from "../src/app/views/settings_shell";
import type { SpeedSourcePanelView } from "../src/app/views/speed_source_panel";

function fakeElement(): HTMLElement {
  return new EventTarget() as unknown as HTMLElement;
}

function createFakeHosts(): UiPanelHostRegistry {
  return {
    dashboard: {
      spectrum: fakeElement(),
      liveOverview: fakeElement(),
      logging: fakeElement(),
    },
    history: fakeElement(),
    settingsShell: fakeElement(),
  };
}

function createDashboardPanels(): UiMountedDashboardPanels {
  return {
    spectrum: {} as UiMountedDashboardPanels["spectrum"],
    liveOverview: {
      model: signal(null),
      speedText: signal("--"),
    } as UiMountedDashboardPanels["liveOverview"],
    logging: {
      actions: signal(null),
      model: signal(null),
    } as UiMountedDashboardPanels["logging"],
  };
}

function createHistoryPanelSpy() {
  type HistoryActions = NonNullable<HistoryPanelView["actions"]["value"]>;
  type HistoryModel = NonNullable<HistoryPanelView["model"]["value"]>;

  const actions: HistoryActions[] = [];
  const models: HistoryModel[] = [];

  return {
    actions,
    models,
    mount(view: HistoryPanelView) {
      if (view.actions.value) {
        actions.push(view.actions.value);
      }
      if (view.model.value) {
        models.push(view.model.value);
      }
    },
  };
}

function createSettingsShellSpy() {
  const activations: string[] = [];
  const activeTabId = signal("carTab");

  return {
    activations,
    emit(tabId: string) {
      activeTabId.value = tabId;
    },
    view: {
      activeTabId,
      activateTab(tabId) {
        activeTabId.value = tabId;
        activations.push(tabId);
      },
    } satisfies SettingsShellView,
  };
}

function createInternetPanelSpy() {
  type InternetActions = NonNullable<InternetPanelView["actions"]["value"]>;
  type InternetModel = NonNullable<InternetPanelView["model"]["value"]>;

  const actions: InternetActions[] = [];
  let focusCalls = 0;
  const models: InternetModel[] = [];

  return {
    actions,
    get focusCalls() {
      return focusCalls;
    },
    models,
    handle: {
      focusSsidInput() {
        focusCalls += 1;
      },
    } satisfies Pick<InternetPanelView, "focusSsidInput">,
    mount(view: InternetPanelView) {
      if (view.actions.value) {
        actions.push(view.actions.value);
      }
      if (view.model.value) {
        models.push(view.model.value);
      }
    },
  };
}

function createSpeedSourcePanelSpy() {
  type SpeedSourceActions = NonNullable<SpeedSourcePanelView["actions"]["value"]>;
  type SpeedSourceDiagnostics = NonNullable<SpeedSourcePanelView["diagnostics"]["value"]>;
  type SpeedSourceModel = NonNullable<SpeedSourcePanelView["model"]["value"]>;

  const actions: SpeedSourceActions[] = [];
  const diagnostics: SpeedSourceDiagnostics[] = [];
  let focusManualCalls = 0;
  let focusScanCalls = 0;
  let focusStaleCalls = 0;
  const models: SpeedSourceModel[] = [];
  let mountedView: SpeedSourcePanelView | null = null;

  return {
    actions,
    diagnostics,
    get focusManualCalls() {
      return focusManualCalls;
    },
    get focusScanCalls() {
      return focusScanCalls;
    },
    get focusStaleCalls() {
      return focusStaleCalls;
    },
    isObdConfigVisible() {
      return mountedView?.model.value?.value.obdConfigVisible ?? false;
    },
    models,
    mount(view: SpeedSourcePanelView) {
      mountedView = view;
      if (view.actions.value) {
        actions.push(view.actions.value);
      }
      if (view.diagnostics.value) {
        diagnostics.push(view.diagnostics.value);
      }
      if (view.model.value) {
        models.push(view.model.value);
      }
      return {
        focusManualSpeedInput() {
          focusManualCalls += 1;
        },
        focusScanObdDevices() {
          focusScanCalls += 1;
        },
        focusStaleTimeoutInput() {
          focusStaleCalls += 1;
        },
        isObdConfigVisible() {
          return mountedView?.model.value?.value.obdConfigVisible ?? false;
        },
      } satisfies Pick<
        SpeedSourcePanelView,
        "focusManualSpeedInput" | "focusScanObdDevices" | "focusStaleTimeoutInput" | "isObdConfigVisible"
      >;
    },
  };
}

test.describe("createLazyUiPanels", () => {
  test("mounts dashboard immediately and replays deferred history/settings bindings", async () => {
    const hosts = createFakeHosts();
    const historyPanel = createHistoryPanelSpy();
    const internetPanel = createInternetPanelSpy();
    const settingsShell = createSettingsShellSpy();
    const speedSourcePanel = createSpeedSourcePanelSpy();
    let dashboardMounts = 0;
    let historyLoads = 0;
    let settingsLoads = 0;

    const lazyPanels = createLazyUiPanels({
      hosts,
      mountDashboardPanels: () => {
        dashboardMounts += 1;
        return createDashboardPanels();
      },
      loadHistoryPanel: async (_hosts, view) => {
        historyLoads += 1;
        historyPanel.mount(view);
      },
      loadSettingsPanels: async (_hosts, panels) => {
        settingsLoads += 1;
        internetPanel.mount(panels.settings.internet);
        return {
          settingsShell: settingsShell.view,
          settings: {
            analysis: {
              focusField() {},
              openGuidance() {},
            },
            cars: {
              focus() {},
            },
            internet: internetPanel.handle,
            speedSource: speedSourcePanel.mount(panels.settings.speedSource),
          },
        };
      },
    });

    expect(dashboardMounts).toBe(1);
    expect(historyLoads).toBe(0);
    expect(settingsLoads).toBe(0);

    const historyActions = {} as NonNullable<HistoryPanelView["actions"]["value"]>;
    const historyModel = signal({}) as unknown as NonNullable<HistoryPanelView["model"]["value"]>;
    lazyPanels.panels.history.model.value = historyModel;
    lazyPanels.panels.history.actions.value = historyActions;

    expect(lazyPanels.panels.settingsShell.activeTabId.value).toBe("carTab");
    lazyPanels.panels.settingsShell.activateTab("updateTab");
    expect(lazyPanels.panels.settingsShell.activeTabId.value).toBe("updateTab");

    const internetActions = {} as NonNullable<InternetPanelView["actions"]["value"]>;
    const internetModel = signal({}) as unknown as NonNullable<InternetPanelView["model"]["value"]>;
    const speedSourceActions = {} as NonNullable<SpeedSourcePanelView["actions"]["value"]>;
    const speedSourceDiagnostics = signal({}) as unknown as NonNullable<
      SpeedSourcePanelView["diagnostics"]["value"]
    >;
    const speedSourceModel = signal({
      obdConfigVisible: true,
    }) as unknown as NonNullable<SpeedSourcePanelView["model"]["value"]>;
    lazyPanels.panels.settings.internet.model.value = internetModel;
    lazyPanels.panels.settings.internet.actions.value = internetActions;
    lazyPanels.panels.settings.internet.focusSsidInput();
    lazyPanels.panels.settings.speedSource.model.value = speedSourceModel;
    lazyPanels.panels.settings.speedSource.actions.value = speedSourceActions;
    lazyPanels.panels.settings.speedSource.diagnostics.value = speedSourceDiagnostics;
    lazyPanels.panels.settings.speedSource.focusManualSpeedInput();
    expect(lazyPanels.panels.settings.speedSource.isObdConfigVisible()).toBe(true);
    const readSpeedSourceVisibility = lazyPanels.panels.settings.speedSource.isObdConfigVisible;
    expect(readSpeedSourceVisibility()).toBe(true);

    await lazyPanels.ensureViewPanels("historyView");
    expect(historyLoads).toBe(1);
    expect(historyPanel.models).toEqual([historyModel]);
    expect(historyPanel.actions).toEqual([historyActions]);

    await lazyPanels.ensureViewPanels("settingsView");
    expect(settingsLoads).toBe(1);
    expect(settingsShell.activations).toEqual(["updateTab"]);
    expect(internetPanel.models).toEqual([internetModel]);
    expect(internetPanel.actions).toEqual([internetActions]);
    expect(internetPanel.focusCalls).toBe(1);
    expect(speedSourcePanel.models).toEqual([speedSourceModel]);
    expect(speedSourcePanel.actions).toEqual([speedSourceActions]);
    expect(speedSourcePanel.diagnostics).toEqual([speedSourceDiagnostics]);
    expect(speedSourcePanel.focusManualCalls).toBe(1);
    expect(lazyPanels.panels.settings.speedSource.isObdConfigVisible()).toBe(true);
    expect(readSpeedSourceVisibility()).toBe(true);
    expect(lazyPanels.panels.settingsShell.activeTabId.value).toBe("updateTab");

    lazyPanels.panels.settings.speedSource.focusScanObdDevices();
    lazyPanels.panels.settings.speedSource.focusStaleTimeoutInput();
    expect(speedSourcePanel.focusScanCalls).toBe(1);
    expect(speedSourcePanel.focusStaleCalls).toBe(1);

    settingsShell.emit("internetTab");
    expect(lazyPanels.panels.settingsShell.activeTabId.value).toBe("internetTab");

    await lazyPanels.ensureViewPanels("historyView");
    await lazyPanels.ensureViewPanels("settingsView");
    expect(historyLoads).toBe(1);
    expect(settingsLoads).toBe(1);
  });

  test("prefetchHiddenPanels schedules offscreen mounts through the deferred scheduler", async () => {
    const hosts = createFakeHosts();
    const historyPanel = createHistoryPanelSpy();
    const settingsShell = createSettingsShellSpy();
    const internetPanel = createInternetPanelSpy();
    let historyLoads = 0;
    let scheduledTask: (() => void) | null = null;
    let settingsLoads = 0;

    const lazyPanels = createLazyUiPanels({
      hosts,
      mountDashboardPanels: () => createDashboardPanels(),
      loadHistoryPanel: async (_hosts, view) => {
        historyLoads += 1;
        historyPanel.mount(view);
      },
      loadSettingsPanels: async (_hosts, panels) => {
        settingsLoads += 1;
        internetPanel.mount(panels.settings.internet);
        return {
          settingsShell: settingsShell.view,
          settings: {
            analysis: {
              focusField() {},
              openGuidance() {},
            },
            cars: {
              focus() {},
            },
            internet: internetPanel.handle,
            speedSource: {
              focusManualSpeedInput() {},
              focusScanObdDevices() {},
              focusStaleTimeoutInput() {},
              isObdConfigVisible() {
                return false;
              },
            },
          },
        };
      },
      scheduleDeferredWork: (task) => {
        scheduledTask = task;
      },
    });

    lazyPanels.prefetchHiddenPanels();
    expect(historyLoads).toBe(0);
    expect(settingsLoads).toBe(0);
    expect(scheduledTask).not.toBeNull();

    scheduledTask?.();
    await Promise.resolve();
    expect(historyLoads).toBe(1);
    expect(settingsLoads).toBe(1);

    scheduledTask = null;
    lazyPanels.prefetchHiddenPanels();
    scheduledTask?.();
    await Promise.resolve();
    expect(historyLoads).toBe(1);
    expect(settingsLoads).toBe(1);
  });
});
