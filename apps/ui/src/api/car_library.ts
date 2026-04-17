import { apiJson } from "./http";
import type * as Local from "../api/types";
import type * as Transport from "./types";

export async function getCarLibraryBrands(): Promise<Local.CarLibraryBrandsPayload> {
  return await apiJson<Transport.CarLibraryBrandsPayload>("/api/car-library/brands");
}

export async function getCarLibraryTypes(brand: string): Promise<Local.CarLibraryTypesPayload> {
  return await apiJson<Transport.CarLibraryTypesPayload>(
    `/api/car-library/types?brand=${encodeURIComponent(brand)}`,
  );
}

export async function getCarLibraryModels(
  brand: string,
  type: string,
): Promise<Local.CarLibraryModelsPayload> {
  return await apiJson<Transport.CarLibraryModelsPayload>(
    `/api/car-library/models?brand=${encodeURIComponent(brand)}&type=${encodeURIComponent(type)}`,
  );
}
