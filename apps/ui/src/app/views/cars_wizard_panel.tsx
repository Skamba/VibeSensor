import type { CarsFeatureFocusTarget } from "../features/cars_feature_workflow";
import type { CarsFeatureManualInputState } from "../features/cars_manual_input";
import { getUiText as t } from "../ui_i18n";
import {
  useSignalProperties,
  type ReadonlySignal,
} from "../ui_signals";
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

const CARS_WIZARD_PANEL_KEYS = [
  "actionHintText",
  "backVisible",
  "finishEnabled",
  "finishVisible",
  "isOpen",
  "progressText",
  "specBranch",
  "step",
  "summary",
] as const;

export function CarsWizardPanel(props: {
  actions: ReadonlySignal<CarsFeatureInteractionHandlers | null>;
  refs: CarsWizardElementRefs;
  wizardModel: ReadonlySignal<CarsWizardRenderModel>;
}) {
  const { refs } = props;
  const {
    actionHintText,
    backVisible,
    finishEnabled,
    finishVisible,
    isOpen,
    progressText,
    specBranch,
    step,
    summary,
  } = useSignalProperties(props.wizardModel, CARS_WIZARD_PANEL_KEYS);

  function dispatchAction(action: CarsFeatureInteraction): void {
    props.actions.peek()?.onAction(action);
  }

  function closeWizard(): void {
    dispatchAction({ type: "close" });
  }

  function emitManualInputs(
    field: keyof CarsFeatureManualInputState,
    value: string,
  ): void {
    dispatchAction({
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
    <div class="wizard-modal-layer" hidden={!isOpen.value}>
      <div
        id="wizardBackdrop"
        class="wizard-backdrop"
        hidden={!isOpen.value}
        onClick={closeWizard}
      />
      <div
        id="addCarWizard"
        class="panel card add-car-wizard"
        hidden={!isOpen.value}
        role="dialog"
        aria-modal="true"
        aria-labelledby="wizardTitle"
        data-spec-branch={specBranch.value ?? undefined}
        tabIndex={-1}
        onKeyDown={handleWizardKeyDown}
        ref={refs.setElementRef("addCarWizard")}
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
                {progressText.value}
              </div>
            </div>
          <button
            id="wizardCloseBtn"
            class="btn btn--muted wizard-close"
            aria-label="Close wizard"
            onClick={closeWizard}
            ref={refs.setElementRef("closeButton")}
          >
            {"\u00d7"}
          </button>
        </div>
          <div class="wizard-shell">
            <div class="wizard-main">
              <div class="wizard-steps">
                <CarsWizardStepNav step={step} />
                <CarsWizardSteps
                  emitManualInputs={emitManualInputs}
                  refs={refs}
                  wizardModel={props.wizardModel}
                  onSelectBrand={(value) => dispatchAction({ type: "select-brand", value })}
                  onSelectGearbox={(index) => dispatchAction({ type: "select-gearbox", index })}
                  onSelectModel={(index) => dispatchAction({ type: "select-model", index })}
                  onSelectTire={(index) => dispatchAction({ type: "select-tire", index })}
                  onSelectType={(value) => dispatchAction({ type: "select-type", value })}
                  onSelectVariant={(index) => dispatchAction({ type: "select-variant", index })}
                  onSubmitCustomBrand={(value) =>
                    dispatchAction({ type: "submit-custom-brand", value })}
                  onSubmitCustomModel={(value) =>
                    dispatchAction({ type: "submit-custom-model", value })}
                  onSubmitCustomType={(value) =>
                    dispatchAction({ type: "submit-custom-type", value })}
                />
              </div>

              <div class="wizard-nav">
                <div id="wizardActionHint" class="subtle wizard-nav__status" aria-live="polite">
                  {actionHintText.value}
                </div>
                <div class="wizard-nav__actions">
                  <button
                    id="wizardBackBtn"
                    class="btn btn--muted"
                    hidden={!backVisible.value}
                    onClick={() => dispatchAction({ type: "back" })}
                  >
                    {t("settings.car.back", "Back")}
                  </button>
                  <button
                    id="wizardManualAddBtn"
                    class="btn btn--success"
                    hidden={!finishVisible.value}
                    disabled={!finishEnabled.value}
                    onClick={() => dispatchAction({ type: "finish" })}
                    ref={refs.setElementRef("manualAddButton")}
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
              <CarsWizardSummaryPanel summary={summary} />
            </aside>
          </div>
      </div>
    </div>
  );
}
