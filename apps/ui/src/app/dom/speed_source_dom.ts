import { requiredById } from "./dom_query";

const SPEED_SOURCE_OWNER = "Speed source feature";

export function getUiSpeedSourcePanelHost(): HTMLElement {
  return requiredById("speedSourcePanelRoot", SPEED_SOURCE_OWNER);
}
