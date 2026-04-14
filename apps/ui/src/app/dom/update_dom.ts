import { requiredById } from "./dom_query";

const UPDATE_OWNER = "Update feature";

export function getUiUpdatePanelHost(): HTMLElement {
  return requiredById("updatePanelRoot", UPDATE_OWNER);
}
