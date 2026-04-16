import { expect, test } from "@playwright/test";

import { createSettingsSpeedSourceModule } from "../src/app/features/settings_speed_source_module";
import { createAppState } from "../src/app/ui_app_state";
import { signal } from "../src/app/ui_signals";
import type { SpeedSourcePanelActionHandlers } from "../src/app/views/speed_source_panel";

test("bindHandlers uses typed panel actions and navigation subscriptions", () => {
  let handlers: SpeedSourcePanelActionHandlers | null = null;
  const activeViewId = signal("settingsView");
  let settingsTabListener: ((tabId: string) => void) | null = null;

  const module = createSettingsSpeedSourceModule({
    settings: createAppState().settings,
    panel: {
      bindActions(nextHandlers) {
        handlers = nextHandlers;
      },
      focusManualSpeedInput() {},
      focusScanObdDevices() {},
      focusStaleTimeoutInput() {},
      isObdConfigVisible() {
        return false;
      },
      bindModel() {},
      bindDiagnostics() {},
    },
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
      renderSpeedReadout() {},
      subscribeSettingsTabChanges(listener) {
        settingsTabListener = listener;
        return () => undefined;
      },
    },
  });

  expect(() => module.bindHandlers()).not.toThrow();
  expect(handlers).not.toBeNull();
  expect(typeof handlers?.onSpeedSourceChanged).toBe("function");
  expect(typeof handlers?.onManualSpeedInput).toBe("function");
  expect(typeof handlers?.onStaleTimeoutInput).toBe("function");
  expect(typeof handlers?.onSave).toBe("function");
  expect(typeof handlers?.onScanObdDevices).toBe("function");
  expect(typeof handlers?.onPairObdDevice).toBe("function");
  expect(settingsTabListener).not.toBeNull();

  expect(() => {
    handlers?.onSpeedSourceChanged("manual");
    handlers?.onManualSpeedInput("80");
    handlers?.onStaleTimeoutInput("5");
    settingsTabListener?.("analysisTab");
    activeViewId.value = "dashboardView";
  }).not.toThrow();
});
