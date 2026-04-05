import type { UiCarsDom } from "../dom/cars_dom";
import {
  renderWizardBrandOptions,
  renderWizardGearboxOptions,
  renderWizardMessage,
  renderWizardModelOptions,
  renderWizardSummary,
  renderWizardTireOptions,
  renderWizardTypeOptions,
  renderWizardVariantOptions,
  syncCarWizardStepState,
} from "./car_wizard_view";
import type {
  CarsFeatureFocusTarget,
  CarsFeatureManualInputState,
  CarsFeatureOptionsState,
  CarsFeatureRenderState,
} from "../features/cars_feature_workflow";

const WIZARD_STEP_LABEL_KEYS = [
  "settings.car.step_brand_short",
  "settings.car.step_type_short",
  "settings.car.step_model_short",
  "settings.car.step_variant_short",
  "settings.car.step_specs_short",
] as const;

export interface CarsFeaturePresenterDeps {
  dom: Pick<
    UiCarsDom,
    | "addCarBtn"
    | "addCarWizard"
    | "wizFinalDriveInput"
    | "wizGearRatioInput"
    | "wizRimInput"
    | "wizTireAspectInput"
    | "wizTireWidthInput"
    | "wizardActionHint"
    | "wizardBackdrop"
    | "wizardBackBtn"
    | "wizardBrandList"
    | "wizardCloseBtn"
    | "wizardCustomBrandInput"
    | "wizardCustomModelInput"
    | "wizardCustomTypeInput"
    | "wizardGearboxList"
    | "wizardManualAddBtn"
    | "wizardModelList"
    | "wizardProgressText"
    | "wizardStepDots"
    | "wizardSteps"
    | "wizardSummaryPanel"
    | "wizardTireList"
    | "wizardTypeList"
    | "wizardVariantList"
  >;
  escapeHtml: (value: unknown) => string;
  fmt: (value: number, digits?: number) => string;
  t: (key: string, vars?: Record<string, unknown>) => string;
}

export interface CarsFeaturePresenter {
  captureReturnFocusTarget(): HTMLElement | null;
  focus(target: CarsFeatureFocusTarget): void;
  readManualInputs(): CarsFeatureManualInputState;
  render(state: CarsFeatureRenderState): void;
  restoreFocus(target: HTMLElement | null): void;
}

function renderOptionsState<TOption>(
  container: HTMLElement | null,
  state: CarsFeatureOptionsState<TOption>,
  renderReady: (options: readonly TOption[]) => string,
  escapeHtml: (value: unknown) => string,
): void {
  if (!container) {
    return;
  }
  if (state.status === "loading" || state.status === "error") {
    container.innerHTML = renderWizardMessage(state.message ?? "", escapeHtml);
    return;
  }
  container.innerHTML = state.status === "ready" ? renderReady(state.options) : "";
}

function focusElement(target: HTMLElement | null | undefined): void {
  target?.focus();
}

function focusFirstOption(
  container: ParentNode | null,
  fallback: HTMLElement | null,
): void {
  const firstOption = container?.querySelector<HTMLButtonElement>(".wiz-opt");
  focusElement(firstOption ?? fallback);
}

function syncInputValue(input: HTMLInputElement | null, value: string): void {
  if (input && input.value !== value) {
    input.value = value;
  }
}

export function createCarsFeaturePresenter(
  deps: CarsFeaturePresenterDeps,
): CarsFeaturePresenter {
  const { dom, escapeHtml, fmt, t } = deps;
  let lastOpenState = false;

  function syncVisibility(isOpen: boolean): void {
    if (dom.wizardBackdrop) {
      dom.wizardBackdrop.hidden = !isOpen;
    }
    dom.addCarWizard.hidden = !isOpen;
    if (isOpen && !lastOpenState) {
      dom.addCarWizard.scrollTop = 0;
    }
    document.body.classList.toggle("wizard-open", isOpen);
    lastOpenState = isOpen;
  }

  function renderSpecsStep(state: CarsFeatureRenderState): void {
    if (dom.wizardTireList) {
      const selectedTireIndex = state.selectedTire ? state.tireOptions.indexOf(state.selectedTire) : -1;
      dom.wizardTireList.innerHTML = state.tireOptions.length > 0
        ? renderWizardTireOptions(
          [...state.tireOptions],
          escapeHtml,
          selectedTireIndex >= 0 ? selectedTireIndex : 0,
        )
        : "";
    }
    if (dom.wizardGearboxList) {
      const selectedGearboxIndex = state.selectedGearbox
        ? state.gearboxOptions.indexOf(state.selectedGearbox)
        : -1;
      if (state.noGearboxesMessage) {
        dom.wizardGearboxList.innerHTML = renderWizardMessage(state.noGearboxesMessage, escapeHtml);
      } else {
        dom.wizardGearboxList.innerHTML = renderWizardGearboxOptions(
          [...state.gearboxOptions],
          { escapeHtml, fmt },
          selectedGearboxIndex,
        );
      }
    }
    syncInputValue(dom.wizTireWidthInput, state.manualInputs.tireWidth);
    syncInputValue(dom.wizTireAspectInput, state.manualInputs.tireAspect);
    syncInputValue(dom.wizRimInput, state.manualInputs.rim);
    syncInputValue(dom.wizFinalDriveInput, state.manualInputs.finalDrive);
    syncInputValue(dom.wizGearRatioInput, state.manualInputs.topGear);
  }

  return {
    captureReturnFocusTarget(): HTMLElement | null {
      return document.activeElement instanceof HTMLElement ? document.activeElement : dom.addCarBtn;
    },

    focus(target): void {
      switch (target) {
        case "brand-option":
          focusFirstOption(dom.wizardBrandList, dom.wizardCustomBrandInput);
          return;
        case "close":
          focusElement(dom.wizardCloseBtn);
          return;
        case "custom-brand":
          focusElement(dom.wizardCustomBrandInput);
          return;
        case "custom-model":
          focusElement(dom.wizardCustomModelInput);
          return;
        case "custom-type":
          focusElement(dom.wizardCustomTypeInput);
          return;
        case "finish":
          focusElement(dom.wizardManualAddBtn);
          return;
        case "gearbox-option":
          focusFirstOption(dom.wizardGearboxList, dom.wizardManualAddBtn);
          return;
        case "manual-final-drive":
          focusElement(dom.wizFinalDriveInput);
          return;
        case "manual-rim":
          focusElement(dom.wizRimInput);
          return;
        case "manual-tire-aspect":
          focusElement(dom.wizTireAspectInput);
          return;
        case "manual-tire-width":
          focusElement(dom.wizTireWidthInput);
          return;
        case "manual-top-gear":
          focusElement(dom.wizGearRatioInput);
          return;
        case "model-option":
          focusFirstOption(dom.wizardModelList, dom.wizardCustomModelInput);
          return;
        case "spec-selection":
          focusElement(
            dom.wizardTireList?.querySelector<HTMLButtonElement>(".wiz-opt")
            ?? dom.wizardGearboxList?.querySelector<HTMLButtonElement>(".wiz-opt")
            ?? dom.wizTireWidthInput,
          );
          return;
        case "type-option":
          focusFirstOption(dom.wizardTypeList, dom.wizardCustomTypeInput);
          return;
        case "variant-option":
          focusFirstOption(dom.wizardVariantList, null);
          return;
      }
    },

    readManualInputs(): CarsFeatureManualInputState {
      return {
        finalDrive: dom.wizFinalDriveInput?.value ?? "",
        rim: dom.wizRimInput?.value ?? "",
        tireAspect: dom.wizTireAspectInput?.value ?? "",
        tireWidth: dom.wizTireWidthInput?.value ?? "",
        topGear: dom.wizGearRatioInput?.value ?? "",
      };
    },

    render(state): void {
      syncVisibility(state.isOpen);
      if (!state.isOpen) {
        delete dom.addCarWizard.dataset.specBranch;
        return;
      }

      syncCarWizardStepState(dom, state.step);
      if (dom.wizardProgressText) {
        dom.wizardProgressText.textContent = t("settings.car.wizard_progress", {
          current: state.step + 1,
          step: t(WIZARD_STEP_LABEL_KEYS[state.step] ?? WIZARD_STEP_LABEL_KEYS[0]),
          total: WIZARD_STEP_LABEL_KEYS.length,
        });
      }
      if (dom.wizardSummaryPanel) {
        dom.wizardSummaryPanel.innerHTML = renderWizardSummary(state.summaryData, { escapeHtml, t });
      }
      if (dom.wizardActionHint) {
        dom.wizardActionHint.textContent = state.actionHint;
      }
      if (state.step === 4) {
        dom.addCarWizard.dataset.specBranch = state.resolvedSpecBranch ?? "pending";
      } else {
        delete dom.addCarWizard.dataset.specBranch;
      }
      if (dom.wizardManualAddBtn) {
        dom.wizardManualAddBtn.hidden = state.step !== 4;
        dom.wizardManualAddBtn.disabled = state.step !== 4 || !state.canFinish;
      }

      renderOptionsState(
        dom.wizardBrandList,
        state.brandOptions,
        (options) => renderWizardBrandOptions([...options], escapeHtml),
        escapeHtml,
      );
      renderOptionsState(
        dom.wizardTypeList,
        state.typeOptions,
        (options) => renderWizardTypeOptions([...options], escapeHtml),
        escapeHtml,
      );
      renderOptionsState(
        dom.wizardModelList,
        state.modelOptions,
        (options) => renderWizardModelOptions([...options], escapeHtml),
        escapeHtml,
      );
      if (dom.wizardVariantList) {
        dom.wizardVariantList.innerHTML = renderWizardVariantOptions([...state.variantOptions], escapeHtml);
      }
      renderSpecsStep(state);
    },

    restoreFocus(target): void {
      const safeTarget = target && document.contains(target) ? target : dom.addCarBtn;
      focusElement(safeTarget);
    },
  };
}
