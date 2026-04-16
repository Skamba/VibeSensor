import { expect, test } from "@playwright/test";

import { createLazyUiPanels } from "../src/app/ui_lazy_panels";
import type { UiMountedDashboardPanels } from "../src/app/ui_panel_bootstrap";
import type { UiPanelHostRegistry } from "../src/app/ui_panel_host_registry";
import { signal } from "../src/app/ui_signals";
import type { HistoryPanelView } from "../src/app/views/history_table_view";
import type { InternetPanelView } from "../src/app/views/internet_panel";
import type { SettingsShellView } from "../src/app/views/settings_shell";

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
    resolveSettingsPanels() {
      return {
        cars: fakeElement(),
        analysis: fakeElement(),
        internet: fakeElement(),
        update: fakeElement(),
        sensors: fakeElement(),
        speedSource: fakeElement(),
        espFlash: fakeElement(),
      };
    },
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
  let activeTabId = "carTab";
  let listener: ((tabId: string) => void) | null = null;

  return {
    activations,
    emit(tabId: string) {
      activeTabId = tabId;
      listener?.(tabId);
    },
    view: {
      activateTab(tabId) {
        activeTabId = tabId;
        activations.push(tabId);
      },
      getActiveTabId() {
        return activeTabId;
      },
      subscribeActiveTabChanges(nextListener) {
        listener = nextListener;
        return () => {
          if (listener === nextListener) {
            listener = null;
          }
        };
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

test.describe("createLazyUiPanels", () => {
  test("mounts dashboard immediately and replays deferred history/settings bindings", async () => {
    const hosts = createFakeHosts();
    const historyPanel = createHistoryPanelSpy();
    const internetPanel = createInternetPanelSpy();
    const settingsShell = createSettingsShellSpy();
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
            speedSource: {} as ReturnType<typeof createLazyUiPanels>["panels"]["settings"]["speedSource"],
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

    const tabChanges: string[] = [];
    const dispose = lazyPanels.panels.settingsShell.subscribeActiveTabChanges((tabId) => {
      tabChanges.push(tabId);
    });
    lazyPanels.panels.settingsShell.activateTab("updateTab");

    const internetActions = {} as Parameters<InternetPanelView["bindActions"]>[0];
    const internetModel = signal({}) as unknown as Parameters<InternetPanelView["bindModel"]>[0];
    lazyPanels.panels.settings.internet.bindModel(internetModel);
    lazyPanels.panels.settings.internet.bindActions(internetActions);
    lazyPanels.panels.settings.internet.focusSsidInput();

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
    expect(tabChanges).toEqual(["updateTab"]);

    settingsShell.emit("internetTab");
    expect(lazyPanels.panels.settingsShell.getActiveTabId()).toBe("internetTab");
    expect(tabChanges).toEqual(["updateTab", "internetTab"]);

    await lazyPanels.ensureViewPanels("historyView");
    await lazyPanels.ensureViewPanels("settingsView");
    expect(historyLoads).toBe(1);
    expect(settingsLoads).toBe(1);

    dispose();
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
