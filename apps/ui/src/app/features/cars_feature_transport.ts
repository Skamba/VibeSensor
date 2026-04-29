import {
  getCarLibraryBrands,
  getCarLibraryModels,
  getCarLibraryTypes,
} from "../../api";
import type { CarLibraryModel } from "../../api";

export interface CarsFeatureTransport {
  loadBrands(): Promise<string[]>;
  loadModels(brand: string, carType: string): Promise<CarLibraryModel[]>;
  loadTypes(brand: string): Promise<string[]>;
}

export function createCarsFeatureTransport(
  overrides: Partial<CarsFeatureTransport> | undefined,
): CarsFeatureTransport {
  return {
    loadBrands: overrides?.loadBrands ?? (async () => (await getCarLibraryBrands()).brands || []),
    loadModels: overrides?.loadModels
      ?? (async (brand, carType) => (await getCarLibraryModels(brand, carType)).models || []),
    loadTypes: overrides?.loadTypes ?? (async (brand) => (await getCarLibraryTypes(brand)).types || []),
  };
}
