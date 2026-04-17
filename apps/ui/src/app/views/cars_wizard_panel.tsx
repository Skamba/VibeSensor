import type { CarsFeatureFocusTarget } from "../features/cars_feature_workflow";
import type { CarsFeatureManualInputState } from "../features/cars_manual_input";
import { useUiTranslation } from "../ui_i18n";
import type { CarsWizardRenderModel } from "./car_wizard_view";
import {
  CarsWizardStepNav,
  CarsWizardSteps,
  CarsWizardSummaryPanel,
} from "./cars_wizard_sections";
import type { CarsWizardElementRefs } from "./cars_wizard_focus";

export type CarsFeatureInteraction =
  | { type: "back" }
  | { type: "close" }
  | { type: "finish" }
  | { type: "manual-input-changed"; field: keyof CarsFeatureManualInputState; value: string }
  | { type: "open" }
  | { type: "select-brand"; value: string }
  | { type: "select-gearbox"; index: number }
  | { type: "select-model"; index: number }
  | { type: "select-tire"; index: number }
  | { type: "select-type"; value: string }
  | { type: "select-variant"; index: number }
  | { type: "submit-custom-brand"; value: string }
  | { type: "submit-custom-model"; value: string }
  | { type: "submit-custom-type"; value: string };

export interface CarsFeatureInteractionHandlers {
  onAction(action: CarsFeatureInteraction): void;
}

export function CarsWizardPanel(props: {
  actions: CarsFeatureInteractionHandlers | null;
  refs: CarsWizardElementRefs;
  wizardModel: CarsWizardRenderModel;
}) {
  const { actions, refs, wizardModel } = props;
  const t = useUiTranslation();

  function closeWizard(): void {
    actions?.onAction({ type: "close" });
  }

  function emitManualInputs(
    field: keyof CarsFeatureManualInputState,
    value: string,
  ): void {
    actions?.onAction({
      type: "manual-input-changed",
      field,
      value,
    });
  }

  function handleWizardKeyDown(event: KeyboardEvent): void {
    if (event.key !== "Escape") {
      return;
    }
    event.preventDefault();
    closeWizard();
  }

  return (
    <div class="wizard-modal-layer" hidden={!wizardModel.isOpen}>
      <div
        id="wizardBackdrop"
        class="wizard-backdrop"
        hidden={!wizardModel.isOpen}
        onClick={closeWizard}
      />
      <div
        id="addCarWizard"
        class="panel card add-car-wizard"
        hidden={!wizardModel.isOpen}
        role="dialog"
        aria-modal="true"
        aria-labelledby="wizardTitle"
        data-spec-branch={wizardModel.specBranch ?? undefined}
        tabIndex={-1}
        onKeyDown={handleWizardKeyDown}
        ref={refs.addCarWizardRef}
      >
        <div class="wizard-header">
          <div class="wizard-header__text">
            <strong id="wizardTitle">
              {t("settings.car.add_title", "Add a Car")}
            </strong>
            <div class="subtle">
              {t(
                "settings.car.wizard_intro",
                "Use the library when it fits, or branch into manual specs without losing your place.",
              )}
            </div>
              <div id="wizardProgressText" class="wizard-progress-text">
                {wizardModel.progressText}
              </div>
          </div>
          <button
            id="wizardCloseBtn"
            class="btn btn--muted wizard-close"
            aria-label="Close wizard"
            onClick={closeWizard}
            ref={refs.wizardCloseBtnRef}
          >
            {"\u00d7"}
          </button>
        </div>
        <div class="wizard-shell">
            <div class="wizard-main">
              <div class="wizard-steps">
                <CarsWizardStepNav step={wizardModel.step} />
                <CarsWizardSteps
                  emitManualInputs={emitManualInputs}
                  refs={refs}
                  wizardModel={wizardModel}
                  onSelectBrand={(value) => actions?.onAction({ type: "select-brand", value })}
                  onSelectGearbox={(index) => actions?.onAction({ type: "select-gearbox", index })}
                  onSelectModel={(index) => actions?.onAction({ type: "select-model", index })}
                  onSelectTire={(index) => actions?.onAction({ type: "select-tire", index })}
                  onSelectType={(value) => actions?.onAction({ type: "select-type", value })}
                  onSelectVariant={(index) => actions?.onAction({ type: "select-variant", index })}
                  onSubmitCustomBrand={(value) =>
                    actions?.onAction({ type: "submit-custom-brand", value })}
                  onSubmitCustomModel={(value) =>
                    actions?.onAction({ type: "submit-custom-model", value })}
                  onSubmitCustomType={(value) =>
                    actions?.onAction({ type: "submit-custom-type", value })}
                />
              </div>

              <div class="wizard-nav">
              <div id="wizardActionHint" class="subtle wizard-nav__status" aria-live="polite">
                {wizardModel.actionHintText}
              </div>
              <div class="wizard-nav__actions">
                <button
                  id="wizardBackBtn"
                  class="btn btn--muted"
                  hidden={!wizardModel.backVisible}
                  onClick={() => actions?.onAction({ type: "back" })}
                >
                  {t("settings.car.back", "Back")}
                </button>
                <button
                  id="wizardManualAddBtn"
                  class="btn btn--success"
                  hidden={!wizardModel.finishVisible}
                  disabled={!wizardModel.finishEnabled}
                  onClick={() => actions?.onAction({ type: "finish" })}
                  ref={refs.wizardManualAddBtnRef}
                >
                  {t("settings.car.finish_add", "Add Car")}
                </button>
              </div>
            </div>
          </div>

          <aside class="wizard-summary-card" aria-live="polite">
            <div class="wizard-task-callout">
              <strong>
                {t("settings.car.wizard_task_title", "Guided setup")}
              </strong>
              <div class="subtle">
                {t(
                  "settings.car.wizard_task_intro",
                  "This flow pauses the rest of Settings so you can build the next analysis profile step by step without losing your place.",
                )}
              </div>
            </div>
            <div class="wizard-summary-card__title">
              {t("settings.car.wizard_summary_title", "Current selection")}
            </div>
            <div class="subtle">
              {t(
                "settings.car.wizard_summary_intro",
                "Your choices stay visible here while the profile comes together.",
              )}
            </div>
            <CarsWizardSummaryPanel summary={wizardModel.summary} />
          </aside>
        </div>
      </div>
    </div>
  );
}
