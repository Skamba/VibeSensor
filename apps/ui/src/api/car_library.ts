import { apiJson } from "./http";
import type * as Local from "../api/types";
import type * as Transport from "./types";

export async function getCarLibraryBrands(): Promise<Local.CarLibraryBrandsPayload> {
  return await apiJson<Transport.CarLibraryBrandsPayload>(
    "/api/car-library/brands",
  );
}

/** Every library model of the brand, each naming its body type. */
export async function getCarLibraryModels(
  brand: string,
): Promise<Local.CarLibraryModelsPayload> {
  return await apiJson<Transport.CarLibraryModelsPayload>(
    `/api/car-library/models?brand=${encodeURIComponent(brand)}`,
  );
}
