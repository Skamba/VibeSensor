import {
  buildCarsWizardRenderModel,
  type CarsWizardRenderModel,
} from "./car_wizard_view";
import type {
  CarsFeatureFocusTarget,
  CarsFeatureManualInputState,
  CarsFeatureRenderState,
} from "../features/cars_feature_workflow";
import type { CarsWizardPanelBridge } from "./cars_panel";

export interface CarsFeaturePresenterDeps {
  fmt: (value: number, digits?: number) => string;
  panel: CarsWizardPanelBridge;
  t: (key: string, vars?: Record<string, unknown>) => string;
}

export interface CarsFeaturePresenter {
  captureReturnFocusTarget(): HTMLElement | null;
  focus(target: CarsFeatureFocusTarget): void;
  readManualInputs(): CarsFeatureManualInputState;
  render(state: CarsFeatureRenderState): void;
  restoreFocus(target: HTMLElement | null): void;
}

export function createCarsFeaturePresenter(
  deps: CarsFeaturePresenterDeps,
): CarsFeaturePresenter {
  const { fmt, panel, t } = deps;

  function renderWizard(state: CarsFeatureRenderState): CarsWizardRenderModel {
    return buildCarsWizardRenderModel(state, { fmt, t });
  }

  return {
    captureReturnFocusTarget(): HTMLElement | null {
      return panel.captureReturnFocusTarget();
    },
    focus(target): void {
      panel.focus(target);
    },
    readManualInputs(): CarsFeatureManualInputState {
      return panel.readManualInputs();
    },
    render(state): void {
      panel.render(renderWizard(state));
    },
    restoreFocus(target): void {
      panel.restoreFocus(target);
    },
  };
}
