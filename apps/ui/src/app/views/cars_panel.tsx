import { render } from "preact";
import { useRef } from "preact/hooks";

import type { CarsFeatureFocusTarget } from "../features/cars_feature_workflow";
import {
  signal,
  useSignalEffect,
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
  resolveWizardFocusTarget,
  type CarsFeatureInteraction,
  type CarsFeatureInteractionHandlers,
  type CarsWizardElementRefs,
  type CarsWizardFocusRequest,
  type CarsWizardOptionRefs,
} from "./cars_wizard_panel";

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

function focusElement(target: HTMLElement | null | undefined): void {
  target?.focus();
}

function CarsPanel(props: {
  state: ReadonlySignal<CarsPanelBridgeState>;
  wizardFocusRequest: ReadonlySignal<CarsWizardFocusRequest | null>;
}) {
  const state = props.state.value;
  const model = state.model?.value ?? DEFAULT_CARS_PANEL_MODEL;
  const wizardModel = state.wizardModel?.value ?? createClosedCarsWizardRenderModel();
  const addCarBtnRef = useRef<HTMLButtonElement | null>(null);
  const addCarWizardRef = useRef<HTMLDivElement | null>(null);
  const wizardCloseBtnRef = useRef<HTMLButtonElement | null>(null);
  const wizardCustomBrandInputRef = useRef<HTMLInputElement | null>(null);
  const wizardCustomModelInputRef = useRef<HTMLInputElement | null>(null);
  const wizardCustomTypeInputRef = useRef<HTMLInputElement | null>(null);
  const wizardManualAddBtnRef = useRef<HTMLButtonElement | null>(null);
  const wizFinalDriveInputRef = useRef<HTMLInputElement | null>(null);
  const wizGearRatioInputRef = useRef<HTMLInputElement | null>(null);
  const wizRimInputRef = useRef<HTMLInputElement | null>(null);
  const wizTireAspectInputRef = useRef<HTMLInputElement | null>(null);
  const wizTireWidthInputRef = useRef<HTMLInputElement | null>(null);
  const optionRefs = useRef<CarsWizardOptionRefs>({
    brandOption: null,
    gearboxOption: null,
    modelOption: null,
    tireOption: null,
    typeOption: null,
    variantOption: null,
  });
  const lastReturnFocusTargetRef = useRef<HTMLElement | null>(null);
  const lastWizardOpenStateRef = useRef(wizardModel.isOpen);

  useSignalEffect(() => {
    const isOpen = props.state.value.wizardModel?.value.isOpen ?? false;
    const wasOpen = lastWizardOpenStateRef.current;
    if (isOpen && !wasOpen) {
      const activeElement = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
      lastReturnFocusTargetRef.current =
        activeElement && activeElement !== document.body ? activeElement : addCarBtnRef.current;
      queueMicrotask(() => {
        if (addCarWizardRef.current) {
          addCarWizardRef.current.scrollTop = 0;
        }
      });
    }
    if (!isOpen && wasOpen) {
      const target = lastReturnFocusTargetRef.current;
      lastReturnFocusTargetRef.current = null;
      queueMicrotask(() => {
        const safeTarget = target && document.contains(target) ? target : addCarBtnRef.current;
        focusElement(safeTarget);
      });
    }
    lastWizardOpenStateRef.current = isOpen;
  });

  useSignalEffect(() => {
    const wizardFocusRequest = props.wizardFocusRequest.value;
    if (!wizardFocusRequest) {
      return;
    }
    queueMicrotask(() => {
      focusElement(
        resolveWizardFocusTarget(wizardFocusRequest.target, {
          closeButton: wizardCloseBtnRef.current,
          customBrandInput: wizardCustomBrandInputRef.current,
          customModelInput: wizardCustomModelInputRef.current,
          customTypeInput: wizardCustomTypeInputRef.current,
          finalDriveInput: wizFinalDriveInputRef.current,
          manualAddButton: wizardManualAddBtnRef.current,
          optionRefs: optionRefs.current,
          rimInput: wizRimInputRef.current,
          tireAspectInput: wizTireAspectInputRef.current,
          tireWidthInput: wizTireWidthInputRef.current,
          topGearInput: wizGearRatioInputRef.current,
        }),
      );
    });
  });

  const wizardRefs: CarsWizardElementRefs = {
    addCarWizardRef,
    optionRefs,
    wizardCloseBtnRef,
    wizardCustomBrandInputRef,
    wizardCustomModelInputRef,
    wizardCustomTypeInputRef,
    wizardManualAddBtnRef,
    wizFinalDriveInputRef,
    wizGearRatioInputRef,
    wizRimInputRef,
    wizTireAspectInputRef,
    wizTireWidthInputRef,
  };

  return (
    <>
      <CarsListSection
        actions={state.actions}
        addCarButtonRef={addCarBtnRef}
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
