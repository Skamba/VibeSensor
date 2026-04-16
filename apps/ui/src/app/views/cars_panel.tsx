import { render } from "preact";

import type { CarsFeatureFocusTarget } from "../features/cars_feature_workflow";
import {
  signal,
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
  useCarsWizardFocusManager,
  type CarsWizardFocusRequest,
} from "./cars_wizard_focus";

export type { CarsFeatureInteraction, CarsFeatureInteractionHandlers } from "./cars_wizard_panel";
export type { CarsListRenderModel } from "./cars_list_section";

export interface CarsListPanelView {
  bindActions(handlers: { onAction(action: import("./settings_car_list_view").CarsListAction): void }): void;
  bindModel(model: ReadonlySignal<CarsListRenderModel>): void;
}

export interface CarsWizardPanelBridge {
  bindActions(handlers: CarsFeatureInteractionHandlers): void;
  focus(target: CarsFeatureFocusTarget): void;
  bindModel(model: ReadonlySignal<CarsWizardRenderModel>): void;
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

function CarsPanel(props: {
  state: ReadonlySignal<CarsPanelBridgeState>;
  wizardFocusRequest: ReadonlySignal<CarsWizardFocusRequest | null>;
}) {
  const state = props.state.value;
  const model = state.model?.value ?? DEFAULT_CARS_PANEL_MODEL;
  const wizardModel = state.wizardModel?.value ?? createClosedCarsWizardRenderModel();
  const { addCarButtonRef, wizardRefs } = useCarsWizardFocusManager({
    state: props.state,
    wizardFocusRequest: props.wizardFocusRequest,
  });

  return (
    <>
      <CarsListSection
        actions={state.actions}
        addCarButtonRef={addCarButtonRef}
        model={model}
        onOpenWizard={() => state.wizardActions?.onAction({ type: "open" })}
      />
      <CarsWizardPanel
        actions={state.wizardActions}
        refs={wizardRefs}
        wizardModel={wizardModel}
      />
    </>
  );
}

export function mountCarsPanel(host: HTMLElement): CarsPanelView {
  const bridgeState = signal<CarsPanelBridgeState>({
    actions: null,
    model: null,
    wizardActions: null,
    wizardModel: null,
  });
  const wizardFocusRequest = signal<CarsWizardFocusRequest | null>(null);
  let focusRequestToken = 0;
  render(
    <CarsPanel
      state={bridgeState}
      wizardFocusRequest={wizardFocusRequest}
    />,
    host,
  );

  return {
    list: {
      bindActions(handlers): void {
        bridgeState.value = { ...bridgeState.value, actions: handlers };
      },
      bindModel(model): void {
        bridgeState.value = { ...bridgeState.value, model };
      },
    },
    wizard: {
      bindActions(handlers): void {
        bridgeState.value = { ...bridgeState.value, wizardActions: handlers };
      },
      focus(target): void {
        focusRequestToken += 1;
        wizardFocusRequest.value = { target, token: focusRequestToken };
      },
      bindModel(model): void {
        bridgeState.value = { ...bridgeState.value, wizardModel: model };
      },
    },
  };
}
