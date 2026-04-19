import type { CarsFeatureFocusTarget } from "../features/cars_feature_workflow";
import { useRef } from "preact/hooks";

export type CarsWizardFocusElements = {
  addCarWizard: HTMLDivElement | null;
  brandOption: HTMLButtonElement | null;
  closeButton: HTMLButtonElement | null;
  customBrandInput: HTMLInputElement | null;
  customModelInput: HTMLInputElement | null;
  customTypeInput: HTMLInputElement | null;
  finalDriveInput: HTMLInputElement | null;
  gearboxOption: HTMLButtonElement | null;
  manualAddButton: HTMLButtonElement | null;
  modelOption: HTMLButtonElement | null;
  rimInput: HTMLInputElement | null;
  tireAspectInput: HTMLInputElement | null;
  tireOption: HTMLButtonElement | null;
  tireWidthInput: HTMLInputElement | null;
  topGearInput: HTMLInputElement | null;
  typeOption: HTMLButtonElement | null;
  variantOption: HTMLButtonElement | null;
};

export type CarsWizardFocusRequest = {
  target: CarsFeatureFocusTarget;
  token: number;
};

export type CarsWizardElementRefs = {
  elements: { current: CarsWizardFocusElements };
  setElementRef: <Key extends keyof CarsWizardFocusElements>(
    key: Key,
  ) => (element: CarsWizardFocusElements[Key]) => void;
};

function createCarsWizardFocusElements(): CarsWizardFocusElements {
  return {
    addCarWizard: null,
    brandOption: null,
    closeButton: null,
    customBrandInput: null,
    customModelInput: null,
    customTypeInput: null,
    finalDriveInput: null,
    gearboxOption: null,
    manualAddButton: null,
    modelOption: null,
    rimInput: null,
    tireAspectInput: null,
    tireOption: null,
    tireWidthInput: null,
    topGearInput: null,
    typeOption: null,
    variantOption: null,
  };
}

export function resolveWizardFocusTarget(
  target: CarsFeatureFocusTarget,
  refs: CarsWizardFocusElements,
): HTMLElement | null {
  switch (target) {
    case "brand-option":
      return refs.brandOption ?? refs.customBrandInput;
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
      return refs.gearboxOption ?? refs.manualAddButton;
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
      return refs.modelOption ?? refs.customModelInput;
    case "spec-selection":
      return refs.tireOption ?? refs.gearboxOption ?? refs.tireWidthInput;
    case "type-option":
      return refs.typeOption ?? refs.customTypeInput;
    case "variant-option":
      return refs.variantOption;
  }
}

export function useCarsWizardElementRefs(): CarsWizardElementRefs {
  const elements = useRef<CarsWizardFocusElements>(createCarsWizardFocusElements());
  const refs = useRef<CarsWizardElementRefs | null>(null);
  if (refs.current === null) {
    refs.current = {
      elements,
      setElementRef: (key) => (element) => {
        elements.current[key] = element;
      },
    };
  }
  return refs.current;
}
