import type { QueryClient } from "@tanstack/query-core";

import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import {
  createCarSelectionDerivedState,
  type CarSelectionState,
  getCarCompleteness,
} from "../car_selection_state";
import {
  composeVehicleSettings,
  mergeCarAspectSettings,
  type SettingsState,
} from "../ui_app_state";
import type {
  CarOrderReferenceStatus,
  CarRecord,
  CarsPayload,
  CarUpsertRequest,
} from "../../api/types";
import type {
  CarsListPanelView,
  CarsListRenderModel,
} from "../views/cars_panel";
import type { AnalysisPanelView } from "../views/analysis_panel";
import {
  computed,
  effect,
  signal,
  untracked,
  type ReadonlySignal,
} from "../ui_signals";
import {
  buildCarsGuidanceRenderModel,
  createSettingsCarListRenderModelMemo,
  type CarsListHighlightedFeedback,
} from "../views/settings_car_list_view";
import {
  createSettingsCarsTransport,
  type SettingsCarsTransport,
} from "./settings_cars_transport";
import { applyCarsPayloadToSettings } from "./dashboard_startup_state";
import { serverStateQueryKeys } from "./server_state_query_keys";

interface SettingsCarsModulePanels {
  analysisPanel: Pick<AnalysisPanelView, "carAvailability">;
  panel: CarsListPanelView;
}

interface SettingsCarsModulePorts {
  activeViewId: ReadonlySignal<string>;
  activeSettingsTabId: ReadonlySignal<string>;
  openAnalysisTab: () => void;
  openCarWizard: () => void;
  refreshSpectrumDecorations: () => void;
  syncAnalysisInputs: () => void;
}

export interface SettingsCarsModuleDeps {
  settings: SettingsState;
  queryClient: QueryClient;
  panels: SettingsCarsModulePanels;
  ports: SettingsCarsModulePorts;
  services: FeatureServices;
  formatting: Pick<FeatureFormatting, "fmt">;
  transport?: Partial<SettingsCarsTransport>;
}

export interface SettingsCarsModule {
  addCarFromWizard(
    name: string,
    carType: string,
    aspects: Record<string, number>,
    orderReferenceStatus?: CarOrderReferenceStatus,
    variant?: string,
  ): Promise<void>;
  bindHandlers(): void;
  dispose(): void;
  hasValidActiveCar(): boolean;
  loadCarsFromServer(): Promise<void>;
  renderCarList(): void;
  showCarCreationSuccess(carId: string, carName: string): void;
  syncActiveCarToInputs(): void;
  syncCarsPayload(payload: CarsPayload): void;
}

function copyActiveCarAspects(
  car: CarRecord | null,
  settings: SettingsState,
): void {
  if (!car?.aspects || typeof car.aspects !== "object") {
    return;
  }
  settings.car.activeVehicleSettings.value = mergeCarAspectSettings(
    settings.car.activeVehicleSettings.value,
    car.aspects,
  );
}

export function createSettingsCarsModule(
  ctx: SettingsCarsModuleDeps,
): SettingsCarsModule {
  const { settings, services, formatting } = ctx;
  const { t } = services;
  const transport = createSettingsCarsTransport(ctx.transport);
  const carSelection = createCarSelectionDerivedState(settings.car);
  let handlersBound = false;
  let disposeHighlightedCarSync: (() => void) | null = null;
  const highlightedCar = signal<CarsListHighlightedFeedback | null>(null);
  const carsContextVisible = computed(
    () =>
      ctx.ports.activeViewId.value === "settingsView" &&
      ctx.ports.activeSettingsTabId.value === "carTab",
  );
  const buildCarListRenderModel = createSettingsCarListRenderModelMemo();

  function hasValidActiveCar(): boolean {
    return carSelection.hasResolvedActiveCar.value;
  }

  function getCarSelectionState(): CarSelectionState {
    return carSelection.selection.value;
  }

  function createPanelModel(
    carSelectionState: CarSelectionState,
  ): CarsListRenderModel {
    return {
      guidance: buildCarsGuidanceRenderModel({
        carSelectionState,
        highlightedCarFeedback: highlightedCar.value,
        t,
      }),
      table:
        carSelectionState.kind === "loading"
          ? null
          : buildCarListRenderModel({
              activeCarId: settings.car.activeCarId.value,
              cars: settings.car.cars.value,
              highlightedCarId: highlightedCar.value?.carId ?? null,
              fmt: formatting.fmt,
              t,
            }),
    };
  }
  const analysisAvailability = computed(() => {
    const carSelectionState = carSelection.selection.value;
    return {
      hasActiveCar: carSelectionState.kind === "active",
      isLoading: carSelectionState.kind === "loading",
    };
  });
  const panelModel = computed(() => createPanelModel(getCarSelectionState()));
  ctx.panels.analysisPanel.carAvailability.value = analysisAvailability;
  ctx.panels.panel.model.value = panelModel;

  function renderCarList(): void {}

  function clearHighlightedCarFeedback(): void {
    highlightedCar.value = null;
  }

  function showCarCreationSuccess(carId: string, carName: string): void {
    highlightedCar.value = { carId, carName };
  }

  function syncCarsPayload(payload: CarsPayload): void {
    applyCarsPayloadToSettings(settings.car, payload);
    if (
      highlightedCar.value &&
      !settings.car.cars.value.some(
        (car) => car.id === highlightedCar.value?.carId,
      )
    ) {
      highlightedCar.value = null;
    }
  }

  function findCar(carId: string): CarRecord | null {
    return settings.car.cars.value.find((entry) => entry.id === carId) ?? null;
  }

  function syncActiveCarToInputs(): void {
    copyActiveCarAspects(carSelection.activeCar.value, settings);
    if (hasValidActiveCar()) {
      ctx.ports.syncAnalysisInputs();
    }
  }

  async function addCarFromWizard(
    name: string,
    carType: string,
    aspects: Record<string, number>,
    orderReferenceStatus?: CarOrderReferenceStatus,
    variant?: string,
  ): Promise<void> {
    try {
      const payload: CarUpsertRequest = {
        aspects: {
          ...composeVehicleSettings(
            settings.car.activeVehicleSettings.value,
            settings.analysis.vehicleSettings.value,
          ),
          ...aspects,
        },
        name,
        type: carType,
      };
      if (orderReferenceStatus) {
        payload.order_reference_status = orderReferenceStatus;
      }
      if (variant) {
        payload.variant = variant;
      }
      const createdPayload = await transport.createCar(payload);
      if (!Array.isArray(createdPayload.cars)) {
        return;
      }
      ctx.queryClient.setQueryData(
        serverStateQueryKeys.settings.cars(),
        createdPayload,
      );
      syncCarsPayload(createdPayload);
      const newCar = createdPayload.cars[createdPayload.cars.length - 1];
      if (!newCar) {
        return;
      }
      const activatedPayload = await transport.activateCar(newCar.id);
      ctx.queryClient.setQueryData(
        serverStateQueryKeys.settings.cars(),
        activatedPayload,
      );
      syncCarsPayload(activatedPayload);
      syncActiveCarToInputs();
      showCarCreationSuccess(newCar.id, newCar.name);
      ctx.ports.refreshSpectrumDecorations();
    } catch (_err) {
      // Preserve the current wizard behavior: failed creation does not close over
      // extra UI state or grow a second error-handling path outside settings.
    }
  }

  async function loadCarsFromServer(): Promise<void> {
    const payload = await ctx.queryClient.fetchQuery({
      queryFn: () => transport.loadCars(),
      queryKey: serverStateQueryKeys.settings.cars(),
      staleTime: 0,
    });
    syncCarsPayload(payload);
    syncActiveCarToInputs();
  }

  async function handleActivateCar(carId: string): Promise<void> {
    if (!carId) {
      return;
    }
    const car = findCar(carId);
    if (!car) {
      return;
    }
    if (!getCarCompleteness(car).isComplete) {
      services.showError(t("settings.car.activate_incomplete"));
      return;
    }
    try {
      const payload = await transport.activateCar(carId);
      ctx.queryClient.setQueryData(
        serverStateQueryKeys.settings.cars(),
        payload,
      );
      syncCarsPayload(payload);
      syncActiveCarToInputs();
      clearHighlightedCarFeedback();
      ctx.ports.refreshSpectrumDecorations();
    } catch (_err) {
      services.showError(t("settings.car.activate_failed"));
    }
  }

  async function handleCompleteCar(carId: string): Promise<void> {
    if (!carId) {
      return;
    }
    const car = findCar(carId);
    if (!car) {
      return;
    }
    try {
      if (car.id !== settings.car.activeCarId.value) {
        const payload = await transport.activateCar(carId);
        ctx.queryClient.setQueryData(
          serverStateQueryKeys.settings.cars(),
          payload,
        );
        syncCarsPayload(payload);
        syncActiveCarToInputs();
        ctx.ports.refreshSpectrumDecorations();
      }
      clearHighlightedCarFeedback();
      ctx.ports.openAnalysisTab();
    } catch (_err) {
      services.showError(t("settings.car.activate_failed"));
    }
  }

  async function handleDeleteCar(carId: string): Promise<void> {
    if (!carId) {
      return;
    }
    const car = findCar(carId);
    const confirmed = await services.requestConfirmation(
      t("settings.car.delete_confirm", { name: car?.name || "" }),
    );
    if (!confirmed) {
      return;
    }
    try {
      const payload = await transport.deleteCar(carId);
      ctx.queryClient.setQueryData(
        serverStateQueryKeys.settings.cars(),
        payload,
      );
      syncCarsPayload(payload);
      syncActiveCarToInputs();
      clearHighlightedCarFeedback();
      ctx.ports.refreshSpectrumDecorations();
    } catch (_err) {
      services.showError(t("settings.car.delete_failed"));
    }
  }

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    disposeHighlightedCarSync = effect(() => {
      if (highlightedCar.value && !carsContextVisible.value) {
        untracked(clearHighlightedCarFeedback);
      }
    });
    ctx.panels.panel.actions.value = {
      onAction: (action) => {
        if (action.type === "add") {
          ctx.ports.openCarWizard();
          return;
        }
        if (action.type === "activate") {
          if (action.carId) {
            void handleActivateCar(action.carId);
          }
          return;
        }
        if (action.type === "complete") {
          if (action.carId) {
            void handleCompleteCar(action.carId);
          }
          return;
        }
        if (action.carId) {
          void handleDeleteCar(action.carId);
        }
      },
    };
  }

  return {
    addCarFromWizard,
    bindHandlers,
    dispose(): void {
      disposeHighlightedCarSync?.();
      disposeHighlightedCarSync = null;
    },
    hasValidActiveCar,
    loadCarsFromServer,
    renderCarList,
    showCarCreationSuccess,
    syncActiveCarToInputs,
    syncCarsPayload,
  };
}
