import { apiJson } from "./http";
import type { CarLibraryBrandsPayload, CarLibraryModelsPayload, CarLibraryTypesPayload } from "./types";

export async function getCarLibraryBrands(): Promise<CarLibraryBrandsPayload> {
  return apiJson("/api/car-library/brands");
}

export async function getCarLibraryTypes(brand: string): Promise<CarLibraryTypesPayload> {
  return apiJson(`/api/car-library/types?brand=${encodeURIComponent(brand)}`);
}

export async function getCarLibraryModels(brand: string, type: string): Promise<CarLibraryModelsPayload> {
  return apiJson(`/api/car-library/models?brand=${encodeURIComponent(brand)}&type=${encodeURIComponent(type)}`);
}
