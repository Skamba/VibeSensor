import { requiredById } from "./dom_query";

const CARS_OWNER = "Cars feature";

export function getUiCarsPanelHost(): HTMLElement {
  return requiredById<HTMLElement>("carsPanelRoot", CARS_OWNER);
}

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
