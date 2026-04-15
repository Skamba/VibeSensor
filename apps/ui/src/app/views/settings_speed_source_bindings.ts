import type { DisplayedSpeedSourceMode } from "../speed_source_state";
import type { UiShellChromeDom } from "../runtime/ui_shell_chrome";
import type { SettingsShellDom } from "./settings_shell";
import type { SettingsSpeedSourcePanelDom } from "./speed_source_panel";
import { closestFromTarget } from "./dom_helpers";
import {
  bindViewEvent,
  composeViewDisposers,
  type ViewDisposer,
} from "./dom_event_bindings";

const TAB_NAVIGATION_KEYS = new Set([
  "Enter",
  " ",
  "ArrowRight",
  "ArrowLeft",
  "Home",
  "End",
]);
const DISPLAYED_SPEED_SOURCE_MODES = [
  "gps",
  "manual",
  "obd2",
] as const satisfies readonly DisplayedSpeedSourceMode[];

export type SettingsSpeedSourceInteraction =
  | { type: "speed-source-changed"; mode: DisplayedSpeedSourceMode }
  | { type: "manual-speed-input"; value: string }
  | { type: "stale-timeout-input"; value: string }
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

function readDisplayedSpeedSourceMode(
  value: string,
): DisplayedSpeedSourceMode | null {
  return DISPLAYED_SPEED_SOURCE_MODES.find((mode) => mode === value) ?? null;
}

export function getSettingsObdDeviceListAction(
  target: EventTarget | null,
): SettingsObdDeviceListAction | null {
  const button = closestFromTarget<HTMLButtonElement>(
    target,
    "[data-obd-pair-mac]",
  );
  const macAddress =
    button?.dataset.obdPairMac ?? button?.getAttribute("data-obd-pair-mac");
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
    Pick<SettingsShellDom, "settingsTabs"> & SettingsSpeedSourcePanelDom,
    | "speedSourceRadios"
    | "manualSpeedInput"
    | "staleTimeoutInput"
    | "saveSpeedSourceBtn"
    | "scanObdDevicesBtn"
    | "settingsTabs"
    | "obdDeviceList"
  >,
  shellDom: Pick<UiShellChromeDom, "menuButtons">,
  handlers: SettingsSpeedSourceBindingHandlers,
): ViewDisposer {
  const navigationTargets = [...dom.settingsTabs, ...shellDom.menuButtons];

  return composeViewDisposers(
    ...dom.speedSourceRadios.map((radio) =>
      bindViewEvent(radio, "change", () => {
        const mode = readDisplayedSpeedSourceMode(radio.value);
        if (mode) {
          handlers.onAction({ type: "speed-source-changed", mode });
        }
      }),
    ),
    bindViewEvent(dom.manualSpeedInput, "input", () => {
      handlers.onAction({
        type: "manual-speed-input",
        value: dom.manualSpeedInput?.value ?? "",
      });
    }),
    bindViewEvent(dom.staleTimeoutInput, "input", () => {
      handlers.onAction({
        type: "stale-timeout-input",
        value: dom.staleTimeoutInput?.value ?? "",
      });
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
