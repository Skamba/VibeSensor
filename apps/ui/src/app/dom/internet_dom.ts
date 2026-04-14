import { requiredById } from "./dom_query";

const INTERNET_OWNER = "Internet settings";

export function getUiInternetPanelHost(): HTMLElement {
  return requiredById("internetPanelRoot", INTERNET_OWNER);
}
