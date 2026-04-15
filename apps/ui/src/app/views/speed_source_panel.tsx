import { h, render } from "preact";

import type { DisplayedSpeedSourceMode } from "../speed_source_state";
import type { ChoiceCardState } from "../view_style_types";
import { useUiTranslation } from "../ui_i18n";
import { signal, type ReadonlySignal } from "../ui_signals";
import {
  settingsFeedbackClassName,
  type SettingsFeedbackMessage,
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
  focusManualSpeedInput(): void;
  focusScanObdDevices(): void;
  focusStaleTimeoutInput(): void;
  isObdConfigVisible(): boolean;
  setModel(model: SpeedSourcePanelRenderModel): void;
  setDiagnostics(model: SpeedSourceDiagnosticsRenderModel): void;
}

type SpeedSourcePanelBridgeState = {
  actions: SpeedSourcePanelActionHandlers | null;
  diagnostics: SpeedSourceDiagnosticsRenderModel;
  diagnosticsDisclosureOpen: boolean;
  model: SpeedSourcePanelRenderModel;
};

const SPEED_SOURCE_CHOICES = [
  {
    captionKey: "settings.speed.gps_caption",
    captionText: "Use live GPS speed when it is healthy and available.",
    id: "speedSourceChoiceGps",
    mode: "gps",
    titleKey: "settings.speed.gps",
    titleText: "GPS",
  },
  {
    captionKey: "settings.speed.obd_caption",
    captionText:
      "Use a paired Bluetooth OBD adapter on the Pi for live vehicle speed and RPM.",
    id: "speedSourceChoiceObd",
    mode: "obd2",
    titleKey: "settings.speed.obd",
    titleText: "OBD-II",
  },
  {
    captionKey: "settings.speed.manual_caption",
    captionText: "Use a fixed speed when you need a deliberate override.",
    id: "speedSourceChoiceManual",
    mode: "manual",
    titleKey: "settings.speed.manual",
    titleText: "Manual",
  },
] as const satisfies readonly {
  captionKey: string;
  captionText: string;
  id: string;
  mode: DisplayedSpeedSourceMode;
  titleKey: string;
  titleText: string;
}[];

const GPS_STATUS_ROWS = [
  {
    fallbackLabel: "Connection",
    id: "gpsStatusState",
    labelKey: "settings.speed.connection_state",
    valueKey: "stateText",
  },
  {
    fallbackLabel: "Device",
    id: "gpsStatusDevice",
    labelKey: "settings.speed.device",
    valueKey: "deviceText",
  },
  {
    fallbackLabel: "Last update",
    id: "gpsStatusLastUpdate",
    labelKey: "settings.speed.last_update",
    valueKey: "lastUpdateText",
  },
  {
    fallbackLabel: "Raw speed",
    id: "gpsStatusRawSpeed",
    labelKey: "settings.speed.raw_speed",
    valueKey: "rawSpeedText",
  },
  {
    fallbackLabel: "Effective speed",
    id: "gpsStatusEffectiveSpeed",
    labelKey: "settings.speed.effective_speed",
    valueKey: "effectiveSpeedText",
  },
  {
    fallbackLabel: "Last error",
    id: "gpsStatusLastError",
    labelKey: "settings.speed.last_error",
    valueKey: "lastErrorText",
  },
  {
    fallbackLabel: "Reconnect in",
    id: "gpsStatusReconnect",
    labelKey: "settings.speed.reconnect_in",
    valueKey: "reconnectText",
  },
  {
    fallbackLabel: "Fallback active",
    id: "gpsStatusFallback",
    labelKey: "settings.speed.fallback_active",
    valueKey: "fallbackText",
  },
] as const satisfies readonly {
  fallbackLabel: string;
  id: string;
  labelKey: string;
  valueKey: keyof SpeedSourceGpsStatusRenderModel;
}[];

const OBD_STATUS_ROWS = [
  {
    fallbackLabel: "Configured adapter",
    id: "obdStatusConfiguredDevice",
    labelKey: "settings.speed.obd_configured_device",
    valueKey: "configuredDeviceText",
  },
  {
    fallbackLabel: "Paired",
    id: "obdStatusPairing",
    labelKey: "settings.speed.obd_paired",
    valueKey: "pairingText",
  },
  {
    fallbackLabel: "Trusted",
    id: "obdStatusTrusted",
    labelKey: "settings.speed.obd_trusted",
    valueKey: "trustedText",
  },
  {
    fallbackLabel: "Bluetooth connected",
    id: "obdStatusConnected",
    labelKey: "settings.speed.obd_connected",
    valueKey: "connectedText",
  },
  {
    fallbackLabel: "RFCOMM channel",
    id: "obdStatusRfcommChannel",
    labelKey: "settings.speed.obd_rfcomm_channel",
    valueKey: "rfcommChannelText",
  },
  {
    fallbackLabel: "Last RPM",
    id: "obdStatusLastRpm",
    labelKey: "settings.speed.obd_last_rpm",
    valueKey: "lastRpmText",
  },
  {
    fallbackLabel: "RPM age",
    id: "obdStatusRpmAge",
    labelKey: "settings.speed.obd_rpm_age",
    valueKey: "rpmAgeText",
  },
  {
    fallbackLabel: "Target cadence",
    id: "obdStatusTargetCadence",
    labelKey: "settings.speed.obd_target_cadence",
    valueKey: "targetCadenceText",
  },
  {
    fallbackLabel: "Effective cadence",
    id: "obdStatusEffectiveCadence",
    labelKey: "settings.speed.obd_effective_cadence",
    valueKey: "effectiveCadenceText",
  },
  {
    fallbackLabel: "Avg request RTT",
    id: "obdStatusRequestRtt",
    labelKey: "settings.speed.obd_request_rtt",
    valueKey: "requestRttText",
  },
  {
    fallbackLabel: "Timeouts",
    id: "obdStatusTimeouts",
    labelKey: "settings.speed.obd_timeouts",
    valueKey: "timeoutsText",
  },
  {
    fallbackLabel: "Errors",
    id: "obdStatusErrors",
    labelKey: "settings.speed.obd_errors",
    valueKey: "errorsText",
  },
  {
    fallbackLabel: "Monitor mode",
    id: "obdStatusMode",
    labelKey: "settings.speed.obd_mode",
    valueKey: "modeText",
  },
  {
    fallbackLabel: "Backoff active",
    id: "obdStatusBackoff",
    labelKey: "settings.speed.obd_backoff_active",
    valueKey: "backoffText",
  },
  {
    fallbackLabel: "Last raw response",
    id: "obdStatusRawResponse",
    labelKey: "settings.speed.obd_raw_response",
    valueKey: "rawResponseText",
  },
  {
    fallbackLabel: "Debug hint",
    id: "obdStatusDebugHint",
    labelKey: "settings.speed.obd_debug_hint",
    valueKey: "debugHintText",
  },
] as const satisfies readonly {
  fallbackLabel: string;
  id: string;
  labelKey: string;
  valueKey: Exclude<keyof SpeedSourceObdStatusRenderModel, "visible">;
}[];

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

const DEFAULT_SPEED_SOURCE_DIAGNOSTICS_MODEL: SpeedSourceDiagnosticsRenderModel = {
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

function SettingsFeedbackBlock(props: {
  message: SettingsFeedbackMessage;
}) {
  const { message } = props;
  return (
    <div
      class={settingsFeedbackClassName(message)}
      aria-live={message.tone === "error" ? "assertive" : "polite"}
    >
      {message.title ? (
        <strong class="settings-feedback__title">{message.title}</strong>
      ) : null}
      <span class="settings-feedback__body">{message.body}</span>
      {message.detail ? (
        <span class="settings-feedback__detail">{message.detail}</span>
      ) : null}
    </div>
  );
}

function SettingsFeedbackSlot(props: {
  className: string;
  id: string;
  message: SettingsFeedbackMessage | null;
}) {
  const { className, id, message } = props;
  return (
    <div id={id} class={className} hidden={message === null}>
      {message ? <SettingsFeedbackBlock message={message} /> : null}
    </div>
  );
}

function SpeedSourceChoiceCard(props: {
  choice: (typeof SPEED_SOURCE_CHOICES)[number];
  model: SpeedSourcePanelRenderModel;
  onSpeedSourceChanged: (mode: DisplayedSpeedSourceMode) => void;
}) {
  const { choice, model, onSpeedSourceChanged } = props;
  const choiceState = model.choiceCards[choice.mode];
  return (
    <label
      id={choice.id}
      class="speed-source-choice"
      data-speed-source-choice={choice.mode}
      data-selected={choiceState.selected ? "true" : undefined}
      data-choice-state={choiceState.state ?? undefined}
      data-choice-badge={choiceState.badgeText ?? undefined}
    >
      <input
        class="speed-source-choice__radio"
        type="radio"
        name="speedSourceRadio"
        value={choice.mode}
        checked={model.selectedMode === choice.mode}
        onChange={() => onSpeedSourceChanged(choice.mode)}
        aria-invalid={
          choice.mode === "obd2" && model.obdSelectionInvalid ? "true" : undefined
        }
      />
      <span class="speed-source-choice__title">
        {choice.titleText}
      </span>
      <span class="speed-source-choice__caption">
        {choice.captionText}
      </span>
    </label>
  );
}

function SpeedSourceObdDeviceRow(props: {
  device: SpeedSourceObdDeviceRenderModel;
  onPairObdDevice: (macAddress: string) => void;
}) {
  const { device, onPairObdDevice } = props;
  return (
    <div class="speed-source-device">
      <div class="speed-source-device__header">
        <div class="speed-source-device__identity">
          <div class="speed-source-device__name">{device.primaryText}</div>
          {device.secondaryText ? (
            <div class="speed-source-device__mac">{device.secondaryText}</div>
          ) : null}
        </div>
        <div class="speed-source-device__badges">
          {device.badges.map((badge) => (
            <span
              key={`${device.macAddress}-${badge.labelText}`}
              class="speed-source-device__badge"
              data-active={badge.active ? "true" : undefined}
            >
              {badge.labelText}
            </span>
          ))}
        </div>
      </div>
      <div class="speed-source-device__actions">
        <button
          class="btn btn--secondary"
          type="button"
          disabled={device.actionDisabled}
          data-obd-pair-mac={device.macAddress}
          onClick={() => onPairObdDevice(device.macAddress)}
        >
          {device.actionLabelText}
        </button>
      </div>
    </div>
  );
}

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
  const t = useUiTranslation();
  return (
    <>
      <div class="panel card">
        <strong>
          {t("settings.speed.title", "Speed Source")}
        </strong>
        <div class="speed-source-summary">
          <div
            class="speed-source-summary__eyebrow"

          >
            {t("settings.speed.summary_title", "Active right now")}
          </div>
          <div
            class="subtle speed-source-summary__caption"

          >
            {t(
              "settings.speed.summary_caption",
              "This source is currently driving the app. Changes below take effect after save.",
            )}
          </div>
          <div class="speed-source-summary__stats">
            <div class="speed-source-summary__stat">
              <div
                class="speed-source-summary__label"

              >
                {t("settings.speed.current_source", "Current source")}
              </div>
              <div
                id="speedSourceCurrentSource"
                class="speed-source-summary__value"
              >
                {state.model.summary.currentSourceText}
              </div>
            </div>
            <div class="speed-source-summary__stat">
              <div
                class="speed-source-summary__label"

              >
                {t("settings.speed.effective_speed", "Effective speed")}
              </div>
              <div
                id="speedSourceEffectiveSpeed"
                class="speed-source-summary__value"
              >
                {state.model.summary.effectiveSpeedText}
              </div>
            </div>
            <div class="speed-source-summary__stat">
              <div
                class="speed-source-summary__label"

              >
                {t("settings.speed.fallback_active", "Fallback active")}
              </div>
              <div
                id="speedSourceFallbackActive"
                class="speed-source-summary__value"
              >
                {state.model.summary.fallbackActiveText}
              </div>
            </div>
          </div>
        </div>
        <div class="speed-source-choice-grid">
          {SPEED_SOURCE_CHOICES.map((choice) => (
            <SpeedSourceChoiceCard
              key={choice.mode}
              choice={choice}
              model={state.model}
              onSpeedSourceChanged={(mode) => {
                state.actions?.onSpeedSourceChanged(mode);
              }}
            />
          ))}
        </div>
        <div
          id="manualSpeedConfig"
          class="speed-source-config"
          hidden={!state.model.manualConfigVisible}
        >
          <div class="subtle">
            {t(
              "settings.speed.manual_intro",
              "Set a fixed speed for manual mode and as the live-source fallback when GPS or OBD-II data goes stale.",
            )}
          </div>
          <div class="manual-speed-row">
            <label
              htmlFor="manualSpeedInput"

            >
              {t("settings.speed.manual_label", "Manual Speed (km/h)")}
            </label>
            <input
              id="manualSpeedInput"
              ref={manualInputRef}
              type="number"
              step="0.1"
              min="0"
              value={state.model.manualSpeedInputValue}
              onInput={(event) => {
                state.actions?.onManualSpeedInput(event.currentTarget.value);
              }}
              aria-invalid={
                state.model.manualSpeedFeedback ? "true" : undefined
              }
              aria-describedby={
                state.model.manualSpeedFeedback ? "manualSpeedFeedback" : undefined
              }
            />
          </div>
          <SettingsFeedbackSlot
            id="manualSpeedFeedback"
            className="settings-feedback-slot settings-feedback-slot--compact"
            message={state.model.manualSpeedFeedback}
          />
        </div>
        <div
          id="obdSpeedConfig"
          ref={obdConfigRef}
          class="speed-source-config"
          hidden={!state.model.obdConfigVisible}
        >
          <div class="subtle">
            {t(
              "settings.speed.obd_intro",
              "Pair a Bluetooth OBD adapter with the Pi, then save OBD-II as the selected live source.",
            )}
          </div>
          <div class="speed-source-obd-toolbar">
            <div class="speed-source-obd-toolbar__summary">
              <div
                class="speed-source-summary__label"

              >
                {t("settings.speed.obd_configured_device", "Configured adapter")}
              </div>
              <div id="obdConfiguredDevice" class="speed-source-summary__value">
                {state.model.obdConfiguredDeviceText}
              </div>
            </div>
            <button
              id="scanObdDevicesBtn"
              ref={scanButtonRef}
              class="btn btn--secondary"
              type="button"
              disabled={state.model.scanObdDevicesDisabled}

              onClick={() => {
                state.actions?.onScanObdDevices();
              }}
            >
              {t("settings.speed.obd_scan", "Scan for adapters")}
            </button>
          </div>
          <div id="obdDeviceScanStatus" class="subtle">
            {state.model.obdScanStatusText}
          </div>
          <div id="obdDeviceList" class="speed-source-device-list">
            {state.model.obdDevices.map((device) => (
              <SpeedSourceObdDeviceRow
                key={device.macAddress}
                device={device}
                onPairObdDevice={(macAddress) => {
                  state.actions?.onPairObdDevice(macAddress);
                }}
              />
            ))}
          </div>
        </div>
        <div
          id="gpsFallbackPanel"
          class="speed-source-config"
          hidden={!state.model.showGpsFallbackPanel}
        >
          <div class="subtle">
            {t(
              "settings.speed.gps_intro",
              "Choose how long stale live-source data can remain usable before the manual fallback takes over.",
            )}
          </div>
          <div class="manual-speed-row">
            <label
              htmlFor="staleTimeoutInput"

            >
              {t("settings.speed.stale_timeout_label", "Stale timeout (s)")}
            </label>
            <input
              id="staleTimeoutInput"
              ref={staleTimeoutInputRef}
              type="number"
              step="1"
              min="3"
              max="120"
              value={state.model.staleTimeoutInputValue}
              onInput={(event) => {
                state.actions?.onStaleTimeoutInput(event.currentTarget.value);
              }}
              aria-invalid={
                state.model.staleTimeoutFeedback ? "true" : undefined
              }
              aria-describedby={
                state.model.staleTimeoutFeedback
                  ? "staleTimeoutFeedback"
                  : undefined
              }
            />
          </div>
          <SettingsFeedbackSlot
            id="staleTimeoutFeedback"
            className="settings-feedback-slot settings-feedback-slot--compact"
            message={state.model.staleTimeoutFeedback}
          />
        </div>
        <SettingsFeedbackSlot
          id="speedSourceSaveFeedback"
          className="settings-feedback-slot"
          message={state.model.saveFeedback}
        />
        <div class="settings-actions settings-actions--sticky">
          <button
            id="saveSpeedSourceBtn"
            class="btn btn--primary"
            type="button"

            onClick={() => {
              state.actions?.onSave();
            }}
          >
            {t("settings.speed.save", "Save Speed Source")}
          </button>
        </div>
      </div>

      <details
        id="speedSourceDiagnostics"
        class="settings-help-disclosure speed-source-diagnostics"
        open={state.diagnosticsDisclosureOpen}
        onToggle={onDiagnosticsToggle}
      >
        <summary class="settings-help-disclosure__summary">
          <span class="settings-help-disclosure__heading">
            <span
              class="settings-help-disclosure__title"

            >
              {t("settings.speed.status_title", "Live source status")}
            </span>
            <span
              class="settings-help-disclosure__caption"

            >
              {t(
                "settings.speed.status_caption",
                "Connection, freshness, effective speed, fallback diagnostics, and Bluetooth OBD detail when configured.",
              )}
            </span>
          </span>
        </summary>
        <div class="settings-help-disclosure__body">
          <table class="kv-table" id="gpsStatusPanel">
            <tbody>
              {GPS_STATUS_ROWS.map((row) => (
                <tr key={row.id}>
                  <td>{t(row.labelKey, row.fallbackLabel)}</td>
                  <td id={row.id}>{state.diagnostics.gps[row.valueKey]}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table
            class="kv-table"
            id="obdStatusPanel"
            hidden={!state.diagnostics.obd.visible}
          >
            <tbody>
              {OBD_STATUS_ROWS.map((row) => (
                <tr key={row.id}>
                  <td>{t(row.labelKey, row.fallbackLabel)}</td>
                  <td id={row.id}>{state.diagnostics.obd[row.valueKey]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
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
    setModel(model): void {
      bridgeState.value = {
        ...bridgeState.value,
        diagnosticsDisclosureOpen:
          bridgeState.value.diagnosticsDisclosureOpen || model.diagnosticsShouldOpen,
        model,
      };
    },
    setDiagnostics(model): void {
      bridgeState.value = { ...bridgeState.value, diagnostics: model };
    },
  };
}
