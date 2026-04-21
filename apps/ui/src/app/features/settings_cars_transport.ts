import {
  addSettingsCar,
  deleteSettingsCar,
  getSettingsCars,
  setActiveSettingsCar,
} from "../../api";
import type { CarUpsertRequest, CarsPayload } from "../../api/types";

export interface SettingsCarsTransport {
  activateCar(carId: string): Promise<CarsPayload>;
  createCar(payload: CarUpsertRequest): Promise<CarsPayload>;
  deleteCar(carId: string): Promise<CarsPayload>;
  loadCars(): Promise<CarsPayload>;
}

export function createSettingsCarsTransport(
  overrides: Partial<SettingsCarsTransport> | undefined,
): SettingsCarsTransport {
  return {
    activateCar: overrides?.activateCar ?? setActiveSettingsCar,
    createCar: overrides?.createCar ?? addSettingsCar,
    deleteCar: overrides?.deleteCar ?? deleteSettingsCar,
    loadCars: overrides?.loadCars ?? getSettingsCars,
  };
}
