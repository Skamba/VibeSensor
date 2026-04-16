import { useRef } from "preact/hooks";

import type { CarsFeatureFocusTarget } from "../features/cars_feature_workflow";
import { useSignalEffect, type ReadonlySignal } from "../ui_signals";
import type { CarsWizardRenderModel } from "./car_wizard_view";

export type CarsWizardOptionRefs = {
  brandOption: HTMLButtonElement | null;
  gearboxOption: HTMLButtonElement | null;
  modelOption: HTMLButtonElement | null;
  tireOption: HTMLButtonElement | null;
  typeOption: HTMLButtonElement | null;
  variantOption: HTMLButtonElement | null;
};

export type CarsWizardFocusRequest = {
  target: CarsFeatureFocusTarget;
  token: number;
};

type CarsWizardFocusRefs = {
  closeButton: HTMLButtonElement | null;
  customBrandInput: HTMLInputElement | null;
  customModelInput: HTMLInputElement | null;
  customTypeInput: HTMLInputElement | null;
  finalDriveInput: HTMLInputElement | null;
  manualAddButton: HTMLButtonElement | null;
  optionRefs: CarsWizardOptionRefs;
  rimInput: HTMLInputElement | null;
  tireAspectInput: HTMLInputElement | null;
  tireWidthInput: HTMLInputElement | null;
  topGearInput: HTMLInputElement | null;
};

export type CarsWizardElementRefs = {
  addCarWizardRef: { current: HTMLDivElement | null };
  optionRefs: { current: CarsWizardOptionRefs };
  wizardCloseBtnRef: { current: HTMLButtonElement | null };
  wizardCustomBrandInputRef: { current: HTMLInputElement | null };
  wizardCustomModelInputRef: { current: HTMLInputElement | null };
  wizardCustomTypeInputRef: { current: HTMLInputElement | null };
  wizardManualAddBtnRef: { current: HTMLButtonElement | null };
  wizFinalDriveInputRef: { current: HTMLInputElement | null };
  wizGearRatioInputRef: { current: HTMLInputElement | null };
  wizRimInputRef: { current: HTMLInputElement | null };
  wizTireAspectInputRef: { current: HTMLInputElement | null };
  wizTireWidthInputRef: { current: HTMLInputElement | null };
};

function focusElement(target: HTMLElement | null | undefined): void {
  target?.focus();
}

export function resolveWizardFocusTarget(
  target: CarsFeatureFocusTarget,
  refs: CarsWizardFocusRefs,
): HTMLElement | null {
  switch (target) {
    case "brand-option":
      return refs.optionRefs.brandOption ?? refs.customBrandInput;
    case "close":
      return refs.closeButton;
    case "custom-brand":
      return refs.customBrandInput;
    case "custom-model":
      return refs.customModelInput;
    case "custom-type":
      return refs.customTypeInput;
    case "finish":
      return refs.manualAddButton;
    case "gearbox-option":
      return refs.optionRefs.gearboxOption ?? refs.manualAddButton;
    case "manual-final-drive":
      return refs.finalDriveInput;
    case "manual-rim":
      return refs.rimInput;
    case "manual-tire-aspect":
      return refs.tireAspectInput;
    case "manual-tire-width":
      return refs.tireWidthInput;
    case "manual-top-gear":
      return refs.topGearInput;
    case "model-option":
      return refs.optionRefs.modelOption ?? refs.customModelInput;
    case "spec-selection":
      return refs.optionRefs.tireOption ?? refs.optionRefs.gearboxOption ?? refs.tireWidthInput;
    case "type-option":
      return refs.optionRefs.typeOption ?? refs.customTypeInput;
    case "variant-option":
      return refs.optionRefs.variantOption;
  }
}

export function useCarsWizardFocusManager(props: {
  state: ReadonlySignal<{ wizardModel: ReadonlySignal<CarsWizardRenderModel> | null }>;
  wizardFocusRequest: ReadonlySignal<CarsWizardFocusRequest | null>;
}): {
  addCarButtonRef: { current: HTMLButtonElement | null };
  wizardRefs: CarsWizardElementRefs;
} {
  const addCarButtonRef = useRef<HTMLButtonElement | null>(null);
  const addCarWizardRef = useRef<HTMLDivElement | null>(null);
  const wizardCloseBtnRef = useRef<HTMLButtonElement | null>(null);
  const wizardCustomBrandInputRef = useRef<HTMLInputElement | null>(null);
  const wizardCustomModelInputRef = useRef<HTMLInputElement | null>(null);
  const wizardCustomTypeInputRef = useRef<HTMLInputElement | null>(null);
  const wizardManualAddBtnRef = useRef<HTMLButtonElement | null>(null);
  const wizFinalDriveInputRef = useRef<HTMLInputElement | null>(null);
  const wizGearRatioInputRef = useRef<HTMLInputElement | null>(null);
  const wizRimInputRef = useRef<HTMLInputElement | null>(null);
  const wizTireAspectInputRef = useRef<HTMLInputElement | null>(null);
  const wizTireWidthInputRef = useRef<HTMLInputElement | null>(null);
  const optionRefs = useRef<CarsWizardOptionRefs>({
    brandOption: null,
    gearboxOption: null,
    modelOption: null,
    tireOption: null,
    typeOption: null,
    variantOption: null,
  });
  const lastReturnFocusTargetRef = useRef<HTMLElement | null>(null);
  const lastHandledFocusRequestTokenRef = useRef(0);
  const lastWizardOpenStateRef = useRef(props.state.value.wizardModel?.value.isOpen ?? false);

  useSignalEffect(() => {
    const isOpen = props.state.value.wizardModel?.value.isOpen ?? false;
    const wasOpen = lastWizardOpenStateRef.current;
    if (isOpen && !wasOpen) {
      const activeElement = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
      lastReturnFocusTargetRef.current =
        activeElement && activeElement !== document.body ? activeElement : addCarButtonRef.current;
      queueMicrotask(() => {
        if (addCarWizardRef.current) {
          addCarWizardRef.current.scrollTop = 0;
        }
      });
    }
    if (!isOpen && wasOpen) {
      const target = lastReturnFocusTargetRef.current;
      lastReturnFocusTargetRef.current = null;
      queueMicrotask(() => {
        const safeTarget = target && document.contains(target) ? target : addCarButtonRef.current;
        focusElement(safeTarget);
      });
    }
    lastWizardOpenStateRef.current = isOpen;
  });

  useSignalEffect(() => {
    const wizardFocusRequest = props.wizardFocusRequest.value;
    if (
      !wizardFocusRequest ||
      wizardFocusRequest.token === lastHandledFocusRequestTokenRef.current
    ) {
      return;
    }
    lastHandledFocusRequestTokenRef.current = wizardFocusRequest.token;
    queueMicrotask(() => {
      focusElement(
        resolveWizardFocusTarget(wizardFocusRequest.target, {
          closeButton: wizardCloseBtnRef.current,
          customBrandInput: wizardCustomBrandInputRef.current,
          customModelInput: wizardCustomModelInputRef.current,
          customTypeInput: wizardCustomTypeInputRef.current,
          finalDriveInput: wizFinalDriveInputRef.current,
          manualAddButton: wizardManualAddBtnRef.current,
          optionRefs: optionRefs.current,
          rimInput: wizRimInputRef.current,
          tireAspectInput: wizTireAspectInputRef.current,
          tireWidthInput: wizTireWidthInputRef.current,
          topGearInput: wizGearRatioInputRef.current,
        }),
      );
    });
  });

  return {
    addCarButtonRef,
    wizardRefs: {
      addCarWizardRef,
      optionRefs,
      wizardCloseBtnRef,
      wizardCustomBrandInputRef,
      wizardCustomModelInputRef,
      wizardCustomTypeInputRef,
      wizardManualAddBtnRef,
      wizFinalDriveInputRef,
      wizGearRatioInputRef,
      wizRimInputRef,
      wizTireAspectInputRef,
      wizTireWidthInputRef,
    },
  };
}
