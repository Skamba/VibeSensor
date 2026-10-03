import { useRef } from "preact/hooks";
import type { JSX } from "preact";

import type { CarsFeatureFocusTarget } from "../features/cars_feature";
import {
  computed,
  signal,
  type Signal,
  type ReadonlySignal,
} from "../ui_signals";
import {
  createClosedCarsWizardRenderModel,
  type CarsWizardRenderModel,
} from "./car_wizard_view";
import {
  CarsListSection,
  type CarsListPanelActionHandlers,
  type CarsListRenderModel,
} from "./cars_list_section";
import {
  CarsWizardPanel,
  type CarsFeatureInteraction,
  type CarsFeatureInteractionHandlers,
} from "./cars_wizard_panel";
import {
  useCarsWizardElementRefs,
  type CarsWizardFocusRequest,
} from "./cars_wizard_focus";
import type { DeferredModelSignal } from "./view_model_binding";

export type { CarsFeatureInteraction, CarsFeatureInteractionHandlers } from "./cars_wizard_panel";
export type { CarsListRenderModel } from "./cars_list_section";

export interface CarsListPanelView {
  actions: Signal<{ onAction(action: import("./settings_car_list_view").CarsListAction): void } | null>;
  model: DeferredModelSignal<CarsListRenderModel>;
}

export interface CarsWizardPanelBridge {
  actions: Signal<CarsFeatureInteractionHandlers | null>;
  focus(target: CarsFeatureFocusTarget): void;
  model: DeferredModelSignal<CarsWizardRenderModel>;
}

export interface CarsPanelView {
  readonly list: CarsListPanelView;
  readonly wizard: CarsWizardPanelBridge;
}

type CarsPanelBridgeState = {
  actions: CarsListPanelActionHandlers | null;
  model: ReadonlySignal<CarsListRenderModel> | null;
  wizardActions: CarsFeatureInteractionHandlers | null;
  wizardModel: ReadonlySignal<CarsWizardRenderModel> | null;
};

const DEFAULT_CARS_PANEL_MODEL: CarsListRenderModel = {
  guidance: null,
  table: null,
};
const DEFAULT_CARS_WIZARD_MODEL = createClosedCarsWizardRenderModel();

function CarsPanel(props: {
  state: ReadonlySignal<CarsPanelBridgeState>;
  wizardFocusRequest: ReadonlySignal<CarsWizardFocusRequest | null>;
}) {
  const state = props.state.value;
  const listActions = state.actions;
  const listModel = state.model?.value ?? DEFAULT_CARS_PANEL_MODEL;
  const wizardActions = signal(state.wizardActions);
  const wizardModel = signal(state.wizardModel?.value ?? DEFAULT_CARS_WIZARD_MODEL);
  const addCarButtonRef = useRef<HTMLButtonElement | null>(null);
  const wizardRefs = useCarsWizardElementRefs();
  const focusRequest = props.wizardFocusRequest.value;
  const openWizard = () => {
    wizardActions.peek()?.onAction({ type: "open" });
  };

  return (
    <>
      <CarsListSection
        actions={listActions}
        addCarButtonRef={addCarButtonRef}
        model={listModel}
        onOpenWizard={openWizard}
      />
      <CarsWizardPanel
        actions={wizardActions}
        addCarButtonRef={addCarButtonRef}
        focusRequest={focusRequest}
        refs={wizardRefs}
        wizardModel={wizardModel}
      />
    </>
  );
}

export function createCarsPanel(
  bindings: {
    list: CarsListPanelView;
    wizard: Omit<CarsWizardPanelBridge, "focus">;
  },
): Pick<CarsWizardPanelBridge, "focus"> & { Panel: () => JSX.Element } {
  const bridgeState = computed<CarsPanelBridgeState>(() => ({
      actions: bindings.list.actions.value,
      model: bindings.list.model.value,
      wizardActions: bindings.wizard.actions.value,
      wizardModel: bindings.wizard.model.value,
    }));
  const wizardFocusRequest = signal<CarsWizardFocusRequest | null>(null);
  let focusRequestToken = 0;
  const Panel = () => (
    <CarsPanel
      state={bridgeState}
      wizardFocusRequest={wizardFocusRequest}
    />
  );

  return {
    Panel,
    focus(target): void {
      focusRequestToken += 1;
      wizardFocusRequest.value = { target, token: focusRequestToken };
    },
  };
}
