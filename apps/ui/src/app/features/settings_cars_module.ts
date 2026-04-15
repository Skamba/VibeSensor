import type { FeatureDepsBase } from "../feature_deps_base";
import {
  createCarSelectionDerivedState,
  type CarSelectionState,
  getCarCompleteness,
} from "../car_selection_state";
import type { SettingsState } from "../ui_app_state";
import type { CarRecord, CarsPayload } from "../../transport/http_models";
import type {
  CarsListPanelView,
} from "../views/cars_panel";
import type { AnalysisPanelView } from "../views/analysis_panel";
import {
  buildCarsGuidanceRenderModel,
  buildSettingsCarListRenderModel,
  type CarsListHighlightedFeedback,
} from "../views/settings_car_list_view";
import {
  createSettingsCarsTransport,
  type SettingsCarsTransport,
} from "./settings_cars_transport";

export interface SettingsCarsModuleDeps extends FeatureDepsBase {
  confirmDelete?: (message: string) => boolean;
  analysisPanel: Pick<AnalysisPanelView, "setCarAvailability">;
  fmt: (value: number, digits?: number) => string;
  openAnalysisTab: () => void;
  openCarWizard: () => void;
  renderRealtimeLoggingStatus: () => void;
  renderRealtimeStatus: () => void;
  renderSpectrum: () => void;
  settings: SettingsState;
  subscribePrimaryViewChanges(listener: (viewId: string) => void): () => void;
  subscribeSettingsTabChanges(listener: (tabId: string) => void): () => void;
  syncAnalysisInputs: () => void;
  panel: CarsListPanelView;
  transport?: Partial<SettingsCarsTransport>;
}

export interface SettingsCarsModule {
  bindHandlers(): void;
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
  for (const [key, value] of Object.entries(car.aspects)) {
    if (typeof value === "number" && key in settings.vehicleSettings) {
      settings.vehicleSettings[key as keyof SettingsState["vehicleSettings"]] =
        value;
    }
  }
}

export function createSettingsCarsModule(
  ctx: SettingsCarsModuleDeps,
): SettingsCarsModule {
  const { settings, t } = ctx;
  const confirmDelete =
    ctx.confirmDelete ?? ((message: string) => window.confirm(message));
  const transport = createSettingsCarsTransport(ctx.transport);
  const carSelection = createCarSelectionDerivedState(settings);
  let handlersBound = false;
  let highlightedCarFeedback: CarsListHighlightedFeedback | null = null;

  function hasValidActiveCar(): boolean {
    return carSelection.hasResolvedActiveCar.value;
  }

  function getCarSelectionState(): CarSelectionState {
    return carSelection.selection.value;
  }

  function createPanelModel(
    carSelectionState: CarSelectionState,
  ): Parameters<CarsListPanelView["setModel"]>[0] {
    return {
      guidance: buildCarsGuidanceRenderModel({
        carSelectionState,
        highlightedCarFeedback,
        t,
      }),
      table: carSelectionState.kind === "loading"
        ? null
        : buildSettingsCarListRenderModel({
          activeCarId: settings.activeCarId,
          cars: settings.cars,
          highlightedCarId: highlightedCarFeedback?.carId ?? null,
          fmt: ctx.fmt,
          t,
        }),
    };
  }

  function syncAnalysisControls(carSelectionState: CarSelectionState): void {
    ctx.analysisPanel.setCarAvailability({
      hasActiveCar: carSelectionState.kind === "active",
      isLoading: carSelectionState.kind === "loading",
    });
  }

  function renderCarList(): void {
    const carSelectionState = getCarSelectionState();
    syncAnalysisControls(carSelectionState);
    ctx.panel.setModel(createPanelModel(carSelectionState));
  }

  function clearHighlightedCarFeedback(): void {
    highlightedCarFeedback = null;
  }

  function dismissHighlightedCarFeedback(): void {
    if (!highlightedCarFeedback) {
      return;
    }
    clearHighlightedCarFeedback();
    renderCarList();
  }

  function syncCarsPayload(payload: CarsPayload): void {
    settings.cars = payload.cars;
    settings.carsLoaded = true;
    const requestedActiveCarId = payload.active_car_id;
    const hasRequestedActive = requestedActiveCarId
      ? settings.cars.some((car) => car.id === requestedActiveCarId)
      : false;
    settings.activeCarId = hasRequestedActive ? requestedActiveCarId : null;
    if (
      highlightedCarFeedback &&
      !settings.cars.some((car) => car.id === highlightedCarFeedback?.carId)
    ) {
      highlightedCarFeedback = null;
    }
    renderCarList();
    ctx.renderRealtimeStatus();
    ctx.renderRealtimeLoggingStatus();
  }

  function findCar(carId: string): CarRecord | null {
    return settings.cars.find((entry) => entry.id === carId) ?? null;
  }

  function syncActiveCarToInputs(): void {
    copyActiveCarAspects(carSelection.activeCar.value, settings);
    if (hasValidActiveCar()) {
      ctx.syncAnalysisInputs();
    }
    renderCarList();
  }

  async function loadCarsFromServer(): Promise<void> {
    try {
      syncCarsPayload(await transport.loadCars());
      syncActiveCarToInputs();
    } catch (_err) {
      return;
    }
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
      ctx.showError(t("settings.car.activate_incomplete"));
      return;
    }
    try {
      syncCarsPayload(await transport.activateCar(carId));
      syncActiveCarToInputs();
      clearHighlightedCarFeedback();
      renderCarList();
      ctx.renderSpectrum();
    } catch (_err) {
      ctx.showError(t("settings.car.activate_failed"));
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
      let shouldRefreshAfterSelection = highlightedCarFeedback !== null;
      if (car.id !== settings.activeCarId) {
        syncCarsPayload(await transport.activateCar(carId));
        syncActiveCarToInputs();
        ctx.renderSpectrum();
        shouldRefreshAfterSelection = true;
      }
      clearHighlightedCarFeedback();
      if (shouldRefreshAfterSelection) {
        renderCarList();
      }
      ctx.openAnalysisTab();
    } catch (_err) {
      ctx.showError(t("settings.car.activate_failed"));
    }
  }

  async function handleDeleteCar(carId: string): Promise<void> {
    if (!carId) {
      return;
    }
    const car = findCar(carId);
    const confirmed = confirmDelete(
      t("settings.car.delete_confirm", { name: car?.name || "" }),
    );
    if (!confirmed) {
      return;
    }
    try {
      syncCarsPayload(await transport.deleteCar(carId));
      syncActiveCarToInputs();
      clearHighlightedCarFeedback();
      renderCarList();
      ctx.renderSpectrum();
    } catch (_err) {
      ctx.showError(t("settings.car.delete_failed"));
    }
  }

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    ctx.subscribeSettingsTabChanges((tabId) => {
      if (tabId !== "carTab") {
        dismissHighlightedCarFeedback();
      }
    });
    ctx.subscribePrimaryViewChanges((viewId) => {
      if (viewId !== "settingsView") {
        dismissHighlightedCarFeedback();
      }
    });
    ctx.panel.bindActions({
      onAction: (action) => {
        if (action.type === "add") {
          ctx.openCarWizard();
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
    });
  }

  renderCarList();

  return {
    bindHandlers,
    hasValidActiveCar,
    loadCarsFromServer,
    renderCarList,
    showCarCreationSuccess(carId: string, carName: string): void {
      highlightedCarFeedback = { carId, carName };
      renderCarList();
    },
    syncActiveCarToInputs,
    syncCarsPayload,
  };
}
