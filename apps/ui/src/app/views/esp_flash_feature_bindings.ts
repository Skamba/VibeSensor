import type { UiEspFlashDom } from "../dom/esp_flash_dom";
import {
  bindViewEvent,
  composeViewDisposers,
  type ViewDisposer,
} from "./dom_event_bindings";

export type EspFlashFeatureBindingAction =
  | { type: "start" }
  | { type: "cancel" }
  | { type: "refresh-ports" }
  | { type: "select-port"; value: string };

export interface EspFlashFeatureBindingHandlers {
  onAction(action: EspFlashFeatureBindingAction): void;
}

export function bindEspFlashFeatureInteractions(
  dom: Pick<
    UiEspFlashDom,
    | "espFlashPortSelect"
    | "espFlashRefreshPortsBtn"
    | "espFlashStartBtn"
    | "espFlashCancelBtn"
  >,
  handlers: EspFlashFeatureBindingHandlers,
): ViewDisposer {
  return composeViewDisposers(
    bindViewEvent(dom.espFlashStartBtn, "click", () => {
      handlers.onAction({ type: "start" });
    }),
    bindViewEvent(dom.espFlashCancelBtn, "click", () => {
      handlers.onAction({ type: "cancel" });
    }),
    bindViewEvent(dom.espFlashRefreshPortsBtn, "click", () => {
      handlers.onAction({ type: "refresh-ports" });
    }),
    bindViewEvent(dom.espFlashPortSelect, "change", () => {
      handlers.onAction({
        type: "select-port",
        value: dom.espFlashPortSelect?.value || "__auto__",
      });
    }),
  );
}
