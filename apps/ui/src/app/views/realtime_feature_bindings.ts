import type { UiRealtimeDom } from "../dom/realtime_dom";
import { getTypedInlineStateAction } from "./dom_helpers";
import { bindViewEvent, composeViewDisposers, type ViewDisposer } from "./dom_event_bindings";
import {
  REALTIME_LOGGING_SUMMARY_ACTIONS,
  type RealtimeLoggingSummaryAction,
} from "./realtime_logging_view_models";
import {
  getRealtimeSensorTableClickAction,
  getRealtimeSensorTableLocationChange,
  type RealtimeSensorTableClickAction,
  type RealtimeSensorTableLocationChange,
} from "./realtime_sensor_table_view";

export interface RealtimeFeatureBindingHandlers {
  onStartLogging(): void;
  onStopLogging(): void;
  onLoggingSummaryAction(action: RealtimeLoggingSummaryAction): void;
  onSensorLocationChange(change: RealtimeSensorTableLocationChange): void;
  onSensorTableAction(action: RealtimeSensorTableClickAction): void;
}

export function bindRealtimeFeatureInteractions(
  dom: Pick<UiRealtimeDom, "startLoggingBtn" | "stopLoggingBtn" | "loggingSummary" | "sensorsSettingsBody">,
  handlers: RealtimeFeatureBindingHandlers,
): ViewDisposer {
  return composeViewDisposers(
    bindViewEvent(dom.startLoggingBtn, "click", () => {
      handlers.onStartLogging();
    }),
    bindViewEvent(dom.stopLoggingBtn, "click", () => {
      handlers.onStopLogging();
    }),
    bindViewEvent(dom.loggingSummary, "click", (event: MouseEvent) => {
      const action = getTypedInlineStateAction(event.target, REALTIME_LOGGING_SUMMARY_ACTIONS);
      if (!action) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      handlers.onLoggingSummaryAction(action);
    }),
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
