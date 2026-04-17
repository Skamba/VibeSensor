import {
  deleteSettingsCar,
  getSettingsCars,
  setActiveSettingsCar,
} from "../../api";
import type { CarsPayload } from "../../api/types";

export interface SettingsCarsTransport {
  activateCar(carId: string): Promise<CarsPayload>;
  deleteCar(carId: string): Promise<CarsPayload>;
  loadCars(): Promise<CarsPayload>;
}

export function createSettingsCarsTransport(
  overrides: Partial<SettingsCarsTransport> | undefined,
): SettingsCarsTransport {
  return {
    activateCar: overrides?.activateCar ?? setActiveSettingsCar,
    deleteCar: overrides?.deleteCar ?? deleteSettingsCar,
    loadCars: overrides?.loadCars ?? getSettingsCars,
  };
}
