import type { SensorsPanelDom } from "./sensors_panel";
import {
  bindViewEvent,
  composeViewDisposers,
  type ViewDisposer,
} from "./dom_event_bindings";
import {
  getRealtimeSensorTableClickAction,
  getRealtimeSensorTableLocationChange,
  type RealtimeSensorTableClickAction,
  type RealtimeSensorTableLocationChange,
} from "./realtime_sensor_table_view";

export interface RealtimeFeatureBindingHandlers {
  onSensorLocationChange(change: RealtimeSensorTableLocationChange): void;
  onSensorTableAction(action: RealtimeSensorTableClickAction): void;
}

export function bindRealtimeFeatureInteractions(
  dom: SensorsPanelDom,
  handlers: RealtimeFeatureBindingHandlers,
): ViewDisposer {
  return composeViewDisposers(
    bindViewEvent(dom.sensorsSettingsBody, "change", (event: Event) => {
      const change = getRealtimeSensorTableLocationChange(event.target);
      if (change) {
        handlers.onSensorLocationChange(change);
      }
    }),
    bindViewEvent(dom.sensorsSettingsBody, "click", (event: MouseEvent) => {
      const action = getRealtimeSensorTableClickAction(event.target);
      if (action) {
        handlers.onSensorTableAction(action);
      }
    }),
  );
}
