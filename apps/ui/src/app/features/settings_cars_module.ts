import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import {
  createCarSelectionDerivedState,
  type CarSelectionState,
  getCarCompleteness,
} from "../car_selection_state";
import type { SettingsState } from "../ui_app_state";
import type { CarRecord, CarsPayload } from "../../api/types";
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
  buildSettingsCarListRenderModel,
  type CarsListHighlightedFeedback,
} from "../views/settings_car_list_view";
import {
  createSettingsCarsTransport,
  type SettingsCarsTransport,
} from "./settings_cars_transport";

interface SettingsCarsModulePanels {
  analysisPanel: Pick<AnalysisPanelView, "carAvailability">;
  panel: CarsListPanelView;
}

interface SettingsCarsModulePorts {
  activeViewId: ReadonlySignal<string>;
  activeSettingsTabId: ReadonlySignal<string>;
  openAnalysisTab: () => void;
  openCarWizard: () => void;
  renderSpectrum: () => void;
  syncAnalysisInputs: () => void;
}

export interface SettingsCarsModuleDeps {
  settings: SettingsState;
  panels: SettingsCarsModulePanels;
  ports: SettingsCarsModulePorts;
  services: FeatureServices;
  formatting: Pick<FeatureFormatting, "fmt">;
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
  const { settings, services, formatting } = ctx;
  const { t } = services;
  const transport = createSettingsCarsTransport(ctx.transport);
  const carSelection = createCarSelectionDerivedState(settings);
  let handlersBound = false;
  const highlightedCar = signal<CarsListHighlightedFeedback | null>(null);
  const carsContextVisible = computed(
    () =>
      ctx.ports.activeViewId.value === "settingsView"
      && ctx.ports.activeSettingsTabId.value === "carTab",
  );

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
      table: carSelectionState.kind === "loading"
        ? null
        : buildSettingsCarListRenderModel({
          activeCarId: settings.activeCarId,
          cars: settings.cars,
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

  function syncCarsPayload(payload: CarsPayload): void {
    settings.cars = payload.cars;
    settings.carsLoaded = true;
    const requestedActiveCarId = payload.active_car_id;
    const hasRequestedActive = requestedActiveCarId
      ? settings.cars.some((car) => car.id === requestedActiveCarId)
      : false;
    settings.activeCarId = hasRequestedActive ? requestedActiveCarId : null;
    if (
      highlightedCar.value
      && !settings.cars.some((car) => car.id === highlightedCar.value?.carId)
    ) {
      highlightedCar.value = null;
    }
  }

  function findCar(carId: string): CarRecord | null {
    return settings.cars.find((entry) => entry.id === carId) ?? null;
  }

  function syncActiveCarToInputs(): void {
    copyActiveCarAspects(carSelection.activeCar.value, settings);
    if (hasValidActiveCar()) {
      ctx.ports.syncAnalysisInputs();
    }
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
      services.showError(t("settings.car.activate_incomplete"));
      return;
    }
    try {
      syncCarsPayload(await transport.activateCar(carId));
      syncActiveCarToInputs();
      clearHighlightedCarFeedback();
      ctx.ports.renderSpectrum();
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
      if (car.id !== settings.activeCarId) {
        syncCarsPayload(await transport.activateCar(carId));
        syncActiveCarToInputs();
        ctx.ports.renderSpectrum();
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
      syncCarsPayload(await transport.deleteCar(carId));
      syncActiveCarToInputs();
      clearHighlightedCarFeedback();
      ctx.ports.renderSpectrum();
    } catch (_err) {
      services.showError(t("settings.car.delete_failed"));
    }
  }

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    effect(() => {
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
    bindHandlers,
    hasValidActiveCar,
    loadCarsFromServer,
    renderCarList,
    showCarCreationSuccess(carId: string, carName: string): void {
      highlightedCar.value = { carId, carName };
    },
    syncActiveCarToInputs,
    syncCarsPayload,
  };
}
