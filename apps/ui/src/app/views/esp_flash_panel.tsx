import { render } from "preact";
import { useRef } from "preact/hooks";

import { useUiText } from "../ui_i18n";
import {
  useComputed,
  useSignalEffect,
  useSignalProperties,
  type ReadonlySignal,
} from "../ui_signals";
import {
  MaintenanceReadinessPanel,
} from "./maintenance_readiness_view";
import { EspFlashHistoryContent } from "./esp_flash_history_section";
import { EspFlashJourneySection } from "./esp_flash_journey_section";
import { EspFlashLogContent } from "./esp_flash_log_section";
import {
  DEFAULT_ESP_FLASH_PANEL_MODEL,
  type EspFlashPanelActionHandlers,
  type EspFlashPanelRenderModel,
  type EspFlashPanelView,
  type EspFlashPortOptionModel,
  type EspFlashStatusBadgeModel,
} from "./esp_flash_panel_shared";
import { EspFlashReadinessSection } from "./esp_flash_readiness_section";
import { useDeferredModel } from "./view_model_binding";

export type {
  EspFlashEmptyStateModel,
  EspFlashHistoryAttemptModel,
  EspFlashHistoryPanelModel,
  EspFlashJourneyPanelModel,
  EspFlashJourneyStageModel,
  EspFlashJourneyStageState,
  EspFlashLogPanelModel,
  EspFlashPanelActionHandlers,
  EspFlashPanelRenderModel,
  EspFlashPanelView,
  EspFlashPortOptionModel,
  EspFlashReadinessPanelModel,
  EspFlashStatusBadgeModel,
  EspFlashStatusGridRowModel,
} from "./esp_flash_panel_shared";

const ESP_FLASH_PANEL_KEYS = [
  "cancelButtonDisabled",
  "cancelButtonHidden",
  "history",
  "journey",
  "log",
  "portOptions",
  "portSelectDisabled",
  "readiness",
  "refreshPortsDisabled",
  "selectedPortValue",
  "startButtonDisabled",
  "startButtonHidden",
  "startButtonLabelText",
  "startSummary",
  "statusBanner",
] as const;

const ESP_FLASH_STATUS_BANNER_KEYS = ["text", "variant"] as const;

function EspFlashStatusBanner(props: {
  badge: ReadonlySignal<EspFlashStatusBadgeModel>;
}) {
  const { text, variant } = useSignalProperties(
    props.badge,
    ESP_FLASH_STATUS_BANNER_KEYS,
  );
  return (
    <span id="espFlashStatusBanner" class="pill" data-variant={variant.value}>
      {text.value}
    </span>
  );
}

function EspFlashPortRow(props: {
  actions: ReadonlySignal<EspFlashPanelActionHandlers | null>;
  portLabel: ReadonlySignal<string>;
  portOptions: ReadonlySignal<readonly EspFlashPortOptionModel[]>;
  portSelectDisabled: ReadonlySignal<boolean>;
  refreshLabel: ReadonlySignal<string>;
  refreshPortsDisabled: ReadonlySignal<boolean>;
  selectedPortValue: ReadonlySignal<string>;
}) {
  const handleSelectPort = (value: string) => {
    props.actions.peek()?.onSelectPort(value);
  };
  const handleRefreshPorts = () => {
    props.actions.peek()?.onRefreshPorts();
  };
  return (
    <div class="manual-speed-row">
      <label htmlFor="espFlashPortSelect">
        {props.portLabel}
      </label>
      <select
        id="espFlashPortSelect"
        disabled={props.portSelectDisabled.value}
        value={props.selectedPortValue.value}
        onChange={(event) => handleSelectPort(event.currentTarget.value)}
      >
        {props.portOptions.value.map((option) => (
          <option key={option.value} value={option.value}>
            {option.labelText}
          </option>
        ))}
      </select>
      <button
        type="button"
        id="espFlashRefreshPortsBtn"
        class="btn btn--muted"
        disabled={props.refreshPortsDisabled.value}
        onClick={handleRefreshPorts}
      >
        {props.refreshLabel}
      </button>
    </div>
  );
}

function EspFlashStartSummarySection(props: {
  model: ReadonlySignal<EspFlashPanelRenderModel["startSummary"]>;
}) {
  return <MaintenanceReadinessPanel model={props.model.value} />;
}

function EspFlashActionRow(props: {
  actions: ReadonlySignal<EspFlashPanelActionHandlers | null>;
  cancelButtonDisabled: ReadonlySignal<boolean>;
  cancelButtonHidden: ReadonlySignal<boolean>;
  cancelLabel: ReadonlySignal<string>;
  startButtonDisabled: ReadonlySignal<boolean>;
  startButtonHidden: ReadonlySignal<boolean>;
  startButtonLabelText: ReadonlySignal<string>;
}) {
  const handleStart = () => {
    props.actions.peek()?.onStart();
  };
  const handleCancel = () => {
    props.actions.peek()?.onCancel();
  };
  return (
    <div class="maintenance-action-row">
      <button
        type="button"
        id="espFlashStartBtn"
        class="btn btn--success"
        hidden={props.startButtonHidden.value}
        disabled={props.startButtonDisabled.value}
        onClick={handleStart}
      >
        {props.startButtonLabelText.value}
      </button>
      <button
        type="button"
        id="espFlashCancelBtn"
        class="btn btn--danger"
        hidden={props.cancelButtonHidden.value}
        disabled={props.cancelButtonDisabled.value}
        onClick={handleCancel}
      >
        {props.cancelLabel}
      </button>
    </div>
  );
}

function EspFlashJourneyCard(props: {
  model: ReadonlySignal<EspFlashPanelRenderModel["journey"]>;
  titleText: ReadonlySignal<string>;
}) {
  return (
    <section class="maintenance-card">
      <div class="maintenance-card__header">
        <div>
          <div class="maintenance-card__title">
            {props.titleText}
          </div>
        </div>
      </div>
      <div
        id="espFlashJourneyPanel"
        class="maintenance-stack maintenance-stack--tight"
        aria-live="polite"
      >
        <EspFlashJourneySection model={props.model} />
      </div>
    </section>
  );
}

function EspFlashLogCard(props: {
  introText: ReadonlySignal<string>;
  model: ReadonlySignal<EspFlashPanelRenderModel["log"]>;
  titleText: ReadonlySignal<string>;
}) {
  const { emptyState, text } = useSignalProperties(props.model, ["emptyState", "text"] as const);
  const logPanelRef = useRef<HTMLDivElement | null>(null);

  useSignalEffect(() => {
    const logPanel = logPanelRef.current;
    if (!logPanel || emptyState.value !== null) {
      return;
    }
    text.value;
    const animationFrameId = globalThis.requestAnimationFrame(() => {
      logPanel.scrollTop = logPanel.scrollHeight;
    });
    return () => globalThis.cancelAnimationFrame(animationFrameId);
  });

  return (
    <section class="maintenance-card">
      <div class="maintenance-card__header">
        <div>
          <div class="maintenance-card__title">
            {props.titleText}
          </div>
          <div class="subtle">
            {props.introText}
          </div>
        </div>
      </div>
      <div
        ref={logPanelRef}
        id="espFlashLogPanel"
        class={
          emptyState.value
            ? "maintenance-log-slot"
            : "maintenance-log-slot maintenance-log-panel"
        }
        aria-live="polite"
      >
        <EspFlashLogContent model={props.model} />
      </div>
    </section>
  );
}

function EspFlashHistoryCard(props: {
  introText: ReadonlySignal<string>;
  model: ReadonlySignal<EspFlashPanelRenderModel["history"]>;
  titleText: ReadonlySignal<string>;
}) {
  return (
    <section class="maintenance-card">
      <div class="maintenance-card__header">
        <div>
          <div class="maintenance-card__title">
            {props.titleText}
          </div>
          <div class="subtle">
            {props.introText}
          </div>
        </div>
      </div>
      <div
        id="espFlashHistoryPanel"
        class="maintenance-stack maintenance-stack--tight"
      >
        <EspFlashHistoryContent model={props.model} />
      </div>
    </section>
  );
}

function EspFlashPanel(props: {
  actions: ReadonlySignal<EspFlashPanelActionHandlers | null>;
  model: ReadonlySignal<ReadonlySignal<EspFlashPanelRenderModel> | null>;
}) {
  const actions = useComputed(() => props.actions.value);
  const cancelLabel = useUiText("settings.esp_flash.cancel", "Cancel");
  const detailsCaption = useUiText(
    "settings.esp_flash.details_caption",
    "Build, erase, and write the current firmware over USB.",
  );
  const detailsTitle = useUiText("settings.esp_flash.details_title", "What happens next");
  const hintText = useUiText(
    "settings.esp_flash.hint",
    "Flash ESP firmware from local source on this Pi.",
  );
  const historyIntro = useUiText(
    "settings.esp_flash.history_intro",
    "Recent flashes stay here so the next operator can see what happened last.",
  );
  const historyTitle = useUiText("settings.esp_flash.history", "Recent attempts");
  const journeyTitle = useUiText("settings.esp_flash.journey_title", "Expected stages");
  const logsIntro = useUiText(
    "settings.esp_flash.logs_intro",
    "Build, erase, and upload output appears here while the toolchain runs.",
  );
  const logsTitle = useUiText("settings.esp_flash.logs_title", "Live flash output");
  const portLabel = useUiText("settings.esp_flash.port", "Serial Port");
  const preflightNote = useUiText(
    "settings.esp_flash.preflight_note",
    "Starting a flash builds the latest firmware on this Pi, erases the selected board, and writes the new image over USB. Keep the board powered until the staged progress reaches Done.",
  );
  const refreshLabel = useUiText("settings.esp_flash.refresh_ports", "Refresh");
  const titleText = useUiText("settings.esp_flash.title", "ESP Flash");
  const model = useDeferredModel(props.model, DEFAULT_ESP_FLASH_PANEL_MODEL);
  const {
    cancelButtonDisabled,
    cancelButtonHidden,
    history,
    journey,
    log,
    portOptions,
    portSelectDisabled,
    readiness,
    refreshPortsDisabled,
    selectedPortValue,
    startButtonDisabled,
    startButtonHidden,
    startButtonLabelText,
    startSummary,
    statusBanner,
  } = useSignalProperties(model, ESP_FLASH_PANEL_KEYS);
  return (
    <div class="panel card">
      <div class="maintenance-layout maintenance-layout--compact">
        <div class="maintenance-stack">
          <section class="maintenance-card maintenance-card--hero">
            <div class="maintenance-card__header">
              <div>
                <div
                  class="maintenance-card__title"
                >
                  {titleText}
                </div>
                <div
                  class="subtle"
                >
                  {hintText}
                </div>
              </div>
              <EspFlashStatusBanner badge={statusBanner} />
            </div>
            <div class="maintenance-card__body maintenance-card__body--hero">
              <EspFlashPortRow
                actions={actions}
                portLabel={portLabel}
                portOptions={portOptions}
                portSelectDisabled={portSelectDisabled}
                refreshLabel={refreshLabel}
                refreshPortsDisabled={refreshPortsDisabled}
                selectedPortValue={selectedPortValue}
              />
              <div
                id="espFlashStartSummary"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              >
                <EspFlashStartSummarySection model={startSummary} />
              </div>
              <div
                id="espFlashReadinessPanel"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              >
                <EspFlashReadinessSection model={readiness} />
              </div>
              <details class="settings-help-disclosure settings-help-disclosure--inline">
                <summary class="settings-help-disclosure__summary">
                  <span class="settings-help-disclosure__heading">
                    <span
                      class="settings-help-disclosure__title"
                    >
                        {detailsTitle}
                    </span>
                    <span
                      class="settings-help-disclosure__caption"
                    >
                        {detailsCaption}
                    </span>
                  </span>
                </summary>
                <div class="settings-help-disclosure__body">
                  <div class="maintenance-note">
                      {preflightNote}
                  </div>
                </div>
              </details>
              <EspFlashActionRow
                actions={actions}
                cancelButtonDisabled={cancelButtonDisabled}
                cancelButtonHidden={cancelButtonHidden}
                cancelLabel={cancelLabel}
                startButtonDisabled={startButtonDisabled}
                startButtonHidden={startButtonHidden}
                startButtonLabelText={startButtonLabelText}
              />
            </div>
          </section>

          <div class="maintenance-pair-grid maintenance-pair-grid--focus">
            <EspFlashJourneyCard model={journey} titleText={journeyTitle} />
            <EspFlashLogCard
              introText={logsIntro}
              model={log}
              titleText={logsTitle}
            />
          </div>

          <EspFlashHistoryCard
            introText={historyIntro}
            model={history}
            titleText={historyTitle}
          />
        </div>
      </div>
    </div>
  );
}

export function mountEspFlashPanel(host: HTMLElement, view: EspFlashPanelView): void {
  render(<EspFlashPanel actions={view.actions} model={view.model} />, host);
}
