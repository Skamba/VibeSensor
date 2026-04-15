import {
  buildCarsWizardRenderModel,
  type CarsWizardRenderModel,
} from "./car_wizard_view";
import type {
  CarsFeatureFocusTarget,
  CarsFeatureRenderState,
} from "../features/cars_feature_workflow";
import type { CarsWizardPanelBridge } from "./cars_panel";

export interface CarsFeaturePresenterDeps {
  fmt: (value: number, digits?: number) => string;
  panel: CarsWizardPanelBridge;
  t: (key: string, vars?: Record<string, unknown>) => string;
}

export interface CarsFeaturePresenter {
  focus(target: CarsFeatureFocusTarget): void;
  render(state: CarsFeatureRenderState): void;
}

export function createCarsFeaturePresenter(
  deps: CarsFeaturePresenterDeps,
): CarsFeaturePresenter {
  const { fmt, panel, t } = deps;

  function renderWizard(state: CarsFeatureRenderState): CarsWizardRenderModel {
    return buildCarsWizardRenderModel(state, { fmt, t });
  }

  return {
    focus(target): void {
      panel.focus(target);
    },
    render(state): void {
      panel.setModel(renderWizard(state));
    },
  };
}
