import { render } from "preact";

import type { DisplayedSpeedSourceMode } from "../speed_source_state";
import type { ChoiceCardState } from "../view_style_types";
import {
  effect,
  signal,
  untracked,
  type ReadonlySignal,
} from "../ui_signals";
import { SpeedSourceConfigPanel } from "./speed_source_config_panel";
import { SpeedSourceDiagnosticsPanel } from "./speed_source_diagnostics_panel";
import type {
  SettingsFeedbackMessage,
} from "./settings_feedback";

export interface SpeedSourceChoiceCardRenderModel {
  badgeText: string | null;
  selected: boolean;
  state: ChoiceCardState | null;
}

export interface SpeedSourceSummaryRenderModel {
  currentSourceText: string;
  effectiveSpeedText: string;
  fallbackActiveText: string;
}

export interface SpeedSourceObdDeviceBadgeRenderModel {
  active: boolean;
  labelText: string;
}

export interface SpeedSourceObdDeviceRenderModel {
  actionDisabled: boolean;
  actionLabelText: string;
  badges: readonly SpeedSourceObdDeviceBadgeRenderModel[];
  macAddress: string;
  primaryText: string;
  secondaryText: string | null;
}

export interface SpeedSourcePanelRenderModel {
  choiceCards: Record<DisplayedSpeedSourceMode, SpeedSourceChoiceCardRenderModel>;
  diagnosticsShouldOpen: boolean;
  manualConfigVisible: boolean;
  manualSpeedFeedback: SettingsFeedbackMessage | null;
  manualSpeedInputValue: string;
  obdConfigVisible: boolean;
  obdConfiguredDeviceText: string;
  obdDevices: readonly SpeedSourceObdDeviceRenderModel[];
  obdScanStatusText: string;
  obdSelectionInvalid: boolean;
  scanObdDevicesDisabled: boolean;
  saveFeedback: SettingsFeedbackMessage | null;
  selectedMode: DisplayedSpeedSourceMode;
  showGpsFallbackPanel: boolean;
  staleTimeoutFeedback: SettingsFeedbackMessage | null;
  staleTimeoutInputValue: string;
  summary: SpeedSourceSummaryRenderModel;
}

export interface SpeedSourceGpsStatusRenderModel {
  deviceText: string;
  effectiveSpeedText: string;
  fallbackText: string;
  lastErrorText: string;
  lastUpdateText: string;
  rawSpeedText: string;
  reconnectText: string;
  stateText: string;
}

export interface SpeedSourceObdStatusRenderModel {
  backoffText: string;
  configuredDeviceText: string;
  connectedText: string;
  debugHintText: string;
  effectiveCadenceText: string;
  errorsText: string;
  lastRpmText: string;
  modeText: string;
  pairingText: string;
  rawResponseText: string;
  requestRttText: string;
  rfcommChannelText: string;
  rpmAgeText: string;
  targetCadenceText: string;
  timeoutsText: string;
  trustedText: string;
  visible: boolean;
}

export interface SpeedSourceDiagnosticsRenderModel {
  gps: SpeedSourceGpsStatusRenderModel;
  obd: SpeedSourceObdStatusRenderModel;
}

export interface SpeedSourcePanelActionHandlers {
  onManualSpeedInput(value: string): void;
  onPairObdDevice(macAddress: string): void;
  onSave(): void;
  onScanObdDevices(): void;
  onSpeedSourceChanged(mode: DisplayedSpeedSourceMode): void;
  onStaleTimeoutInput(value: string): void;
}

export interface SpeedSourcePanelView {
  bindActions(handlers: SpeedSourcePanelActionHandlers): void;
  bindDiagnostics(model: ReadonlySignal<SpeedSourceDiagnosticsRenderModel>): void;
  bindModel(model: ReadonlySignal<SpeedSourcePanelRenderModel>): void;
  focusManualSpeedInput(): void;
  focusScanObdDevices(): void;
  focusStaleTimeoutInput(): void;
  isObdConfigVisible(): boolean;
}

type SpeedSourcePanelBridgeState = {
  actions: SpeedSourcePanelActionHandlers | null;
  diagnostics: SpeedSourceDiagnosticsRenderModel;
  diagnosticsDisclosureOpen: boolean;
  model: SpeedSourcePanelRenderModel;
};

const DEFAULT_SPEED_SOURCE_PANEL_MODEL: SpeedSourcePanelRenderModel = {
  choiceCards: {
    gps: { badgeText: null, selected: false, state: null },
    manual: { badgeText: null, selected: false, state: null },
    obd2: { badgeText: null, selected: false, state: null },
  },
  diagnosticsShouldOpen: false,
  manualConfigVisible: false,
  manualSpeedFeedback: null,
  manualSpeedInputValue: "",
  obdConfigVisible: false,
  obdConfiguredDeviceText: "--",
  obdDevices: [],
  obdScanStatusText: "Scan to discover nearby Bluetooth OBD adapters.",
  obdSelectionInvalid: false,
  scanObdDevicesDisabled: false,
  saveFeedback: null,
  selectedMode: "gps",
  showGpsFallbackPanel: false,
  staleTimeoutFeedback: null,
  staleTimeoutInputValue: "10",
  summary: {
    currentSourceText: "--",
    effectiveSpeedText: "--",
    fallbackActiveText: "--",
  },
};

export const DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL: SpeedSourceDiagnosticsRenderModel = {
  gps: {
    deviceText: "--",
    effectiveSpeedText: "--",
    fallbackText: "--",
    lastErrorText: "--",
    lastUpdateText: "--",
    rawSpeedText: "--",
    reconnectText: "--",
    stateText: "--",
  },
  obd: {
    backoffText: "--",
    configuredDeviceText: "--",
    connectedText: "--",
    debugHintText: "--",
    effectiveCadenceText: "--",
    errorsText: "--",
    lastRpmText: "--",
    modeText: "--",
    pairingText: "--",
    rawResponseText: "--",
    requestRttText: "--",
    rfcommChannelText: "--",
    rpmAgeText: "--",
    targetCadenceText: "--",
    timeoutsText: "--",
    trustedText: "--",
    visible: false,
  },
};

function SpeedSourcePanel(props: {
  manualInputRef: (element: HTMLInputElement | null) => void;
  obdConfigRef: (element: HTMLElement | null) => void;
  onDiagnosticsToggle: (event: Event) => void;
  scanButtonRef: (element: HTMLButtonElement | null) => void;
  staleTimeoutInputRef: (element: HTMLInputElement | null) => void;
  state: ReadonlySignal<SpeedSourcePanelBridgeState>;
}) {
  const {
    manualInputRef,
    obdConfigRef,
    onDiagnosticsToggle,
    scanButtonRef,
    staleTimeoutInputRef,
    state: bridgeState,
  } = props;
  const state = bridgeState.value;
  return (
    <>
      <SpeedSourceConfigPanel
        actions={state.actions}
        manualInputRef={manualInputRef}
        model={state.model}
        obdConfigRef={obdConfigRef}
        scanButtonRef={scanButtonRef}
        staleTimeoutInputRef={staleTimeoutInputRef}
      />
      <SpeedSourceDiagnosticsPanel
        diagnostics={state.diagnostics}
        diagnosticsDisclosureOpen={state.diagnosticsDisclosureOpen}
        onDiagnosticsToggle={onDiagnosticsToggle}
      />
    </>
  );
}

export function mountSpeedSourcePanel(host: HTMLElement): SpeedSourcePanelView {
  const bridgeState = signal<SpeedSourcePanelBridgeState>({
    actions: null,
    diagnostics: DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL,
    diagnosticsDisclosureOpen: false,
    model: DEFAULT_SPEED_SOURCE_PANEL_MODEL,
  });
  let manualSpeedInput: HTMLInputElement | null = null;
  let obdConfig: HTMLElement | null = null;
  let scanObdDevicesBtn: HTMLButtonElement | null = null;
  let staleTimeoutInput: HTMLInputElement | null = null;
  render(
    <SpeedSourcePanel
      manualInputRef={(element) => {
        manualSpeedInput = element;
      }}
      obdConfigRef={(element) => {
        obdConfig = element;
      }}
      onDiagnosticsToggle={(event) => {
        bridgeState.value = {
          ...bridgeState.value,
          diagnosticsDisclosureOpen:
            (event.currentTarget as HTMLDetailsElement | null)?.open ?? false,
        };
      }}
      scanButtonRef={(element) => {
        scanObdDevicesBtn = element;
      }}
      staleTimeoutInputRef={(element) => {
        staleTimeoutInput = element;
      }}
      state={bridgeState}
    />,
    host,
  );

  return {
    bindActions(handlers): void {
      bridgeState.value = { ...bridgeState.value, actions: handlers };
    },
    bindDiagnostics(model): void {
      effect(() => {
        const currentBridgeState = untracked(() => bridgeState.value);
        bridgeState.value = {
          ...currentBridgeState,
          diagnostics: model.value,
        };
      });
    },
    bindModel(model): void {
      effect(() => {
        const currentBridgeState = untracked(() => bridgeState.value);
        bridgeState.value = {
          ...currentBridgeState,
          diagnosticsDisclosureOpen:
            currentBridgeState.diagnosticsDisclosureOpen || model.value.diagnosticsShouldOpen,
          model: model.value,
        };
      });
    },
    focusManualSpeedInput(): void {
      manualSpeedInput?.focus();
    },
    focusScanObdDevices(): void {
      scanObdDevicesBtn?.focus();
    },
    focusStaleTimeoutInput(): void {
      staleTimeoutInput?.focus();
    },
    isObdConfigVisible(): boolean {
      if (!obdConfig || obdConfig.hidden) {
        return false;
      }
      const activePanel = obdConfig.closest<HTMLElement>(".settings-tab-panel");
      if (!activePanel || activePanel.hidden) {
        return false;
      }
      const activeView = activePanel.closest<HTMLElement>(".view");
      return activeView == null || !activeView.hidden;
    },
  };
}
