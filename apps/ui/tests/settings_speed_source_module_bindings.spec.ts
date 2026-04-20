import { expect, test } from "vitest";
import { createSettingsSpeedSourceModule } from "../src/app/features/settings_speed_source_module";
import { createAppState } from "../src/app/ui_app_state";
import { signal } from "../src/app/ui_signals";
import type { SpeedSourcePanelActionHandlers } from "../src/app/views/speed_source_panel";

test("bindHandlers uses typed panel actions and navigation subscriptions", () => {
  const activeViewId = signal("settingsView");
  const activeSettingsTabId = signal("speedSourceTab");
  const panel = {
    actions: signal<SpeedSourcePanelActionHandlers | null>(null),
    diagnostics: signal(null),
    model: signal(null),
    focusManualSpeedInput() {},
    focusScanObdDevices() {},
    focusStaleTimeoutInput() {},
    isObdConfigVisible() {
      return false;
    },
  };

  const module = createSettingsSpeedSourceModule({
    settings: createAppState().settings,
    panel,
    services: {
      t: (key) => key,
      requestConfirmation: async () => true,
      showError() {},
    },
    formatting: {
      fmt: (value) => String(value),
    },
    getSpeedUnit: () => "kmh",
    ports: {
      activeViewId,
      activeSettingsTabId,
    },
  });

  expect(() => module.bindHandlers()).not.toThrow();
  const handlers = panel.actions.value;
  expect(handlers).not.toBeNull();
  expect(typeof handlers?.onSpeedSourceChanged).toBe("function");
  expect(typeof handlers?.onManualSpeedInput).toBe("function");
  expect(typeof handlers?.onStaleTimeoutInput).toBe("function");
  expect(typeof handlers?.onSave).toBe("function");
  expect(typeof handlers?.onScanObdDevices).toBe("function");
  expect(typeof handlers?.onPairObdDevice).toBe("function");

  expect(() => {
    handlers?.onSpeedSourceChanged("manual");
    handlers?.onManualSpeedInput("80");
    handlers?.onStaleTimeoutInput("5");
    activeSettingsTabId.value = "analysisTab";
    activeViewId.value = "dashboardView";
  }).not.toThrow();
});
