import { useEffect, useRef } from "preact/hooks";

import { FeedbackBlock, FeedbackSlot } from "../../components/feedback";
import { t } from "../../i18n";
import { FIELDS, type FieldKey, guidanceLines } from "./analysis_model";
import {
  carsLoading,
  drafts,
  editField,
  fieldErrors,
  focusRequest,
  guidanceRequest,
  hasActiveCar,
  resetAnalysis,
  saveAnalysis,
  saveFeedback,
} from "./analysis_store";

const HELP_KEYS = [
  "settings.uncertainty_defaults",
  "settings.analysis.group.uncertainty_model_help",
];

export function Analysis() {
  const guidance = useRef<HTMLDetailsElement | null>(null);
  const inputs = useRef<Partial<Record<FieldKey, HTMLInputElement | null>>>({});
  const guidanceOpen = guidanceRequest.value;
  const focus = focusRequest.value;
  useEffect(() => {
    if (guidanceOpen > 0 && guidance.current) {
      guidance.current.open = true;
    }
  }, [guidanceOpen]);
  useEffect(() => {
    if (focus) {
      inputs.current[focus.field]?.focus();
    }
  }, [focus]);
  const canSave = hasActiveCar.value;
  const errors = fieldErrors.value;
  return (
    <div class="panel card settings-layout">
      <details
        id="analysisGuidanceHelp"
        ref={guidance}
        class="settings-help-disclosure settings-help-disclosure--banner"
      >
        <summary class="settings-help-disclosure__summary">
          <span class="settings-help-disclosure__heading">
            <strong class="settings-help-disclosure__title">
              {t("settings.analysis.guidance_title")}
            </strong>
            <span class="settings-help-disclosure__caption">
              {t("settings.analysis.guidance_summary")}
            </span>
          </span>
        </summary>
        <div class="settings-help-disclosure__body">
          <div class="subtle">{t("settings.analysis.guidance_intro")}</div>
          <div class="subtle">{t("settings.analysis.guidance_guardrail")}</div>
        </div>
      </details>
      <div
        id="analysisNoCarMessage"
        class="empty-state empty-state--inline"
        hidden={canSave || carsLoading.value}
      >
        {t("settings.analysis.no_car_selected")}
      </div>
      <div class="settings-groups">
        <section class="settings-group">
          <h3>{t("settings.group.uncertainty_model")}</h3>
          <details
            id="analysisUncertaintyHelp"
            class="settings-help-disclosure settings-help-disclosure--inline"
          >
            <summary class="settings-help-disclosure__summary">
              <span class="settings-help-disclosure__title">
                {t("settings.analysis.more_guidance")}
              </span>
            </summary>
            <div class="settings-help-disclosure__body">
              {HELP_KEYS.map((key) => (
                <div key={key} class="subtle">
                  {t(key)}
                </div>
              ))}
            </div>
          </details>
          <div class="settings-subgrid settings-subgrid--aligned-labels">
            {FIELDS.map((field) => {
              const error = errors[field.key];
              return (
                <div class="field" key={field.key}>
                  <label htmlFor={field.inputId}>{t(field.labelKey)}</label>
                  <input
                    id={field.inputId}
                    ref={(element) => {
                      inputs.current[field.key] = element;
                    }}
                    type="number"
                    step="0.1"
                    inputMode="decimal"
                    value={drafts.value[field.key]}
                    aria-invalid={error ? "true" : undefined}
                    onInput={(event) =>
                      editField(field.key, event.currentTarget.value)
                    }
                  />
                  <div
                    id={field.guidanceId}
                    class="subtle settings-field-guidance"
                  >
                    {guidanceLines(field, t).map((line) => (
                      <div
                        key={`${field.guidanceId}-${line.label}`}
                        class="settings-field-guidance__row"
                      >
                        <span class="settings-field-guidance__label">
                          {line.label}
                        </span>{" "}
                        <span class="settings-field-guidance__value">
                          {line.value}
                        </span>
                      </div>
                    ))}
                    {error ? (
                      <FeedbackBlock
                        message={{ body: error, compact: true, tone: "error" }}
                        live
                      />
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
      <FeedbackSlot id="analysisSaveFeedback" message={saveFeedback.value} />
      <div class="settings-actions settings-actions--sticky">
        <button
          id="resetAnalysisBtn"
          type="button"
          class="btn"
          disabled={!canSave}
          onClick={() => void resetAnalysis()}
        >
          {t("settings.analysis.reset")}
        </button>
        <button
          id="saveAnalysisBtn"
          type="button"
          class="btn btn--primary"
          disabled={!canSave}
          onClick={() => void saveAnalysis()}
        >
          {t("settings.analysis.save")}
        </button>
      </div>
    </div>
  );
}
