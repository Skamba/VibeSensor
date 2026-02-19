import { apiJson } from "./http";
import type { CarLibraryModel } from "./types";

export async function getCarLibraryBrands(): Promise<{ brands: string[] }> {
  return apiJson("/api/car-library/brands");
}

export async function getCarLibraryTypes(brand: string): Promise<{ types: string[] }> {
  return apiJson(`/api/car-library/types?brand=${encodeURIComponent(brand)}`);
}

export async function getCarLibraryModels(brand: string, type: string): Promise<{ models: CarLibraryModel[] }> {
  return apiJson(`/api/car-library/models?brand=${encodeURIComponent(brand)}&type=${encodeURIComponent(type)}`);
}
