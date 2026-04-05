import type { FeatureDepsBase } from "../feature_deps_base";
import type { UiCarsDom } from "../dom/cars_dom";
import {
  bindCarsFeatureInteractions,
  type CarsFeatureInteraction,
} from "../views/cars_feature_bindings";
import { createCarsFeaturePresenter } from "../views/cars_feature_presenter";
import { createCarsFeatureWorkflow } from "./cars_feature_workflow";

export interface CarsFeatureDeps extends FeatureDepsBase {
  addCarFromWizard: (
    name: string,
    carType: string,
    aspects: Record<string, number>,
    variant?: string,
  ) => Promise<void>;
  dom: UiCarsDom;
  fmt: (n: number, digits?: number) => string;
}

export interface CarsFeature {
  bindWizardHandlers(): void;
  openWizard(): void;
}

export function createCarsFeature(ctx: CarsFeatureDeps): CarsFeature {
  const presenter = createCarsFeaturePresenter({
    dom: ctx.dom,
    escapeHtml: ctx.escapeHtml,
    fmt: ctx.fmt,
    t: ctx.t,
  });
  const workflow = createCarsFeatureWorkflow({
    addCarFromWizard: ctx.addCarFromWizard,
    fmt: ctx.fmt,
    t: ctx.t,
    view: presenter,
  });
  let handlersBound = false;
  let lastFocusTarget: HTMLElement | null = null;

  function restoreFocus(): void {
    presenter.restoreFocus(lastFocusTarget);
    lastFocusTarget = null;
  }

  function openWizard(): void {
    lastFocusTarget = presenter.captureReturnFocusTarget();
    void workflow.openWizard(presenter.readManualInputs());
  }

  async function handleInteraction(action: CarsFeatureInteraction): Promise<void> {
    if (action.type === "open") {
      openWizard();
      return;
    }
    if (action.type === "close") {
      workflow.closeWizard();
      restoreFocus();
      return;
    }
    if (action.type === "back") {
      await workflow.goBack();
      return;
    }
    if (action.type === "select-brand") {
      await workflow.selectBrand(action.value);
      return;
    }
    if (action.type === "select-type") {
      await workflow.selectType(action.value);
      return;
    }
    if (action.type === "select-model") {
      await workflow.selectModel(action.index);
      return;
    }
    if (action.type === "select-variant") {
      await workflow.selectVariant(action.index);
      return;
    }
    if (action.type === "select-tire") {
      workflow.selectTire(action.index);
      return;
    }
    if (action.type === "select-gearbox") {
      workflow.selectGearbox(action.index);
      return;
    }
    if (action.type === "submit-custom-brand") {
      await workflow.submitCustomBrand(action.value);
      return;
    }
    if (action.type === "submit-custom-type") {
      await workflow.submitCustomType(action.value);
      return;
    }
    if (action.type === "submit-custom-model") {
      await workflow.submitCustomModel(action.value);
      return;
    }
    if (action.type === "manual-inputs-changed") {
      workflow.handleManualInputsChanged(action.inputs);
      return;
    }
    if (await workflow.finishWizard()) {
      restoreFocus();
    }
  }

  return {
    bindWizardHandlers(): void {
      if (handlersBound) {
        return;
      }
      handlersBound = true;
      bindCarsFeatureInteractions(ctx.dom, {
        onAction: (action) => {
          void handleInteraction(action);
        },
      });
    },
    openWizard,
  };
}
