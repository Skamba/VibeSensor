import { expect, test } from "@playwright/test";

import { createSettingsAnalysisModule } from "../src/app/features/settings_analysis_module";
import { createAppState } from "../src/app/ui_app_state";
import type {
  AnalysisPanelActionHandlers,
  AnalysisPanelFieldKey,
  AnalysisPanelRenderModel,
  AnalysisPanelView,
} from "../src/app/views/analysis_panel";

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

test("settings analysis module renders guidance and surfaces invalid input through the typed panel bridge", () => {
  const state = createAppState().settings;
  const renders: AnalysisPanelRenderModel[] = [];
  let actions: AnalysisPanelActionHandlers | null = null;
  let focusedField: AnalysisPanelFieldKey | null = null;
  let guidanceOpened = false;

  const panel: AnalysisPanelView = {
    bindActions(nextActions) {
      actions = nextActions;
    },
    focusField(field) {
      focusedField = field;
    },
    openGuidance() {
      guidanceOpened = true;
    },
    setModel(model) {
      renders.push(model);
    },
    setCarAvailability() {
      return;
    },
  };

  const module = createSettingsAnalysisModule({
    panel,
    escapeHtml: (value) => String(value ?? ""),
    hasValidActiveCar: () => true,
    onMissingActiveCar: () => undefined,
    onSaveError: () => undefined,
    renderSpectrum: () => undefined,
    settings: state,
    showError: () => undefined,
    t: translate,
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

  actions?.onFieldInput({
    field: "wheel_bandwidth_pct",
    value: "5",
  });

  const recoveredRender = lastRender(renders);
  expect(recoveredRender.fields.wheel_bandwidth_pct.invalid).toBe(false);
  expect(recoveredRender.fields.wheel_bandwidth_pct.guidance.error).toBeNull();
});
