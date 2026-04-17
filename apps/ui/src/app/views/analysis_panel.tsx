import { render } from "preact";
import { useRef } from "preact/hooks";

import { getUiText as t } from "../ui_i18n";
import {
  computed,
  signal,
  useSignalEffect,
  type ReadonlySignal,
} from "../ui_signals";
import {
  ORDER_BAND_FIELDS,
  UNCERTAINTY_FIELDS,
  type AnalysisPanelActionHandlers,
  type AnalysisPanelCarAvailability,
  type AnalysisPanelFieldKey,
  type AnalysisPanelRenderModel,
  type SettingsAnalysisGuidanceRenderModel,
} from "./analysis_panel_models";
import {
  AnalysisFieldGroup,
  AnalysisGuidanceDialog,
  AnalysisSaveFeedback,
} from "./analysis_panel_sections";

export type {
  AnalysisPanelActionHandlers,
  AnalysisPanelCarAvailability,
  AnalysisPanelFieldKey,
  AnalysisPanelRenderModel,
  SettingsAnalysisGuidanceLine,
  SettingsAnalysisGuidanceRenderModel,
} from "./analysis_panel_models";

export interface AnalysisPanelView {
  bindActions(handlers: AnalysisPanelActionHandlers): void;
  bindCarAvailability(state: ReadonlySignal<AnalysisPanelCarAvailability>): void;
  bindModel(model: ReadonlySignal<AnalysisPanelRenderModel>): void;
  focusField(field: AnalysisPanelFieldKey): void;
  openGuidance(): void;
}

type AnalysisPanelBridgeState = {
  actions: AnalysisPanelActionHandlers | null;
  availability: AnalysisPanelCarAvailability;
  model: AnalysisPanelRenderModel;
};

type AnalysisFieldFocusRequest = {
  field: AnalysisPanelFieldKey;
  token: number;
};

const EMPTY_GUIDANCE_MODEL: SettingsAnalysisGuidanceRenderModel = {
  error: null,
  lines: [],
};

const DEFAULT_ANALYSIS_PANEL_MODEL: AnalysisPanelRenderModel = {
  fields: {
    wheel_bandwidth_pct: {
      guidance: EMPTY_GUIDANCE_MODEL,
      invalid: false,
      value: "",
    },
    driveshaft_bandwidth_pct: {
      guidance: EMPTY_GUIDANCE_MODEL,
      invalid: false,
      value: "",
    },
    engine_bandwidth_pct: {
      guidance: EMPTY_GUIDANCE_MODEL,
      invalid: false,
      value: "",
    },
    speed_uncertainty_pct: {
      guidance: EMPTY_GUIDANCE_MODEL,
      invalid: false,
      value: "",
    },
    tire_diameter_uncertainty_pct: {
      guidance: EMPTY_GUIDANCE_MODEL,
      invalid: false,
      value: "",
    },
    final_drive_uncertainty_pct: {
      guidance: EMPTY_GUIDANCE_MODEL,
      invalid: false,
      value: "",
    },
    gear_uncertainty_pct: {
      guidance: EMPTY_GUIDANCE_MODEL,
      invalid: false,
      value: "",
    },
    min_abs_band_hz: {
      guidance: EMPTY_GUIDANCE_MODEL,
      invalid: false,
      value: "",
    },
    max_band_half_width_pct: {
      guidance: EMPTY_GUIDANCE_MODEL,
      invalid: false,
      value: "",
    },
  },
  saveFeedback: null,
};

const DEFAULT_ANALYSIS_CAR_AVAILABILITY: AnalysisPanelCarAvailability = {
  hasActiveCar: true,
  isLoading: false,
};

function AnalysisPanel(props: {
  guidanceOpenRequest: ReadonlySignal<number>;
  inputFocusRequest: ReadonlySignal<AnalysisFieldFocusRequest | null>;
  state: ReadonlySignal<AnalysisPanelBridgeState>;
}) {
  const state = props.state.value;
  const guidanceHelpRef = useRef<HTMLDetailsElement | null>(null);
  const inputRefs = useRef<Record<AnalysisPanelFieldKey, HTMLInputElement | null>>({
    wheel_bandwidth_pct: null,
    driveshaft_bandwidth_pct: null,
    engine_bandwidth_pct: null,
    speed_uncertainty_pct: null,
    tire_diameter_uncertainty_pct: null,
    final_drive_uncertainty_pct: null,
    gear_uncertainty_pct: null,
    min_abs_band_hz: null,
    max_band_half_width_pct: null,
  });

  useSignalEffect(() => {
    const inputFocusRequest = props.inputFocusRequest.value;
    if (!inputFocusRequest) {
      return;
    }
    inputRefs.current[inputFocusRequest.field]?.focus();
  });

  useSignalEffect(() => {
    const guidanceOpenRequest = props.guidanceOpenRequest.value;
    if (guidanceOpenRequest <= 0) {
      return;
    }
    if (guidanceHelpRef.current) {
      guidanceHelpRef.current.open = true;
    }
  });

  const noCarSelected = !state.availability.hasActiveCar && !state.availability.isLoading;
  return (
    <div class="panel card settings-layout">
      <AnalysisGuidanceDialog guidanceHelpRef={guidanceHelpRef} />
      <div
        id="analysisNoCarMessage"
        class="empty-state empty-state--inline"
        hidden={!noCarSelected}

      >
        {t(
          "settings.analysis.no_car_selected",
          "No car selected. Select or create a car in Settings → Car to save analysis settings.",
        )}
      </div>
      <div class="settings-groups">
        <AnalysisFieldGroup
          actions={state.actions}
          fields={ORDER_BAND_FIELDS}
          helpBody={[
            {
              key: "settings.analysis.group.order_band_widths_help",
              fallback:
                "These values control how far the app searches around each expected order. Wider bands tolerate more speed drift but can blend nearby faults together.",
            },
          ]}
          helpId="analysisOrderBandHelp"
          inputRefs={inputRefs.current}
          modelFields={state.model.fields}
          titleFallback="Order Band Widths"
          titleKey="settings.group.order_band_widths"
        />
        <AnalysisFieldGroup
          actions={state.actions}
          fields={UNCERTAINTY_FIELDS}
          helpBody={[
            {
              key: "settings.uncertainty_defaults",
              fallback:
                "Defaults use tire wear from 10/32 in to 2/32 in plus safety margin.",
            },
            {
              key: "settings.analysis.group.uncertainty_model_help",
              fallback:
                "Use these only when vehicle data is approximate, modified, or worn. Higher uncertainty makes matching more tolerant, but it can lower specificity and confidence.",
            },
          ]}
          helpId="analysisUncertaintyHelp"
          inputRefs={inputRefs.current}
          modelFields={state.model.fields}
          subgridClassName="settings-subgrid settings-subgrid--aligned-labels"
          titleFallback="Uncertainty Model"
          titleKey="settings.group.uncertainty_model"
        />
      </div>
      <AnalysisSaveFeedback message={state.model.saveFeedback} />
      <div class="settings-actions settings-actions--sticky">
        <button
          id="resetAnalysisBtn"
          type="button"
          class="btn"

          disabled={!state.availability.hasActiveCar}
          onClick={() => state.actions?.onReset()}
        >
          {t("settings.analysis.reset", "Reset to defaults")}
        </button>
        <button
          id="saveAnalysisBtn"
          type="button"
          class="btn btn--primary"

          disabled={!state.availability.hasActiveCar}
          onClick={() => state.actions?.onSave()}
        >
          {t("settings.analysis.save", "Save Analysis Settings")}
        </button>
      </div>
    </div>
  );
}

export function mountAnalysisPanel(host: HTMLElement): AnalysisPanelView {
  const actions = signal<AnalysisPanelActionHandlers | null>(null);
  const availabilitySignal = signal<ReadonlySignal<AnalysisPanelCarAvailability> | null>(null);
  const modelSignal = signal<ReadonlySignal<AnalysisPanelRenderModel> | null>(null);
  const bridgeState = computed<AnalysisPanelBridgeState>(() => ({
    actions: actions.value,
    availability: availabilitySignal.value?.value ?? DEFAULT_ANALYSIS_CAR_AVAILABILITY,
    model: modelSignal.value?.value ?? DEFAULT_ANALYSIS_PANEL_MODEL,
  }));
  const inputFocusRequest = signal<AnalysisFieldFocusRequest | null>(null);
  const guidanceOpenRequest = signal(0);
  let focusRequestToken = 0;
  render(
    <AnalysisPanel
      guidanceOpenRequest={guidanceOpenRequest}
      inputFocusRequest={inputFocusRequest}
      state={bridgeState}
    />,
    host,
  );

  return {
    bindActions(handlers) {
      actions.value = handlers;
    },
    bindCarAvailability(state) {
      availabilitySignal.value = state;
    },
    bindModel(model) {
      modelSignal.value = model;
    },
    focusField(field) {
      focusRequestToken += 1;
      inputFocusRequest.value = { field, token: focusRequestToken };
    },
    openGuidance() {
      guidanceOpenRequest.value += 1;
    },
  };
}
