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
      setSpeedText() {
        return undefined;
      },
    } as UiMountedDashboardPanels["liveOverview"],
    logging: {} as UiMountedDashboardPanels["logging"],
  };
}

function createHistoryPanelSpy() {
  type HistoryActions = Parameters<HistoryPanelView["bindActions"]>[0];
  type HistoryModel = Parameters<HistoryPanelView["bindModel"]>[0];

  const actions: HistoryActions[] = [];
  const models: HistoryModel[] = [];

  return {
    actions,
    models,
    view: {
      bindActions(nextActions) {
        actions.push(nextActions);
      },
      bindModel(nextModel) {
        models.push(nextModel);
      },
    } satisfies HistoryPanelView,
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
  type InternetActions = Parameters<InternetPanelView["bindActions"]>[0];
  type InternetModel = Parameters<InternetPanelView["bindModel"]>[0];

  const actions: InternetActions[] = [];
  let focusCalls = 0;
  const models: InternetModel[] = [];

  return {
    actions,
    get focusCalls() {
      return focusCalls;
    },
    models,
    view: {
      bindActions(nextActions) {
        actions.push(nextActions);
      },
      bindModel(nextModel) {
        models.push(nextModel);
      },
      focusSsidInput() {
        focusCalls += 1;
      },
    } satisfies InternetPanelView,
  };
}

function createSpeedSourcePanelSpy() {
  type SpeedSourceActions = Parameters<SpeedSourcePanelView["bindActions"]>[0];
  type SpeedSourceDiagnostics = Parameters<SpeedSourcePanelView["bindDiagnostics"]>[0];
  type SpeedSourceModel = Parameters<SpeedSourcePanelView["bindModel"]>[0];

  const actions: SpeedSourceActions[] = [];
  const diagnostics: SpeedSourceDiagnostics[] = [];
  let focusManualCalls = 0;
  let focusScanCalls = 0;
  let focusStaleCalls = 0;
  const models: SpeedSourceModel[] = [];
  let obdConfigVisible = false;

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
      return obdConfigVisible;
    },
    models,
    view: {
      bindActions(nextActions) {
        actions.push(nextActions);
      },
      bindDiagnostics(nextDiagnostics) {
        diagnostics.push(nextDiagnostics);
      },
      bindModel(nextModel) {
        models.push(nextModel);
        obdConfigVisible = nextModel.value.obdConfigVisible;
      },
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
        return obdConfigVisible;
      },
    } satisfies SpeedSourcePanelView,
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
      loadHistoryPanel: async () => {
        historyLoads += 1;
        return historyPanel.view;
      },
      loadSettingsPanels: async () => {
        settingsLoads += 1;
        return {
          settingsShell: settingsShell.view,
          settings: {
            cars: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["cars"],
            analysis: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["analysis"],
            internet: internetPanel.view,
            update: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["update"],
            sensors: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["sensors"],
            speedSource: speedSourcePanel.view,
            espFlash: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["espFlash"],
          },
        };
      },
    });

    expect(dashboardMounts).toBe(1);
    expect(historyLoads).toBe(0);
    expect(settingsLoads).toBe(0);

    const historyActions = {} as Parameters<HistoryPanelView["bindActions"]>[0];
    const historyModel = signal({}) as unknown as Parameters<HistoryPanelView["bindModel"]>[0];
    lazyPanels.panels.history.bindModel(historyModel);
    lazyPanels.panels.history.bindActions(historyActions);

    expect(lazyPanels.panels.settingsShell.activeTabId.value).toBe("carTab");
    lazyPanels.panels.settingsShell.activateTab("updateTab");
    expect(lazyPanels.panels.settingsShell.activeTabId.value).toBe("updateTab");

    const internetActions = {} as Parameters<InternetPanelView["bindActions"]>[0];
    const internetModel = signal({}) as unknown as Parameters<InternetPanelView["bindModel"]>[0];
    const speedSourceActions = {} as Parameters<SpeedSourcePanelView["bindActions"]>[0];
    const speedSourceDiagnostics = signal({}) as unknown as Parameters<SpeedSourcePanelView["bindDiagnostics"]>[0];
    const speedSourceModel = signal({
      obdConfigVisible: true,
    }) as unknown as Parameters<SpeedSourcePanelView["bindModel"]>[0];
    lazyPanels.panels.settings.internet.bindModel(internetModel);
    lazyPanels.panels.settings.internet.bindActions(internetActions);
    lazyPanels.panels.settings.internet.focusSsidInput();
    lazyPanels.panels.settings.speedSource.bindModel(speedSourceModel);
    lazyPanels.panels.settings.speedSource.bindActions(speedSourceActions);
    lazyPanels.panels.settings.speedSource.bindDiagnostics(speedSourceDiagnostics);
    lazyPanels.panels.settings.speedSource.focusManualSpeedInput();
    expect(lazyPanels.panels.settings.speedSource.isObdConfigVisible()).toBe(true);

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
      loadHistoryPanel: async () => {
        historyLoads += 1;
        return historyPanel.view;
      },
      loadSettingsPanels: async () => {
        settingsLoads += 1;
        return {
          settingsShell: settingsShell.view,
          settings: {
            cars: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["cars"],
            analysis: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["analysis"],
            internet: internetPanel.view,
            update: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["update"],
            sensors: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["sensors"],
            speedSource: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["speedSource"],
            espFlash: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["espFlash"],
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
