import { useEffect, useRef } from "preact/hooks";

import { speedUnit } from "../../app_store";
import { FeedbackBlock, FeedbackSlot } from "../../components/feedback";
import { formatSpeed } from "../../format";
import { t } from "../../i18n";
import {
  obdStatus,
  speedSettings,
  speedSourceSnapshot,
  speedStatus,
} from "../../settings_store";
import {
  type DisplayedSpeedSourceMode,
  gpsReceiverMissing,
  resolveEffectiveSpeedSource,
} from "../../speed_source";
import {
  activeSourceLabel,
  activeSpeedKph,
  choiceState,
  configuredDeviceText,
  deviceActionLabel,
  deviceBadges,
  type DiagnosticRow,
  gpsDiagnostics,
  hasReadableName,
  obdDiagnostics,
} from "./speed_source_model";
import {
  chooseMode,
  diagnosticsOpen,
  draftPending,
  editManualSpeed,
  editStaleTimeout,
  focusRequest,
  manualSpeedFeedback,
  manualSpeedInput,
  obdSelectionError,
  pairDevice,
  pairingMac,
  savedMode,
  saveFeedback,
  saveSpeedSource,
  scanDevices,
  scanInFlight,
  scannedDevices,
  scanStatus,
  selectedMode,
  staleTimeoutFeedback,
  staleTimeoutInput,
} from "./speed_source_store";

const CHOICES: ReadonlyArray<{
  mode: DisplayedSpeedSourceMode;
  id: string;
  titleKey: string;
  captionKey: string;
}> = [
  {
    mode: "gps",
    id: "speedSourceChoiceGps",
    titleKey: "settings.speed.gps",
    captionKey: "settings.speed.gps_caption",
  },
  {
    mode: "obd2",
    id: "speedSourceChoiceObd",
    titleKey: "settings.speed.obd",
    captionKey: "settings.speed.obd_caption",
  },
  {
    mode: "manual",
    id: "speedSourceChoiceManual",
    titleKey: "settings.speed.manual",
    captionKey: "settings.speed.manual_caption",
  },
];

function Summary() {
  const snapshot = speedSourceSnapshot.value;
  const stats: Array<[string, string, string]> = [
    [
      "speedSourceCurrentSource",
      "settings.speed.current_source",
      activeSourceLabel(snapshot, t),
    ],
    [
      "speedSourceEffectiveSpeed",
      "settings.speed.effective_speed",
      formatSpeed(
        activeSpeedKph(snapshot, speedSettings.gpsEffectiveSpeedKph.value),
        speedUnit.value,
        t,
        1,
      ),
    ],
    [
      "speedSourceFallbackActive",
      "settings.speed.fallback_active",
      t(
        speedSettings.gpsFallbackActive.value
          ? "settings.speed.fallback_yes"
          : "settings.speed.fallback_no",
      ),
    ],
  ];
  return (
    <div class="speed-source-summary">
      <div class="speed-source-summary__eyebrow">
        {t("settings.speed.summary_title")}
      </div>
      <div class="subtle speed-source-summary__caption">
        {t("settings.speed.summary_caption")}
      </div>
      <div class="speed-source-summary__stats">
        {stats.map(([id, labelKey, value]) => (
          <div class="speed-source-summary__stat" key={id}>
            <div class="speed-source-summary__label">{t(labelKey)}</div>
            <div id={id} class="speed-source-summary__value">
              {value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Choices() {
  const selected = selectedMode.value;
  const saved = savedMode.value;
  const pending = draftPending.value;
  return (
    <div class="speed-source-choice-grid">
      {CHOICES.map((choice) => {
        const state = choiceState({
          active: saved === choice.mode,
          pending: pending && selected === choice.mode,
          error: choice.mode === "obd2" && obdSelectionError.value,
          t,
        });
        return (
          <label
            key={choice.mode}
            id={choice.id}
            class="speed-source-choice"
            data-speed-source-choice={choice.mode}
            data-selected={state.selected ? "true" : undefined}
            data-choice-state={state.state ?? undefined}
            data-choice-badge={state.badge ?? undefined}
          >
            <input
              class="speed-source-choice__radio"
              type="radio"
              name="speedSourceRadio"
              value={choice.mode}
              checked={selected === choice.mode}
              onChange={() => chooseMode(choice.mode)}
              aria-invalid={
                choice.mode === "obd2" && obdSelectionError.value
                  ? "true"
                  : undefined
              }
            />
            <span class="speed-source-choice__title">{t(choice.titleKey)}</span>
            <span class="speed-source-choice__caption">
              {t(choice.captionKey)}
            </span>
          </label>
        );
      })}
    </div>
  );
}

/** What each source needs and can test (docs/user_journeys.md §3.4). */
function Consequences() {
  return (
    <details
      id="speedSourceConsequences"
      class="settings-help-disclosure speed-source-consequences"
      open
    >
      <summary class="settings-help-disclosure__summary">
        <span class="settings-help-disclosure__heading">
          <span class="settings-help-disclosure__title">
            {t("settings.speed.compare.title")}
          </span>
        </span>
      </summary>
      <div class="settings-help-disclosure__body">
        {CHOICES.map((choice) => (
          <dl
            key={choice.mode}
            class="speed-source-consequence"
            data-speed-source-consequence={choice.mode}
          >
            <dt class="speed-source-consequence__source">
              {t(choice.titleKey)}
            </dt>
            {(["hardware", "enables", "limits"] as const).map((aspect) => (
              <dd key={aspect} class="speed-source-consequence__row">
                <span class="speed-source-consequence__label">
                  {t(`settings.speed.compare.${aspect}`)}
                </span>
                <span>
                  {t(`settings.speed.compare.${choice.mode}.${aspect}`)}
                </span>
              </dd>
            ))}
          </dl>
        ))}
      </div>
    </details>
  );
}

/** GPS is chosen, but no USB receiver is plugged in. */
function GpsReceiverHint() {
  if (
    selectedMode.value !== "gps" ||
    !gpsReceiverMissing("gps", speedStatus.value)
  ) {
    return null;
  }
  return (
    <div id="gpsReceiverMissing">
      <FeedbackBlock
        message={{
          title: t("speed.gps_no_receiver.title"),
          body: t("speed.gps_no_receiver.body"),
          tone: "error",
        }}
      />
    </div>
  );
}

function NumberField(props: {
  id: string;
  label: string;
  value: string;
  step: string;
  min: string;
  max?: string;
  feedbackId: string;
  feedback: typeof manualSpeedFeedback.value;
  inputRef: (element: HTMLInputElement | null) => void;
  onInput: (value: string) => void;
}) {
  return (
    <>
      <div class="manual-speed-row">
        <label htmlFor={props.id}>{props.label}</label>
        <input
          id={props.id}
          ref={props.inputRef}
          type="number"
          step={props.step}
          min={props.min}
          max={props.max}
          value={props.value}
          onInput={(event) => props.onInput(event.currentTarget.value)}
          aria-invalid={props.feedback ? "true" : undefined}
          aria-describedby={props.feedback ? props.feedbackId : undefined}
        />
      </div>
      <FeedbackSlot id={props.feedbackId} message={props.feedback} compact />
    </>
  );
}

function ObdConfig(props: {
  scanRef: (element: HTMLButtonElement | null) => void;
}) {
  const busy = scanInFlight.value || pairingMac.value !== null;
  const configuredMac = speedSettings.obdDeviceMac.value;
  return (
    <div
      id="obdSpeedConfig"
      class="speed-source-config"
      hidden={selectedMode.value !== "obd2"}
    >
      <div class="subtle">{t("settings.speed.obd_intro")}</div>
      <div class="speed-source-obd-toolbar">
        <div class="speed-source-obd-toolbar__summary">
          <div class="speed-source-summary__label">
            {t("settings.speed.obd_configured_device")}
          </div>
          <div id="obdConfiguredDevice" class="speed-source-summary__value">
            {configuredDeviceText(
              configuredMac,
              speedSettings.obdDeviceName.value,
              t,
            )}
          </div>
        </div>
        <button
          id="scanObdDevicesBtn"
          ref={props.scanRef}
          class="btn btn--secondary"
          type="button"
          disabled={busy}
          onClick={() => void scanDevices()}
        >
          {t("settings.speed.obd_scan")}
        </button>
      </div>
      <div id="obdDeviceScanStatus" class="subtle">
        {scanStatus.value ?? t("settings.speed.obd_scan_idle")}
      </div>
      <div id="obdDeviceList" class="speed-source-device-list">
        {scannedDevices.value.map((device) => (
          <div class="speed-source-device" key={device.mac_address}>
            <div class="speed-source-device__header">
              <div class="speed-source-device__identity">
                <div class="speed-source-device__name">
                  {device.name?.trim() || device.mac_address}
                </div>
                {hasReadableName(device) ? (
                  <div class="speed-source-device__mac">
                    {device.mac_address}
                  </div>
                ) : null}
              </div>
              <div class="speed-source-device__badges">
                {deviceBadges(device, configuredMac, t).map((badge) => (
                  <span
                    key={`${device.mac_address}-${badge.label}`}
                    class="speed-source-device__badge"
                    data-active={badge.active ? "true" : undefined}
                  >
                    {badge.label}
                  </span>
                ))}
              </div>
            </div>
            <div class="speed-source-device__actions">
              <button
                class="btn btn--secondary"
                type="button"
                disabled={busy}
                data-obd-pair-mac={device.mac_address}
                onClick={() => void pairDevice(device.mac_address)}
              >
                {deviceActionLabel(device, pairingMac.value, t)}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DiagnosticsTable(props: {
  id: string;
  rows: DiagnosticRow[];
  hidden?: boolean;
}) {
  return (
    <table class="kv-table" id={props.id} hidden={props.hidden}>
      <tbody>
        {props.rows.map((row) => (
          <tr key={row.id}>
            <td>{t(row.labelKey)}</td>
            <td id={row.id}>{row.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Diagnostics() {
  const snapshot = speedSourceSnapshot.value;
  const fallbackInUse =
    resolveEffectiveSpeedSource(snapshot) !== snapshot.speedSource;
  return (
    <details
      id="speedSourceDiagnostics"
      class="settings-help-disclosure speed-source-diagnostics"
      open={diagnosticsOpen.value || fallbackInUse}
      onToggle={(event) => {
        diagnosticsOpen.value = event.currentTarget.open;
      }}
    >
      <summary class="settings-help-disclosure__summary">
        <span class="settings-help-disclosure__heading">
          <span class="settings-help-disclosure__title">
            {t("settings.speed.status_title")}
          </span>
          <span class="settings-help-disclosure__caption">
            {t("settings.speed.status_caption")}
          </span>
        </span>
      </summary>
      <div class="settings-help-disclosure__body">
        <DiagnosticsTable
          id="gpsStatusPanel"
          rows={gpsDiagnostics(speedStatus.value, speedUnit.value, t)}
        />
        <DiagnosticsTable
          id="obdStatusPanel"
          rows={obdDiagnostics(obdStatus.value, t)}
          hidden={obdStatus.value === null}
        />
      </div>
    </details>
  );
}

export function SpeedSource() {
  const refs = useRef<{
    manual: HTMLInputElement | null;
    stale: HTMLInputElement | null;
    scan: HTMLButtonElement | null;
  }>({ manual: null, stale: null, scan: null });
  const focus = focusRequest.value;
  useEffect(() => {
    if (focus) {
      refs.current[focus.field]?.focus();
    }
  }, [focus]);
  const mode = selectedMode.value;
  return (
    <>
      <div class="panel card">
        <strong>{t("settings.speed.title")}</strong>
        <Summary />
        <Choices />
        <GpsReceiverHint />
        <div
          id="manualSpeedConfig"
          class="speed-source-config"
          hidden={mode !== "manual"}
        >
          <div class="subtle">{t("settings.speed.manual_intro")}</div>
          <NumberField
            id="manualSpeedInput"
            label={t("settings.speed.manual_label")}
            value={manualSpeedInput.value}
            step="0.1"
            min="0"
            feedbackId="manualSpeedFeedback"
            feedback={manualSpeedFeedback.value}
            inputRef={(element) => {
              refs.current.manual = element;
            }}
            onInput={editManualSpeed}
          />
        </div>
        <ObdConfig
          scanRef={(element) => {
            refs.current.scan = element;
          }}
        />
        <div
          id="gpsFallbackPanel"
          class="speed-source-config"
          hidden={mode === "manual"}
        >
          <div class="subtle">{t("settings.speed.gps_intro")}</div>
          <NumberField
            id="staleTimeoutInput"
            label={t("settings.speed.stale_timeout_label")}
            value={staleTimeoutInput.value}
            step="1"
            min="3"
            max="120"
            feedbackId="staleTimeoutFeedback"
            feedback={staleTimeoutFeedback.value}
            inputRef={(element) => {
              refs.current.stale = element;
            }}
            onInput={editStaleTimeout}
          />
        </div>
        <FeedbackSlot
          id="speedSourceSaveFeedback"
          message={saveFeedback.value}
        />
        <div class="settings-actions settings-actions--sticky">
          <button
            id="saveSpeedSourceBtn"
            class="btn btn--primary"
            type="button"
            onClick={() => void saveSpeedSource()}
          >
            {t("settings.speed.save")}
          </button>
        </div>
      </div>
      <Consequences />
      <Diagnostics />
    </>
  );
}
