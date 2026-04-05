import { apiJson } from "./http";
import { fromTransportPayload } from "../transport/http_adapters";
import type * as Local from "../transport/http_models";
import type * as Transport from "./types";

export async function getCarLibraryBrands(): Promise<Local.CarLibraryBrandsPayload> {
  return fromTransportPayload<Transport.CarLibraryBrandsPayload, Local.CarLibraryBrandsPayload>(
    await apiJson<Transport.CarLibraryBrandsPayload>("/api/car-library/brands"),
  );
}

export async function getCarLibraryTypes(brand: string): Promise<Local.CarLibraryTypesPayload> {
  return fromTransportPayload<Transport.CarLibraryTypesPayload, Local.CarLibraryTypesPayload>(
    await apiJson<Transport.CarLibraryTypesPayload>(
      `/api/car-library/types?brand=${encodeURIComponent(brand)}`,
    ),
  );
}

export async function getCarLibraryModels(
  brand: string,
  type: string,
): Promise<Local.CarLibraryModelsPayload> {
  return fromTransportPayload<Transport.CarLibraryModelsPayload, Local.CarLibraryModelsPayload>(
    await apiJson<Transport.CarLibraryModelsPayload>(
      `/api/car-library/models?brand=${encodeURIComponent(brand)}&type=${encodeURIComponent(type)}`,
    ),
  );
}
