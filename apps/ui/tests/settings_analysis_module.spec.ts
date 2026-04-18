import { expect, test } from "@playwright/test";

import { createSettingsAnalysisModule } from "../src/app/features/settings_analysis_module";
import { createAppState } from "../src/app/ui_app_state";
import { effect, signal } from "../src/app/ui_signals";
import type {
  AnalysisPanelActionHandlers,
  AnalysisPanelFieldKey,
  AnalysisPanelRenderModel,
  AnalysisPanelView,
} from "../src/app/views/analysis_panel";
import { installWindowGlobal, jsonResponse } from "./async_test_helpers";

function lastRender(renders: AnalysisPanelRenderModel[]): AnalysisPanelRenderModel {
  const render = renders.at(-1);
  if (!render) {
    throw new Error("Expected analysis panel to render");
  }
  return render;
}

function translate(key: string, vars?: Record<string, unknown>): string {
  switch (key) {
    case "settings.analysis.range_value":
      return `${vars?.min}-${vars?.max}${String(vars?.unit ?? "")}`;
    case "settings.analysis.recommended_range_label":
      return "Recommended range";
    case "settings.analysis.default_label":
      return "Default";
    case "settings.wheel_bandwidth":
      return "Wheel bandwidth";
    case "settings.analysis.invalid_number":
      return `${vars?.field ?? "Field"} must be a number`;
    case "settings.analysis.invalid_value":
      return `${vars?.field ?? "Field"} must stay between ${vars?.min ?? "?"} and ${vars?.max ?? "?"}${String(vars?.unit ?? "")}`;
    case "settings.analysis.reset_confirm":
      return "Reset analysis settings?";
    default:
      return key;
  }
}

test.beforeEach(() => {
  installWindowGlobal();
});

test("settings analysis module renders guidance and surfaces invalid input through the typed panel bridge", () => {
  const state = createAppState().settings;
  const renders: AnalysisPanelRenderModel[] = [];
  let actions: AnalysisPanelActionHandlers | null = null;
  let focusedField: AnalysisPanelFieldKey | null = null;
  let guidanceOpened = false;

  const panel: AnalysisPanelView = {
    actions: signal(null),
    carAvailability: signal(null),
    model: signal(null),
    focusField(field) {
      focusedField = field;
    },
    openGuidance() {
      guidanceOpened = true;
    },
  };
  effect(() => {
    actions = panel.actions.value;
  });
  effect(() => {
    const model = panel.model.value;
    if (model === null) {
      return;
    }
    renders.push(model.value);
  });

  const module = createSettingsAnalysisModule({
    panel,
    hasValidActiveCar: () => true,
    onMissingActiveCar: () => undefined,
    onSaveError: () => undefined,
    renderSpectrum: () => undefined,
    settings: state,
    services: {
      t: translate,
      requestConfirmation: async () => true,
      showError: () => undefined,
    },
  });

  module.bindHandlers();

  expect(lastRender(renders).fields.wheel_bandwidth_pct.guidance.lines).toEqual([
    {
      label: "Recommended range",
      value: "2-12%",
    },
    {
      label: "Default",
      value: "5%",
    },
  ]);

  actions?.onFieldInput({
    field: "wheel_bandwidth_pct",
    value: "200",
  });
  module.saveAnalysisFromInputs();

  const invalidRender = lastRender(renders);
  expect(invalidRender.fields.wheel_bandwidth_pct.invalid).toBe(true);
  expect(invalidRender.fields.wheel_bandwidth_pct.guidance.error).toMatchObject({
    body: "Wheel bandwidth must stay between 0.1 and 100%",
    compact: true,
    tone: "error",
  });
  expect(focusedField).toBe("wheel_bandwidth_pct");
  expect(guidanceOpened).toBe(true);

  const rendersBeforeRecovery = renders.length;
  actions?.onFieldInput({
    field: "wheel_bandwidth_pct",
    value: "5",
  });

  expect(renders).toHaveLength(rendersBeforeRecovery + 1);
  const recoveredRender = lastRender(renders);
  expect(recoveredRender.fields.wheel_bandwidth_pct.invalid).toBe(false);
  expect(recoveredRender.fields.wheel_bandwidth_pct.guidance.error).toBeNull();
});

test("settings analysis module keeps active-car geometry when loading server analysis settings", async () => {
  const originalFetch = globalThis.fetch;
  const state = createAppState().settings;
  let renderSpectrumCalls = 0;

  state.vehicleSettings.value = {
    ...state.vehicleSettings.value,
    tire_width_mm: 245,
    tire_aspect_pct: 40,
    rim_in: 19,
    final_drive_ratio: 3.23,
    current_gear_ratio: 0.72,
    tire_deflection_factor: 0.95,
    wheel_bandwidth_pct: 5,
    speed_uncertainty_pct: 1,
    min_abs_band_hz: 0.2,
  };

  globalThis.fetch = (async () =>
    jsonResponse({
      tire_width_mm: 999,
      tire_aspect_pct: 99,
      rim_in: 24,
      final_drive_ratio: 9.99,
      current_gear_ratio: 2.22,
      tire_deflection_factor: 0.5,
      wheel_bandwidth_pct: 7.5,
      speed_uncertainty_pct: 2.5,
      min_abs_band_hz: 1.5,
    })) as typeof fetch;

  const module = createSettingsAnalysisModule({
    panel: {
      actions: signal(null),
      carAvailability: signal(null),
      model: signal(null),
      focusField: () => undefined,
      openGuidance: () => undefined,
    },
    hasValidActiveCar: () => true,
    onMissingActiveCar: () => undefined,
    onSaveError: () => undefined,
    renderSpectrum: () => {
      renderSpectrumCalls += 1;
    },
    settings: state,
    services: {
      t: translate,
      requestConfirmation: async () => true,
      showError: () => undefined,
    },
  });

  try {
    await module.loadAnalysisSettingsFromServer();
  } finally {
    globalThis.fetch = originalFetch;
  }

  expect(state.vehicleSettings.value).toMatchObject({
    tire_width_mm: 245,
    tire_aspect_pct: 40,
    rim_in: 19,
    final_drive_ratio: 3.23,
    current_gear_ratio: 0.72,
    tire_deflection_factor: 0.95,
    wheel_bandwidth_pct: 7.5,
    speed_uncertainty_pct: 2.5,
    min_abs_band_hz: 1.5,
  });
  expect(renderSpectrumCalls).toBe(1);
});
