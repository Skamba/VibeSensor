import type { DisplayedSpeedSourceMode } from "../speed_source_state";
import { getUiText as t } from "../ui_i18n";
import {
  settingsFeedbackClassName,
  type SettingsFeedbackMessage,
} from "./settings_feedback";
import type {
  SpeedSourceObdDeviceRenderModel,
  SpeedSourcePanelActionHandlers,
  SpeedSourcePanelRenderModel,
} from "./speed_source_panel";

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

function SpeedSourceSummarySection(props: {
  summary: SpeedSourcePanelRenderModel["summary"];
}) {
  const { summary } = props;
  return (
    <div class="speed-source-summary">
      <div class="speed-source-summary__eyebrow">
        {t("settings.speed.summary_title", "Active right now")}
      </div>
      <div class="subtle speed-source-summary__caption">
        {t(
          "settings.speed.summary_caption",
          "This source is currently driving the app. Changes below take effect after save.",
        )}
      </div>
      <div class="speed-source-summary__stats">
        <div class="speed-source-summary__stat">
          <div class="speed-source-summary__label">
            {t("settings.speed.current_source", "Current source")}
          </div>
          <div
            id="speedSourceCurrentSource"
            class="speed-source-summary__value"
          >
            {summary.currentSourceText}
          </div>
        </div>
        <div class="speed-source-summary__stat">
          <div class="speed-source-summary__label">
            {t("settings.speed.effective_speed", "Effective speed")}
          </div>
          <div
            id="speedSourceEffectiveSpeed"
            class="speed-source-summary__value"
          >
            {summary.effectiveSpeedText}
          </div>
        </div>
        <div class="speed-source-summary__stat">
          <div class="speed-source-summary__label">
            {t("settings.speed.fallback_active", "Fallback active")}
          </div>
          <div
            id="speedSourceFallbackActive"
            class="speed-source-summary__value"
          >
            {summary.fallbackActiveText}
          </div>
        </div>
      </div>
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

function SpeedSourceCardGroup(props: {
  actions: SpeedSourcePanelActionHandlers | null;
  model: SpeedSourcePanelRenderModel;
}) {
  const { actions, model } = props;
  return (
    <div class="speed-source-choice-grid">
      {SPEED_SOURCE_CHOICES.map((choice) => (
        <SpeedSourceChoiceCard
          key={choice.mode}
          choice={choice}
          model={model}
          onSpeedSourceChanged={(mode) => {
            actions?.onSpeedSourceChanged(mode);
          }}
        />
      ))}
    </div>
  );
}

function ManualSpeedSection(props: {
  actions: SpeedSourcePanelActionHandlers | null;
  manualInputRef: (element: HTMLInputElement | null) => void;
  model: SpeedSourcePanelRenderModel;
}) {
  const { actions, manualInputRef, model } = props;
  return (
    <div
      id="manualSpeedConfig"
      class="speed-source-config"
      hidden={!model.manualConfigVisible}
    >
      <div class="subtle">
        {t(
          "settings.speed.manual_intro",
          "Set a fixed speed for manual mode and as the live-source fallback when GPS or OBD-II data goes stale.",
        )}
      </div>
      <div class="manual-speed-row">
        <label htmlFor="manualSpeedInput">
          {t("settings.speed.manual_label", "Manual Speed (km/h)")}
        </label>
        <input
          id="manualSpeedInput"
          ref={manualInputRef}
          type="number"
          step="0.1"
          min="0"
          value={model.manualSpeedInputValue}
          onInput={(event) => {
            actions?.onManualSpeedInput(event.currentTarget.value);
          }}
          aria-invalid={
            model.manualSpeedFeedback ? "true" : undefined
          }
          aria-describedby={
            model.manualSpeedFeedback ? "manualSpeedFeedback" : undefined
          }
        />
      </div>
      <SettingsFeedbackSlot
        id="manualSpeedFeedback"
        className="settings-feedback-slot settings-feedback-slot--compact"
        message={model.manualSpeedFeedback}
      />
    </div>
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

function ObdConfigSection(props: {
  actions: SpeedSourcePanelActionHandlers | null;
  model: SpeedSourcePanelRenderModel;
  obdConfigRef: (element: HTMLElement | null) => void;
  scanButtonRef: (element: HTMLButtonElement | null) => void;
}) {
  const { actions, model, obdConfigRef, scanButtonRef } = props;
  return (
    <div
      id="obdSpeedConfig"
      ref={obdConfigRef}
      class="speed-source-config"
      hidden={!model.obdConfigVisible}
    >
      <div class="subtle">
        {t(
          "settings.speed.obd_intro",
          "Pair a Bluetooth OBD adapter with the Pi, then save OBD-II as the selected live source.",
        )}
      </div>
      <div class="speed-source-obd-toolbar">
        <div class="speed-source-obd-toolbar__summary">
          <div class="speed-source-summary__label">
            {t("settings.speed.obd_configured_device", "Configured adapter")}
          </div>
          <div id="obdConfiguredDevice" class="speed-source-summary__value">
            {model.obdConfiguredDeviceText}
          </div>
        </div>
        <button
          id="scanObdDevicesBtn"
          ref={scanButtonRef}
          class="btn btn--secondary"
          type="button"
          disabled={model.scanObdDevicesDisabled}
          onClick={() => {
            actions?.onScanObdDevices();
          }}
        >
          {t("settings.speed.obd_scan", "Scan for adapters")}
        </button>
      </div>
      <div id="obdDeviceScanStatus" class="subtle">
        {model.obdScanStatusText}
      </div>
      <div id="obdDeviceList" class="speed-source-device-list">
        {model.obdDevices.map((device) => (
          <SpeedSourceObdDeviceRow
            key={device.macAddress}
            device={device}
            onPairObdDevice={(macAddress) => {
              actions?.onPairObdDevice(macAddress);
            }}
          />
        ))}
      </div>
    </div>
  );
}

function GpsFallbackSection(props: {
  actions: SpeedSourcePanelActionHandlers | null;
  model: SpeedSourcePanelRenderModel;
  staleTimeoutInputRef: (element: HTMLInputElement | null) => void;
}) {
  const { actions, model, staleTimeoutInputRef } = props;
  return (
    <div
      id="gpsFallbackPanel"
      class="speed-source-config"
      hidden={!model.showGpsFallbackPanel}
    >
      <div class="subtle">
        {t(
          "settings.speed.gps_intro",
          "Choose how long stale live-source data can remain usable before the manual fallback takes over.",
        )}
      </div>
      <div class="manual-speed-row">
        <label htmlFor="staleTimeoutInput">
          {t("settings.speed.stale_timeout_label", "Stale timeout (s)")}
        </label>
        <input
          id="staleTimeoutInput"
          ref={staleTimeoutInputRef}
          type="number"
          step="1"
          min="3"
          max="120"
          value={model.staleTimeoutInputValue}
          onInput={(event) => {
            actions?.onStaleTimeoutInput(event.currentTarget.value);
          }}
          aria-invalid={
            model.staleTimeoutFeedback ? "true" : undefined
          }
          aria-describedby={
            model.staleTimeoutFeedback ? "staleTimeoutFeedback" : undefined
          }
        />
      </div>
      <SettingsFeedbackSlot
        id="staleTimeoutFeedback"
        className="settings-feedback-slot settings-feedback-slot--compact"
        message={model.staleTimeoutFeedback}
      />
    </div>
  );
}

function SpeedSourceSaveSection(props: {
  actions: SpeedSourcePanelActionHandlers | null;
  saveFeedback: SettingsFeedbackMessage | null;
}) {
  const { actions, saveFeedback } = props;
  return (
    <>
      <SettingsFeedbackSlot
        id="speedSourceSaveFeedback"
        className="settings-feedback-slot"
        message={saveFeedback}
      />
      <div class="settings-actions settings-actions--sticky">
        <button
          id="saveSpeedSourceBtn"
          class="btn btn--primary"
          type="button"
          onClick={() => {
            actions?.onSave();
          }}
        >
          {t("settings.speed.save", "Save Speed Source")}
        </button>
      </div>
    </>
  );
}

export function SpeedSourceConfigPanel(props: {
  actions: SpeedSourcePanelActionHandlers | null;
  manualInputRef: (element: HTMLInputElement | null) => void;
  model: SpeedSourcePanelRenderModel;
  obdConfigRef: (element: HTMLElement | null) => void;
  scanButtonRef: (element: HTMLButtonElement | null) => void;
  staleTimeoutInputRef: (element: HTMLInputElement | null) => void;
}) {
  const {
    actions,
    manualInputRef,
    model,
    obdConfigRef,
    scanButtonRef,
    staleTimeoutInputRef,
  } = props;
  return (
    <div class="panel card">
      <strong>
        {t("settings.speed.title", "Speed Source")}
      </strong>
      <SpeedSourceSummarySection summary={model.summary} />
      <SpeedSourceCardGroup actions={actions} model={model} />
      <ManualSpeedSection
        actions={actions}
        manualInputRef={manualInputRef}
        model={model}
      />
      <ObdConfigSection
        actions={actions}
        model={model}
        obdConfigRef={obdConfigRef}
        scanButtonRef={scanButtonRef}
      />
      <GpsFallbackSection
        actions={actions}
        model={model}
        staleTimeoutInputRef={staleTimeoutInputRef}
      />
      <SpeedSourceSaveSection
        actions={actions}
        saveFeedback={model.saveFeedback}
      />
    </div>
  );
}
