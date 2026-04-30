import type { QueryClient } from "@tanstack/query-core";

import type { CarOrderReferenceStatus } from "../../api/types";
import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import type {
  CarsFeatureInteraction,
  CarsWizardPanelBridge,
} from "../views/cars_panel";
import { buildCarsWizardRenderModel } from "../views/car_wizard_view";
import { computed } from "../ui_signals";
import { createCarsFeatureWorkflow } from "./cars_feature_workflow";

export interface CarsFeatureDeps {
  addCarFromWizard: (
    name: string,
    carType: string,
    aspects: Record<string, number | string>,
    orderReferenceStatus?: CarOrderReferenceStatus,
    variant?: string,
  ) => Promise<void>;
  panel: CarsWizardPanelBridge;
  services: Pick<FeatureServices, "t">;
  formatting: Pick<FeatureFormatting, "fmt">;
  queryClient: QueryClient;
}

export interface CarsFeature {
  bindWizardHandlers(): void;
  dispose(): void;
  openWizard(): void;
}

export function createCarsFeature(ctx: CarsFeatureDeps): CarsFeature {
  const workflow = createCarsFeatureWorkflow({
    addCarFromWizard: ctx.addCarFromWizard,
    fmt: ctx.formatting.fmt,
    queryClient: ctx.queryClient,
    t: ctx.services.t,
    view: {
      focus(target): void {
        ctx.panel.focus(target);
      },
    },
  });
  const wizardModel = computed(() =>
    buildCarsWizardRenderModel(workflow.renderState.value, {
      fmt: ctx.formatting.fmt,
      t: ctx.services.t,
    }),
  );
  ctx.panel.model.value = wizardModel;
  let handlersBound = false;

  function openWizard(): void {
    void workflow.openWizard();
  }

  async function handleInteraction(
    action: CarsFeatureInteraction,
  ): Promise<void> {
    if (action.type === "open") {
      openWizard();
      return;
    }
    if (action.type === "close") {
      workflow.closeWizard();
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
    if (action.type === "manual-input-changed") {
      workflow.handleManualInputChanged(action.field, action.value);
      return;
    }
    await workflow.finishWizard();
  }

  return {
    bindWizardHandlers(): void {
      if (handlersBound) {
        return;
      }
      handlersBound = true;
      ctx.panel.actions.value = {
        onAction: (action) => {
          void handleInteraction(action);
        },
      };
    },
    dispose(): void {},
    openWizard,
  };
}
