import { requiredById } from "./dom_query";

const SENSORS_OWNER = "Sensors feature";

export function getUiSensorsPanelHost(): HTMLElement {
  return requiredById("sensorsPanelRoot", SENSORS_OWNER);
}
