import { addSettingsCar as addSettingsCarApi, setActiveSettingsCar as setActiveSettingsCarApi } from "../../api";
import type { CarUpsertRequest, CarsPayload } from "../../api/types";

export interface UiCarCreationCommandDeps {
  getVehicleSettings: () => Record<string, number>;
  syncCarsPayload: (payload: CarsPayload) => void;
  syncActiveCarToInputs: () => void;
  showCarCreationSuccess?: (carId: string, carName: string) => void;
  renderCarList: () => void;
  renderSpectrum: () => void;
  addSettingsCar?: (payload: CarUpsertRequest) => Promise<CarsPayload>;
  setActiveSettingsCar?: (carId: string) => Promise<CarsPayload>;
}

export interface UiCarCreationCommand {
  addCarFromWizard(
    name: string,
    carType: string,
    aspects: Record<string, number>,
    variant?: string,
  ): Promise<void>;
}

export function createUiCarCreationCommand(
  deps: UiCarCreationCommandDeps,
): UiCarCreationCommand {
  const addSettingsCar = deps.addSettingsCar ?? addSettingsCarApi;
  const setActiveSettingsCar = deps.setActiveSettingsCar ?? setActiveSettingsCarApi;

  return {
    async addCarFromWizard(
      name: string,
      carType: string,
      aspects: Record<string, number>,
      variant?: string,
    ): Promise<void> {
      try {
        const fullAspects = { ...deps.getVehicleSettings(), ...aspects };
        const payload: CarUpsertRequest = { name, type: carType, aspects: fullAspects };
        if (variant) {
          payload.variant = variant;
        }
        const result = await addSettingsCar(payload);
        if (!Array.isArray(result.cars)) {
          return;
        }
        deps.syncCarsPayload(result);
        const newCar = result.cars[result.cars.length - 1];
        if (newCar) {
          const setResult = await setActiveSettingsCar(newCar.id);
          deps.syncCarsPayload(setResult);
        }
        deps.syncActiveCarToInputs();
        if (newCar) {
          deps.showCarCreationSuccess?.(newCar.id, newCar.name);
        }
        deps.renderCarList();
        deps.renderSpectrum();
      } catch (_err) {
        // Preserve the current silent wizard failure behavior while removing
        // the cross-feature dependency from CarsFeature to SettingsFeature.
      }
    },
  };
}
