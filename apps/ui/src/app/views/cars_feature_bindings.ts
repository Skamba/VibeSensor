import type { UiCarsDom } from "../dom/cars_dom";
import { closestFromTarget } from "./dom_helpers";
import {
  bindViewEvent,
  composeViewDisposers,
  type ViewDisposer,
} from "./dom_event_bindings";

export interface CarsFeatureManualInputState {
  finalDrive: string;
  rim: string;
  tireAspect: string;
  tireWidth: string;
  topGear: string;
}

export type CarsFeatureInteraction =
  | { type: "back" }
  | { type: "close" }
  | { type: "finish" }
  | { type: "manual-inputs-changed"; inputs: CarsFeatureManualInputState }
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

export interface CarsFeatureBindingTargets {
  keyboard: Pick<EventTarget, "addEventListener" | "removeEventListener"> | null;
}

function parseIndex(value: string | null): number | null {
  if (value == null) {
    return null;
  }
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

function readManualInputs(
  dom: Pick<
    UiCarsDom,
    "wizFinalDriveInput" | "wizGearRatioInput" | "wizRimInput" | "wizTireAspectInput" | "wizTireWidthInput"
  >,
): CarsFeatureManualInputState {
  return {
    finalDrive: dom.wizFinalDriveInput?.value ?? "",
    rim: dom.wizRimInput?.value ?? "",
    tireAspect: dom.wizTireAspectInput?.value ?? "",
    tireWidth: dom.wizTireWidthInput?.value ?? "",
    topGear: dom.wizGearRatioInput?.value ?? "",
  };
}

function bindIndexedOptionClick(
  target: HTMLElement | null,
  selector: string,
  readAction: (button: HTMLButtonElement) => CarsFeatureInteraction | null,
  handlers: CarsFeatureInteractionHandlers,
): ViewDisposer {
  return bindViewEvent(target, "click", (event: MouseEvent) => {
    const button = closestFromTarget<HTMLButtonElement>(event.target, selector);
    const action = button ? readAction(button) : null;
    if (action) {
      handlers.onAction(action);
    }
  });
}

export function bindCarsFeatureInteractions(
  dom: Pick<
    UiCarsDom,
    | "addCarBtn"
    | "addCarWizard"
    | "wizFinalDriveInput"
    | "wizGearRatioInput"
    | "wizRimInput"
    | "wizTireAspectInput"
    | "wizTireWidthInput"
    | "wizardBackdrop"
    | "wizardBackBtn"
    | "wizardBrandList"
    | "wizardCloseBtn"
    | "wizardCustomBrandBtn"
    | "wizardCustomBrandInput"
    | "wizardCustomModelBtn"
    | "wizardCustomModelInput"
    | "wizardCustomTypeBtn"
    | "wizardCustomTypeInput"
    | "wizardGearboxList"
    | "wizardManualAddBtn"
    | "wizardModelList"
    | "wizardTireList"
    | "wizardTypeList"
    | "wizardVariantList"
  >,
  handlers: CarsFeatureInteractionHandlers,
  targets?: Partial<CarsFeatureBindingTargets>,
): ViewDisposer {
  const keyboardTarget = targets?.keyboard ?? (typeof document === "undefined" ? null : document);

  return composeViewDisposers(
    bindViewEvent(dom.addCarBtn, "click", () => {
      handlers.onAction({ type: "open" });
    }),
    bindViewEvent(dom.wizardCloseBtn, "click", () => {
      handlers.onAction({ type: "close" });
    }),
    bindViewEvent(dom.wizardBackdrop, "click", () => {
      handlers.onAction({ type: "close" });
    }),
    bindViewEvent(dom.wizardBackBtn, "click", () => {
      handlers.onAction({ type: "back" });
    }),
    bindViewEvent<KeyboardEvent>(keyboardTarget, "keydown", (event) => {
      if (event.key === "Escape" && !dom.addCarWizard.hidden) {
        event.preventDefault();
        handlers.onAction({ type: "close" });
      }
    }),
    bindIndexedOptionClick(
      dom.wizardBrandList,
      ".wiz-opt[data-value]",
      (button) => ({
        type: "select-brand",
        value: button.getAttribute("data-value") ?? "",
      }),
      handlers,
    ),
    bindIndexedOptionClick(
      dom.wizardTypeList,
      ".wiz-opt[data-value]",
      (button) => ({
        type: "select-type",
        value: button.getAttribute("data-value") ?? "",
      }),
      handlers,
    ),
    bindIndexedOptionClick(
      dom.wizardModelList,
      ".wiz-opt[data-idx]",
      (button) => {
        const index = parseIndex(button.getAttribute("data-idx"));
        return index == null ? null : { type: "select-model", index };
      },
      handlers,
    ),
    bindIndexedOptionClick(
      dom.wizardVariantList,
      ".wiz-opt[data-idx]",
      (button) => {
        const index = parseIndex(button.getAttribute("data-idx"));
        return index == null ? null : { type: "select-variant", index };
      },
      handlers,
    ),
    bindIndexedOptionClick(
      dom.wizardTireList,
      ".wiz-opt[data-tire-idx]",
      (button) => {
        const index = parseIndex(button.getAttribute("data-tire-idx"));
        return index == null ? null : { type: "select-tire", index };
      },
      handlers,
    ),
    bindIndexedOptionClick(
      dom.wizardGearboxList,
      ".wiz-opt[data-idx]",
      (button) => {
        const index = parseIndex(button.getAttribute("data-idx"));
        return index == null ? null : { type: "select-gearbox", index };
      },
      handlers,
    ),
    bindViewEvent(dom.wizardCustomBrandBtn, "click", () => {
      handlers.onAction({
        type: "submit-custom-brand",
        value: dom.wizardCustomBrandInput?.value?.trim() ?? "",
      });
    }),
    bindViewEvent(dom.wizardCustomTypeBtn, "click", () => {
      handlers.onAction({
        type: "submit-custom-type",
        value: dom.wizardCustomTypeInput?.value?.trim() ?? "",
      });
    }),
    bindViewEvent(dom.wizardCustomModelBtn, "click", () => {
      handlers.onAction({
        type: "submit-custom-model",
        value: dom.wizardCustomModelInput?.value?.trim() ?? "",
      });
    }),
    bindViewEvent(dom.wizardManualAddBtn, "click", () => {
      handlers.onAction({ type: "finish" });
    }),
    bindViewEvent(dom.wizTireWidthInput, "input", () => {
      handlers.onAction({ type: "manual-inputs-changed", inputs: readManualInputs(dom) });
    }),
    bindViewEvent(dom.wizTireAspectInput, "input", () => {
      handlers.onAction({ type: "manual-inputs-changed", inputs: readManualInputs(dom) });
    }),
    bindViewEvent(dom.wizRimInput, "input", () => {
      handlers.onAction({ type: "manual-inputs-changed", inputs: readManualInputs(dom) });
    }),
    bindViewEvent(dom.wizFinalDriveInput, "input", () => {
      handlers.onAction({ type: "manual-inputs-changed", inputs: readManualInputs(dom) });
    }),
    bindViewEvent(dom.wizGearRatioInput, "input", () => {
      handlers.onAction({ type: "manual-inputs-changed", inputs: readManualInputs(dom) });
    }),
  );
}
