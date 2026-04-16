import { expect, test } from "@playwright/test";

import { createSettingsCarsModule } from "../src/app/features/settings_cars_module";
import { effect, signal } from "../src/app/ui_signals";
import type { CarsListRenderModel, CarsListPanelView } from "../src/app/views/cars_panel";
import { createAppState } from "../src/app/ui_app_state";
import type { CarsPayload } from "../src/transport/http_models";

function lastRender(renders: CarsListRenderModel[]): CarsListRenderModel {
  const render = renders.at(-1);
  if (!render) {
    throw new Error("Expected cars panel to render");
  }
  return render;
}

test("settings cars module dismisses transient creation feedback through typed tab and view callbacks", () => {
  const state = createAppState().settings;
  const renders: CarsListRenderModel[] = [];
  const activeViewId = signal("settingsView");
  let settingsTabListener: ((tabId: string) => void) | null = null;

  const panel: CarsListPanelView = {
    bindActions() {},
    bindModel(model) {
      effect(() => {
        renders.push(model.value);
      });
    },
  };

  const module = createSettingsCarsModule({
    settings: state,
    panels: {
      analysisPanel: {
        bindCarAvailability() {
          return;
        },
      },
      panel,
    },
    ports: {
      activeViewId,
      openAnalysisTab: () => undefined,
      openCarWizard: () => undefined,
      renderSpectrum: () => undefined,
      subscribeSettingsTabChanges(listener) {
        settingsTabListener = listener;
        return () => {
          if (settingsTabListener === listener) {
            settingsTabListener = null;
          }
        };
      },
      syncAnalysisInputs: () => undefined,
    },
    services: {
      t: (key, vars) => {
        if (key === "settings.car.created_body") {
          return `${vars?.name ?? "Unknown"} was added and selected for this setup.`;
        }
        return key;
      },
      requestConfirmation: async () => true,
      showError: () => undefined,
    },
    formatting: {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
    },
  });

  const payload: CarsPayload = {
    active_car_id: "car-1",
    cars: [{
      id: "car-1",
      name: "Track Demo",
      type: "Coupe",
      variant: null,
      aspects: {
        tire_width_mm: 225,
        tire_aspect_pct: 45,
        rim_in: 18,
        final_drive_ratio: 3.08,
        current_gear_ratio: 0.64,
      },
    }],
  };

  module.bindHandlers();
  module.syncCarsPayload(payload);
  module.showCarCreationSuccess("car-1", "Track Demo");

  const highlighted = lastRender(renders);
  expect(highlighted.guidance).toMatchObject({
    titleText: "settings.car.created_title",
    tone: "success",
  });
  expect(highlighted.table?.kind).toBe("rows");
  if (highlighted.table?.kind !== "rows") {
    return;
  }
  expect(highlighted.table.rows[0].isHighlighted).toBe(true);
  expect(highlighted.table.rows[0].highlightedStatusText).toBe("settings.car.just_added");

  settingsTabListener?.("analysisTab");

  const dismissedByTab = lastRender(renders);
  expect(dismissedByTab.guidance).toBeNull();
  expect(dismissedByTab.table?.kind).toBe("rows");
  if (dismissedByTab.table?.kind !== "rows") {
    return;
  }
  expect(dismissedByTab.table.rows[0].isHighlighted).toBe(false);
  expect(dismissedByTab.table.rows[0].highlightedStatusText).toBeNull();

  module.showCarCreationSuccess("car-1", "Track Demo");
  activeViewId.value = "dashboardView";

  const dismissedByView = lastRender(renders);
  expect(dismissedByView.guidance).toBeNull();
  expect(dismissedByView.table?.kind).toBe("rows");
  if (dismissedByView.table?.kind !== "rows") {
    return;
  }
  expect(dismissedByView.table.rows[0].isHighlighted).toBe(false);
  expect(dismissedByView.table.rows[0].highlightedStatusText).toBeNull();
});
