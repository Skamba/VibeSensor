import { expect, test } from "@playwright/test";

import {
  resolveWizardFocusTarget,
  type CarsWizardFocusElements,
} from "../src/app/views/cars_wizard_focus";

function makeFocusElements(
  overrides: Partial<CarsWizardFocusElements> = {},
): CarsWizardFocusElements {
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
    ...overrides,
  };
}

test.describe("resolveWizardFocusTarget", () => {
  test("falls back from option targets to the matching manual control", () => {
    const customBrandInput = {} as HTMLInputElement;
    const customModelInput = {} as HTMLInputElement;
    const customTypeInput = {} as HTMLInputElement;
    const manualAddButton = {} as HTMLButtonElement;
    const tireWidthInput = {} as HTMLInputElement;

    const refs = makeFocusElements({
      customBrandInput,
      customModelInput,
      customTypeInput,
      manualAddButton,
      tireWidthInput,
    });

    expect(resolveWizardFocusTarget("brand-option", refs)).toBe(customBrandInput);
    expect(resolveWizardFocusTarget("model-option", refs)).toBe(customModelInput);
    expect(resolveWizardFocusTarget("type-option", refs)).toBe(customTypeInput);
    expect(resolveWizardFocusTarget("gearbox-option", refs)).toBe(manualAddButton);
    expect(resolveWizardFocusTarget("spec-selection", refs)).toBe(tireWidthInput);
  });

  test("prefers the first available option control before fallback inputs", () => {
    const tireOption = {} as HTMLButtonElement;
    const gearboxOption = {} as HTMLButtonElement;
    const tireWidthInput = {} as HTMLInputElement;
    const brandOption = {} as HTMLButtonElement;
    const customBrandInput = {} as HTMLInputElement;

    expect(
      resolveWizardFocusTarget(
        "spec-selection",
        makeFocusElements({ gearboxOption, tireOption, tireWidthInput }),
      ),
    ).toBe(tireOption);
    expect(
      resolveWizardFocusTarget(
        "gearbox-option",
        makeFocusElements({ gearboxOption, manualAddButton: {} as HTMLButtonElement }),
      ),
    ).toBe(gearboxOption);
    expect(
      resolveWizardFocusTarget(
        "brand-option",
        makeFocusElements({ brandOption, customBrandInput }),
      ),
    ).toBe(brandOption);
  });
});
