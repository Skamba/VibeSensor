import type { JSX } from "preact";

import { useUiTranslation } from "../ui_i18n";
import {
  settingsFeedbackClassName,
  type SettingsFeedbackMessage,
} from "./settings_feedback";
import type {
  AnalysisFieldSpec,
  AnalysisPanelActionHandlers,
  AnalysisPanelFieldKey,
  AnalysisPanelFieldRenderModel,
  SettingsAnalysisGuidanceRenderModel,
} from "./analysis_panel_models";

type AnalysisHelpText = {
  fallback: string;
  key: string;
};

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

export function AnalysisGuidanceDialog(props: {
  guidanceHelpRef: { current: HTMLDetailsElement | null };
}) {
  const { guidanceHelpRef } = props;
  const t = useUiTranslation();
  return (
    <details
      id="analysisGuidanceHelp"
      ref={guidanceHelpRef}
      class="settings-help-disclosure settings-help-disclosure--banner"
    >
      <summary class="settings-help-disclosure__summary">
        <span class="settings-help-disclosure__heading">
          <strong class="settings-help-disclosure__title">
            {t("settings.analysis.guidance_title", "Safe starting point")}
          </strong>
          <span class="settings-help-disclosure__caption">
            {t(
              "settings.analysis.guidance_summary",
              "Keep the defaults unless the data is unusually noisy or the vehicle specs are approximate.",
            )}
          </span>
        </span>
      </summary>
      <div class="settings-help-disclosure__body">
        <div class="subtle">
          {t(
            "settings.analysis.guidance_intro",
            "Most users should keep the defaults. Use wider bands or higher uncertainty only when your data is unusually noisy or your vehicle specs are approximate.",
          )}
        </div>
        <div class="subtle">
          {t(
            "settings.analysis.guidance_guardrail",
            "Values outside the guided range will ask for confirmation before they are saved.",
          )}
        </div>
      </div>
    </details>
  );
}

export function AnalysisFieldGroup(props: {
  actions: AnalysisPanelActionHandlers | null;
  fields: readonly AnalysisFieldSpec[];
  helpBody: readonly AnalysisHelpText[];
  helpId: string;
  inputRefs: Record<AnalysisPanelFieldKey, HTMLInputElement | null>;
  modelFields: Record<AnalysisPanelFieldKey, AnalysisPanelFieldRenderModel>;
  subgridClassName?: string;
  titleFallback: string;
  titleKey: string;
}) {
  const {
    actions,
    fields,
    helpBody,
    helpId,
    inputRefs,
    modelFields,
    subgridClassName = "settings-subgrid",
    titleFallback,
    titleKey,
  } = props;
  const t = useUiTranslation();
  return (
    <section class="settings-group">
      <h3>
        {t(titleKey, titleFallback)}
      </h3>
      <details
        id={helpId}
        class="settings-help-disclosure settings-help-disclosure--inline"
      >
        <summary class="settings-help-disclosure__summary">
          <span class="settings-help-disclosure__title">
            {t("settings.analysis.more_guidance", "Why this matters")}
          </span>
        </summary>
        <div class="settings-help-disclosure__body">
          {helpBody.map((item) => (
            <div key={item.key} class="subtle">
              {t(item.key, item.fallback)}
            </div>
          ))}
        </div>
      </details>
      <div class={subgridClassName}>
        {fields.map((field) => (
          <AnalysisField
            key={field.key}
            actions={actions}
            model={modelFields[field.key]}
            onInputRef={(element) => {
              inputRefs[field.key] = element;
            }}
            spec={field}
          />
        ))}
      </div>
    </section>
  );
}

export function AnalysisSaveFeedback(props: {
  message: SettingsFeedbackMessage | null;
}) {
  const { message } = props;
  return (
    <div
      id="analysisSaveFeedback"
      class="settings-feedback-slot"
      hidden={message === null}
    >
      {message ? <SettingsFeedbackBlock message={message} /> : null}
    </div>
  );
}
