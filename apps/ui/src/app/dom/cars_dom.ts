import { getById, requiredById } from "./dom_query";

const CARS_OWNER = "Cars feature";

export interface UiCarsDom {
  addCarBtn: HTMLButtonElement;
  wizardBackdrop: HTMLElement | null;
  addCarWizard: HTMLElement;
  wizardProgressText: HTMLElement | null;
  wizardCloseBtn: HTMLButtonElement | null;
  wizardBackBtn: HTMLButtonElement | null;
  wizardSteps: Array<HTMLElement | null>;
  wizardStepDots: HTMLElement[];
  wizardSummaryPanel: HTMLElement | null;
  wizardActionHint: HTMLElement | null;
  wizardBrandList: HTMLElement | null;
  wizardTypeList: HTMLElement | null;
  wizardModelList: HTMLElement | null;
  wizardVariantList: HTMLElement | null;
  wizardTireList: HTMLElement | null;
  wizardGearboxList: HTMLElement | null;
  wizardCustomBrandInput: HTMLInputElement | null;
  wizardCustomBrandBtn: HTMLButtonElement | null;
  wizardCustomTypeInput: HTMLInputElement | null;
  wizardCustomTypeBtn: HTMLButtonElement | null;
  wizardCustomModelInput: HTMLInputElement | null;
  wizardCustomModelBtn: HTMLButtonElement | null;
  wizardManualAddBtn: HTMLButtonElement | null;
  wizTireWidthInput: HTMLInputElement | null;
  wizTireAspectInput: HTMLInputElement | null;
  wizRimInput: HTMLInputElement | null;
  wizFinalDriveInput: HTMLInputElement | null;
  wizGearRatioInput: HTMLInputElement | null;
}

export function createUiCarsDom(): UiCarsDom {
  return {
    addCarBtn: requiredById<HTMLButtonElement>("addCarBtn", CARS_OWNER),
    wizardBackdrop: getById<HTMLElement>("wizardBackdrop"),
    addCarWizard: requiredById<HTMLElement>("addCarWizard", CARS_OWNER),
    wizardProgressText: getById<HTMLElement>("wizardProgressText"),
    wizardCloseBtn: getById<HTMLButtonElement>("wizardCloseBtn"),
    wizardBackBtn: getById<HTMLButtonElement>("wizardBackBtn"),
    wizardSteps: [0, 1, 2, 3, 4].map((index) => getById<HTMLElement>(`wizardStep${index}`)),
    wizardStepDots: Array.from(document.querySelectorAll<HTMLElement>(".wizard-step-dot")),
    wizardSummaryPanel: getById<HTMLElement>("wizardSummaryPanel"),
    wizardActionHint: getById<HTMLElement>("wizardActionHint"),
    wizardBrandList: getById<HTMLElement>("wizardBrandList"),
    wizardTypeList: getById<HTMLElement>("wizardTypeList"),
    wizardModelList: getById<HTMLElement>("wizardModelList"),
    wizardVariantList: getById<HTMLElement>("wizardVariantList"),
    wizardTireList: getById<HTMLElement>("wizardTireList"),
    wizardGearboxList: getById<HTMLElement>("wizardGearboxList"),
    wizardCustomBrandInput: getById<HTMLInputElement>("wizardCustomBrand"),
    wizardCustomBrandBtn: getById<HTMLButtonElement>("wizardCustomBrandBtn"),
    wizardCustomTypeInput: getById<HTMLInputElement>("wizardCustomType"),
    wizardCustomTypeBtn: getById<HTMLButtonElement>("wizardCustomTypeBtn"),
    wizardCustomModelInput: getById<HTMLInputElement>("wizardCustomModel"),
    wizardCustomModelBtn: getById<HTMLButtonElement>("wizardCustomModelBtn"),
    wizardManualAddBtn: getById<HTMLButtonElement>("wizardManualAddBtn"),
    wizTireWidthInput: getById<HTMLInputElement>("wizTireWidth"),
    wizTireAspectInput: getById<HTMLInputElement>("wizTireAspect"),
    wizRimInput: getById<HTMLInputElement>("wizRim"),
    wizFinalDriveInput: getById<HTMLInputElement>("wizFinalDrive"),
    wizGearRatioInput: getById<HTMLInputElement>("wizGearRatio"),
  };
}
