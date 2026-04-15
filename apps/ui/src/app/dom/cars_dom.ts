import { requiredById } from "./dom_query";

const CARS_OWNER = "Cars feature";

export function getUiCarsPanelHost(): HTMLElement {
  return requiredById<HTMLElement>("carsPanelRoot", CARS_OWNER);
}
