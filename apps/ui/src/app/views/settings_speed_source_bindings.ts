import type { UiSettingsDom } from "../dom/settings_dom";
import type { UiShellDom } from "../dom/shell_dom";
import { closestFromTarget } from "./dom_helpers";
import { bindViewEvent, composeViewDisposers, type ViewDisposer } from "./dom_event_bindings";

const TAB_NAVIGATION_KEYS = new Set(["Enter", " ", "ArrowRight", "ArrowLeft", "Home", "End"]);

export type SettingsSpeedSourceInteraction =
  | { type: "speed-source-changed" }
  | { type: "manual-speed-input" }
  | { type: "stale-timeout-input" }
  | { type: "save" }
  | { type: "scan-obd-devices" }
  | { type: "navigate-context" }
  | { type: "pair-obd-device"; macAddress: string };

export interface SettingsObdDeviceListAction {
  type: "pair-obd-device";
  macAddress: string;
}

export interface SettingsSpeedSourceBindingHandlers {
  onAction(action: SettingsSpeedSourceInteraction): void;
}

export function getSettingsObdDeviceListAction(
  target: EventTarget | null,
): SettingsObdDeviceListAction | null {
  const button = closestFromTarget<HTMLButtonElement>(target, "[data-obd-pair-mac]");
  const macAddress = button?.dataset.obdPairMac ?? button?.getAttribute("data-obd-pair-mac");
  if (!macAddress) {
    return null;
  }
  return {
    type: "pair-obd-device",
    macAddress,
  };
}

export function bindSettingsSpeedSourceInteractions(
  dom: Pick<
    UiSettingsDom,
    | "speedSourceRadios"
    | "manualSpeedInput"
    | "staleTimeoutInput"
    | "saveSpeedSourceBtn"
    | "scanObdDevicesBtn"
    | "settingsTabs"
    | "obdDeviceList"
  >,
  shellDom: Pick<UiShellDom, "menuButtons">,
  handlers: SettingsSpeedSourceBindingHandlers,
): ViewDisposer {
  const navigationTargets = [...dom.settingsTabs, ...shellDom.menuButtons];

  return composeViewDisposers(
    ...dom.speedSourceRadios.map((radio) =>
      bindViewEvent(radio, "change", () => {
        handlers.onAction({ type: "speed-source-changed" });
      })),
    bindViewEvent(dom.manualSpeedInput, "input", () => {
      handlers.onAction({ type: "manual-speed-input" });
    }),
    bindViewEvent(dom.staleTimeoutInput, "input", () => {
      handlers.onAction({ type: "stale-timeout-input" });
    }),
    bindViewEvent(dom.saveSpeedSourceBtn, "click", () => {
      handlers.onAction({ type: "save" });
    }),
    bindViewEvent(dom.scanObdDevicesBtn, "click", () => {
      handlers.onAction({ type: "scan-obd-devices" });
    }),
    ...navigationTargets.flatMap((target) => [
      bindViewEvent(target, "click", () => {
        handlers.onAction({ type: "navigate-context" });
      }),
      bindViewEvent(target, "keydown", (event: KeyboardEvent) => {
        if (TAB_NAVIGATION_KEYS.has(event.key)) {
          handlers.onAction({ type: "navigate-context" });
        }
      }),
    ]),
    bindViewEvent(dom.obdDeviceList, "click", (event: MouseEvent) => {
      const action = getSettingsObdDeviceListAction(event.target);
      if (action) {
        handlers.onAction(action);
      }
    }),
  );
}
