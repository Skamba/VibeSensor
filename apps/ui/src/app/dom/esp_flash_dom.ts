import { requiredById } from "./dom_query";

const ESP_FLASH_OWNER = "ESP flash feature";

export function getUiEspFlashPanelHost(): HTMLElement {
  return requiredById("espFlashPanelRoot", ESP_FLASH_OWNER);
}
