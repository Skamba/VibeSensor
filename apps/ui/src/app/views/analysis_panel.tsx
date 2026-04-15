import type { JSX } from "preact";
import { useEffect, useRef } from "preact/hooks";

import { createUiPreactMount } from "../runtime/ui_preact_mount";
import { useUiTranslation } from "../ui_i18n";
import { signal, type ReadonlySignal } from "../ui_signals";
import type {
  SettingsAnalysisGuidanceRenderModel,
} from "./settings_analysis_guidance";
import {
  settingsFeedbackClassName,
  type SettingsFeedbackMessage,
} from "./settings_feedback";

export type AnalysisPanelFieldKey =
  | "wheel_bandwidth_pct"
  | "driveshaft_bandwidth_pct"
  | "engine_bandwidth_pct"
  | "speed_uncertainty_pct"
  | "tire_diameter_uncertainty_pct"
  | "final_drive_uncertainty_pct"
  | "gear_uncertainty_pct"
  | "min_abs_band_hz"
  | "max_band_half_width_pct";

export interface AnalysisPanelFieldRenderModel {
  guidance: SettingsAnalysisGuidanceRenderModel;
  invalid: boolean;
  value: string;
}

export interface AnalysisPanelRenderModel {
  fields: Record<AnalysisPanelFieldKey, AnalysisPanelFieldRenderModel>;
  saveFeedback: SettingsFeedbackMessage | null;
}

export interface AnalysisPanelCarAvailability {
  hasActiveCar: boolean;
  isLoading: boolean;
}

export interface AnalysisPanelActionHandlers {
  onFieldInput(action: { field: AnalysisPanelFieldKey; value: string }): void;
  onReset(): void;
  onSave(): void;
}

export interface AnalysisPanelView {
  bindActions(handlers: AnalysisPanelActionHandlers): void;
  focusField(field: AnalysisPanelFieldKey): void;
  openGuidance(): void;
  setModel(model: AnalysisPanelRenderModel): void;
  setCarAvailability(state: AnalysisPanelCarAvailability): void;
}

type AnalysisFieldSpec = {
  fallbackLabel: string;
  guidanceId: string;
  inputId: string;
  key: AnalysisPanelFieldKey;
  labelKey: string;
  step: string;
};

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

const ORDER_BAND_FIELDS: readonly AnalysisFieldSpec[] = [
  {
    fallbackLabel: "Wheel Bandwidth (%)",
    guidanceId: "wheelBandwidthGuidance",
    inputId: "wheelBandwidthInput",
    key: "wheel_bandwidth_pct",
    labelKey: "settings.wheel_bandwidth",
    step: "0.1",
  },
  {
    fallbackLabel: "Driveshaft Bandwidth (%)",
    guidanceId: "driveshaftBandwidthGuidance",
    inputId: "driveshaftBandwidthInput",
    key: "driveshaft_bandwidth_pct",
    labelKey: "settings.driveshaft_bandwidth",
    step: "0.1",
  },
  {
    fallbackLabel: "Engine Bandwidth (%)",
    guidanceId: "engineBandwidthGuidance",
    inputId: "engineBandwidthInput",
    key: "engine_bandwidth_pct",
    labelKey: "settings.engine_bandwidth",
    step: "0.1",
  },
  {
    fallbackLabel: "Min Half-width (Hz)",
    guidanceId: "minAbsBandHzGuidance",
    inputId: "minAbsBandHzInput",
    key: "min_abs_band_hz",
    labelKey: "settings.min_half_width",
    step: "0.1",
  },
  {
    fallbackLabel: "Max Half-width (%)",
    guidanceId: "maxBandHalfWidthGuidance",
    inputId: "maxBandHalfWidthInput",
    key: "max_band_half_width_pct",
    labelKey: "settings.max_half_width",
    step: "0.1",
  },
] as const;

const UNCERTAINTY_FIELDS: readonly AnalysisFieldSpec[] = [
  {
    fallbackLabel: "Speed Uncertainty (%)",
    guidanceId: "speedUncertaintyGuidance",
    inputId: "speedUncertaintyInput",
    key: "speed_uncertainty_pct",
    labelKey: "settings.speed_uncertainty",
    step: "0.1",
  },
  {
    fallbackLabel: "Tire Diameter Uncertainty (%)",
    guidanceId: "tireDiameterUncertaintyGuidance",
    inputId: "tireDiameterUncertaintyInput",
    key: "tire_diameter_uncertainty_pct",
    labelKey: "settings.tire_diameter_uncertainty",
    step: "0.1",
  },
  {
    fallbackLabel: "Final Drive Uncertainty (%)",
    guidanceId: "finalDriveUncertaintyGuidance",
    inputId: "finalDriveUncertaintyInput",
    key: "final_drive_uncertainty_pct",
    labelKey: "settings.final_drive_uncertainty",
    step: "0.1",
  },
  {
    fallbackLabel: "Gear/Slip Uncertainty (%)",
    guidanceId: "gearUncertaintyGuidance",
    inputId: "gearUncertaintyInput",
    key: "gear_uncertainty_pct",
    labelKey: "settings.gear_slip_uncertainty",
    step: "0.1",
  },
] as const;

function SettingsFeedbackBlock(props: {
  message: SettingsFeedbackMessage;
}) {
  const { message } = props;
  return (
    <div
      class={settingsFeedbackClassName(message)}
      aria-live={message.tone === "error" ? "assertive" : "polite"}
    >
      {message.title ? (
        <strong class="settings-feedback__title">{message.title}</strong>
      ) : null}
      <span class="settings-feedback__body">{message.body}</span>
      {message.detail ? (
        <span class="settings-feedback__detail">{message.detail}</span>
      ) : null}
    </div>
  );
}

function handleFieldInput(
  actions: AnalysisPanelActionHandlers | null,
  field: AnalysisPanelFieldKey,
  event: JSX.TargetedEvent<HTMLInputElement, Event>,
): void {
  actions?.onFieldInput({
    field,
    value: event.currentTarget.value,
  });
}

function AnalysisFieldGuidance(props: {
  guidanceId: string;
  model: SettingsAnalysisGuidanceRenderModel;
}) {
  const { guidanceId, model } = props;
  return (
    <div id={guidanceId} class="subtle settings-field-guidance">
      {model.lines.map((line) => (
        <div key={`${guidanceId}-${line.label}`} class="settings-field-guidance__row">
          <span class="settings-field-guidance__label">{line.label}</span>
          {" "}
          <span class="settings-field-guidance__value">{line.value}</span>
        </div>
      ))}
      {model.error ? <SettingsFeedbackBlock message={model.error} /> : null}
    </div>
  );
}

function AnalysisField(props: {
  actions: AnalysisPanelActionHandlers | null;
  model: AnalysisPanelFieldRenderModel;
  onInputRef: (element: HTMLInputElement | null) => void;
  spec: AnalysisFieldSpec;
}) {
  const { actions, model, onInputRef, spec } = props;
  const t = useUiTranslation();
  return (
    <div class="field">
      <label htmlFor={spec.inputId}>
        {t(spec.labelKey, spec.fallbackLabel)}
      </label>
      <input
        id={spec.inputId}
        ref={onInputRef}
        type="number"
        step={spec.step}
        inputMode="decimal"
        value={model.value}
        aria-invalid={model.invalid ? "true" : undefined}
        onInput={(event) => handleFieldInput(actions, spec.key, event)}
      />
      <AnalysisFieldGuidance guidanceId={spec.guidanceId} model={model.guidance} />
    </div>
  );
}

function AnalysisPanel(props: {
  guidanceOpenRequest: ReadonlySignal<number>;
  inputFocusRequest: ReadonlySignal<AnalysisFieldFocusRequest | null>;
  state: ReadonlySignal<AnalysisPanelBridgeState>;
}) {
  const state = props.state.value;
  const guidanceOpenRequest = props.guidanceOpenRequest.value;
  const inputFocusRequest = props.inputFocusRequest.value;
  const t = useUiTranslation();
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

  useEffect(() => {
    if (!inputFocusRequest) {
      return;
    }
    inputRefs.current[inputFocusRequest.field]?.focus();
  }, [inputFocusRequest]);

  useEffect(() => {
    if (guidanceOpenRequest <= 0) {
      return;
    }
    if (guidanceHelpRef.current) {
      guidanceHelpRef.current.open = true;
    }
  }, [guidanceOpenRequest]);

  const noCarSelected = !state.availability.hasActiveCar && !state.availability.isLoading;
  return (
    <div class="panel card settings-layout">
      <details
        id="analysisGuidanceHelp"
        ref={guidanceHelpRef}
        class="settings-help-disclosure settings-help-disclosure--banner"
      >
        <summary class="settings-help-disclosure__summary">
          <span class="settings-help-disclosure__heading">
            <strong
              class="settings-help-disclosure__title"

            >
              {t("settings.analysis.guidance_title", "Safe starting point")}
            </strong>
            <span
              class="settings-help-disclosure__caption"

            >
              {t(
                "settings.analysis.guidance_summary",
                "Keep the defaults unless the data is unusually noisy or the vehicle specs are approximate.",
              )}
            </span>
          </span>
        </summary>
        <div class="settings-help-disclosure__body">
          <div
            class="subtle"

          >
            {t(
              "settings.analysis.guidance_intro",
              "Most users should keep the defaults. Use wider bands or higher uncertainty only when your data is unusually noisy or your vehicle specs are approximate.",
            )}
          </div>
          <div
            class="subtle"

          >
            {t(
              "settings.analysis.guidance_guardrail",
              "Values outside the guided range will ask for confirmation before they are saved.",
            )}
          </div>
        </div>
      </details>
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
        <section class="settings-group">
          <h3>
            {t("settings.group.order_band_widths", "Order Band Widths")}
          </h3>
          <details
            id="analysisOrderBandHelp"
            class="settings-help-disclosure settings-help-disclosure--inline"
          >
            <summary class="settings-help-disclosure__summary">
              <span
                class="settings-help-disclosure__title"

              >
                {t("settings.analysis.more_guidance", "Why this matters")}
              </span>
            </summary>
            <div class="settings-help-disclosure__body">
              <div
                class="subtle"

              >
                {t(
                  "settings.analysis.group.order_band_widths_help",
                  "These values control how far the app searches around each expected order. Wider bands tolerate more speed drift but can blend nearby faults together.",
                )}
              </div>
            </div>
          </details>
          <div class="settings-subgrid">
            {ORDER_BAND_FIELDS.map((field) => (
              <AnalysisField
                key={field.key}
                actions={state.actions}
                model={state.model.fields[field.key]}
                onInputRef={(element) => {
                  inputRefs.current[field.key] = element;
                }}
                spec={field}
              />
            ))}
          </div>
        </section>

        <section class="settings-group">
          <h3>
            {t("settings.group.uncertainty_model", "Uncertainty Model")}
          </h3>
          <details
            id="analysisUncertaintyHelp"
            class="settings-help-disclosure settings-help-disclosure--inline"
          >
            <summary class="settings-help-disclosure__summary">
              <span
                class="settings-help-disclosure__title"

              >
                {t("settings.analysis.more_guidance", "Why this matters")}
              </span>
            </summary>
            <div class="settings-help-disclosure__body">
              <div class="subtle">
                <span>
                  {t(
                    "settings.uncertainty_defaults",
                    "Defaults use tire wear from 10/32 in to 2/32 in plus safety margin.",
                  )}
                </span>
              </div>
              <div
                class="subtle"

              >
                {t(
                  "settings.analysis.group.uncertainty_model_help",
                  "Use these only when vehicle data is approximate, modified, or worn. Higher uncertainty makes matching more tolerant, but it can lower specificity and confidence.",
                )}
              </div>
            </div>
          </details>
          <div class="settings-subgrid settings-subgrid--aligned-labels">
            {UNCERTAINTY_FIELDS.map((field) => (
              <AnalysisField
                key={field.key}
                actions={state.actions}
                model={state.model.fields[field.key]}
                onInputRef={(element) => {
                  inputRefs.current[field.key] = element;
                }}
                spec={field}
              />
            ))}
          </div>
        </section>
      </div>
      <div
        id="analysisSaveFeedback"
        class="settings-feedback-slot"
        hidden={state.model.saveFeedback === null}
      >
        {state.model.saveFeedback ? (
          <SettingsFeedbackBlock message={state.model.saveFeedback} />
        ) : null}
      </div>
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
  const bridgeState = signal<AnalysisPanelBridgeState>({
    actions: null,
    availability: DEFAULT_ANALYSIS_CAR_AVAILABILITY,
    model: DEFAULT_ANALYSIS_PANEL_MODEL,
  });
  const inputFocusRequest = signal<AnalysisFieldFocusRequest | null>(null);
  const guidanceOpenRequest = signal(0);
  let focusRequestToken = 0;
  const mount = createUiPreactMount(host);
  mount.render(
    <AnalysisPanel
      guidanceOpenRequest={guidanceOpenRequest}
      inputFocusRequest={inputFocusRequest}
      state={bridgeState}
    />,
  );

  return {
    bindActions(handlers) {
      bridgeState.value = { ...bridgeState.value, actions: handlers };
    },
    focusField(field) {
      focusRequestToken += 1;
      inputFocusRequest.value = { field, token: focusRequestToken };
    },
    openGuidance() {
      guidanceOpenRequest.value += 1;
    },
    setModel(model) {
      bridgeState.value = { ...bridgeState.value, model };
    },
    setCarAvailability(state) {
      bridgeState.value = { ...bridgeState.value, availability: state };
    },
  };
}
