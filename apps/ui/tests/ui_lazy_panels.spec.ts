import { describe, expect, test } from "vitest";
import { createLazyUiPanels } from "../src/app/ui_lazy_panels";
import { signal } from "../src/app/ui_signals";
import type { AnalysisPanelView } from "../src/app/views/analysis_panel";
import type { CarsPanelView } from "../src/app/views/cars_panel";
import type { HistoryPanelView } from "../src/app/views/history_table_view";
import type { InternetPanelView } from "../src/app/views/internet_panel";
import type { SettingsShellView } from "../src/app/views/settings_shell";
import type { SpeedSourcePanelView } from "../src/app/views/speed_source_panel";

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

function createAnalysisPanelSpy() {
  const focusFields: Array<Parameters<AnalysisPanelView["focusField"]>[0]> = [];
  let guidanceOpens = 0;

  return {
    focusFields,
    get guidanceOpens() {
      return guidanceOpens;
    },
    handle: {
      focusField(field) {
        focusFields.push(field);
      },
      openGuidance() {
        guidanceOpens += 1;
      },
    } satisfies Pick<AnalysisPanelView, "focusField" | "openGuidance">,
  };
}

function createCarsPanelSpy() {
  const focusTargets: Array<Parameters<CarsPanelView["wizard"]["focus"]>[0]> =
    [];

  return {
    focusTargets,
    handle: {
      focus(target) {
        focusTargets.push(target);
      },
    } satisfies Pick<CarsPanelView["wizard"], "focus">,
  };
}

function createInternetPanelSpy() {
  let focusCalls = 0;

  return {
    get focusCalls() {
      return focusCalls;
    },
    handle: {
      focusSsidInput() {
        focusCalls += 1;
      },
    } satisfies Pick<InternetPanelView, "focusSsidInput">,
  };
}

function createSpeedSourcePanelSpy() {
  let focusManualCalls = 0;
  let focusScanCalls = 0;
  let focusStaleCalls = 0;

  return {
    get focusManualCalls() {
      return focusManualCalls;
    },
    get focusScanCalls() {
      return focusScanCalls;
    },
    get focusStaleCalls() {
      return focusStaleCalls;
    },
    handle: {
      focusManualSpeedInput() {
        focusManualCalls += 1;
      },
      focusScanObdDevices() {
        focusScanCalls += 1;
      },
      focusStaleTimeoutInput() {
        focusStaleCalls += 1;
      },
    } satisfies Pick<
      SpeedSourcePanelView,
      "focusManualSpeedInput" | "focusScanObdDevices" | "focusStaleTimeoutInput"
    >,
  };
}

describe("createLazyUiPanels", () => {
  test("replays deferred settings shell and focus bindings after settings attach", () => {
    const analysisPanel = createAnalysisPanelSpy();
    const carsPanel = createCarsPanelSpy();
    const internetPanel = createInternetPanelSpy();
    const settingsShell = createSettingsShellSpy();
    const speedSourcePanel = createSpeedSourcePanelSpy();
    const lazyPanels = createLazyUiPanels();

    const historyActions = {} as NonNullable<
      HistoryPanelView["actions"]["value"]
    >;
    const historyModel = signal({}) as unknown as NonNullable<
      HistoryPanelView["model"]["value"]
    >;
    lazyPanels.panels.history.model.value = historyModel;
    lazyPanels.panels.history.actions.value = historyActions;

    expect(lazyPanels.panels.settingsShell.activeTabId.value).toBe("carTab");
    lazyPanels.panels.settingsShell.activateTab("updateTab");

    const internetActions = {} as NonNullable<
      InternetPanelView["actions"]["value"]
    >;
    const internetModel = signal({}) as unknown as NonNullable<
      InternetPanelView["model"]["value"]
    >;
    const speedSourceActions = {} as NonNullable<
      SpeedSourcePanelView["actions"]["value"]
    >;
    const speedSourceDiagnostics = signal({}) as unknown as NonNullable<
      SpeedSourcePanelView["diagnostics"]["value"]
    >;
    const speedSourceModel = signal({
      obdConfigVisible: true,
    }) as unknown as NonNullable<SpeedSourcePanelView["model"]["value"]>;

    lazyPanels.panels.settings.internet.model.value = internetModel;
    lazyPanels.panels.settings.internet.actions.value = internetActions;
    lazyPanels.panels.settings.internet.focusSsidInput();
    lazyPanels.panels.settings.analysis.openGuidance();
    lazyPanels.panels.settings.analysis.focusField("wheel_bandwidth_pct");
    lazyPanels.panels.settings.cars.wizard.focus("finish");
    lazyPanels.panels.settings.speedSource.model.value = speedSourceModel;
    lazyPanels.panels.settings.speedSource.actions.value = speedSourceActions;
    lazyPanels.panels.settings.speedSource.diagnostics.value =
      speedSourceDiagnostics;
    lazyPanels.panels.settings.speedSource.focusManualSpeedInput();

    expect(lazyPanels.panels.settings.speedSource.isObdConfigVisible()).toBe(
      true,
    );

    lazyPanels.attachSettingsPanels({
      settingsShell: settingsShell.view,
      settings: {
        analysis: analysisPanel.handle,
        cars: carsPanel.handle,
        internet: internetPanel.handle,
        speedSource: speedSourcePanel.handle,
      },
    });

    expect(settingsShell.activations).toEqual(["updateTab"]);
    expect(analysisPanel.guidanceOpens).toBe(1);
    expect(analysisPanel.focusFields).toEqual(["wheel_bandwidth_pct"]);
    expect(carsPanel.focusTargets).toEqual(["finish"]);
    expect(internetPanel.focusCalls).toBe(1);
    expect(speedSourcePanel.focusManualCalls).toBe(1);
    expect(lazyPanels.panels.settings.speedSource.isObdConfigVisible()).toBe(
      true,
    );
    expect(lazyPanels.panels.settingsShell.activeTabId.value).toBe("updateTab");

    lazyPanels.panels.settings.speedSource.focusScanObdDevices();
    lazyPanels.panels.settings.speedSource.focusStaleTimeoutInput();
    lazyPanels.panels.settings.analysis.openGuidance();
    lazyPanels.panels.settings.analysis.focusField("speed_uncertainty_pct");
    lazyPanels.panels.settings.cars.wizard.focus("close");

    expect(analysisPanel.guidanceOpens).toBe(2);
    expect(analysisPanel.focusFields).toEqual([
      "wheel_bandwidth_pct",
      "speed_uncertainty_pct",
    ]);
    expect(carsPanel.focusTargets).toEqual(["finish", "close"]);
    expect(speedSourcePanel.focusScanCalls).toBe(1);
    expect(speedSourcePanel.focusStaleCalls).toBe(1);

    settingsShell.emit("internetTab");
    expect(lazyPanels.panels.settingsShell.activeTabId.value).toBe(
      "internetTab",
    );
  });

  test("dispose prevents deferred settings replays after teardown", () => {
    const analysisPanel = createAnalysisPanelSpy();
    const carsPanel = createCarsPanelSpy();
    const internetPanel = createInternetPanelSpy();
    const settingsShell = createSettingsShellSpy();
    const speedSourcePanel = createSpeedSourcePanelSpy();
    const lazyPanels = createLazyUiPanels();

    lazyPanels.panels.settingsShell.activateTab("updateTab");
    lazyPanels.panels.settings.analysis.openGuidance();
    lazyPanels.panels.settings.analysis.focusField("wheel_bandwidth_pct");
    lazyPanels.panels.settings.cars.wizard.focus("finish");
    lazyPanels.panels.settings.internet.focusSsidInput();
    lazyPanels.panels.settings.speedSource.focusManualSpeedInput();
    lazyPanels.dispose();

    lazyPanels.attachSettingsPanels({
      settingsShell: settingsShell.view,
      settings: {
        analysis: analysisPanel.handle,
        cars: carsPanel.handle,
        internet: internetPanel.handle,
        speedSource: speedSourcePanel.handle,
      },
    });

    expect(settingsShell.activations).toEqual([]);
    expect(analysisPanel.guidanceOpens).toBe(0);
    expect(analysisPanel.focusFields).toEqual([]);
    expect(carsPanel.focusTargets).toEqual([]);
    expect(internetPanel.focusCalls).toBe(0);
    expect(speedSourcePanel.focusManualCalls).toBe(0);
  });
});
