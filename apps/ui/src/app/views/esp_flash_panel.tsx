import { render } from "preact";
import { useRef } from "preact/hooks";

import { useUiText } from "../ui_i18n";
import {
  computed,
  signal,
  useComputed,
  useSignalEffect,
  type ReadonlySignal,
} from "../ui_signals";
import type { VisualVariant } from "../view_style_types";
import {
  MaintenanceReadinessPanel,
  type MaintenanceReadinessPanelModel,
} from "./maintenance_readiness_view";

export interface EspFlashStatusBadgeModel {
  text: string;
  variant: VisualVariant;
}

export interface EspFlashStatusGridRowModel {
  labelText: string;
  valueText: string;
}

export interface EspFlashPortOptionModel {
  labelText: string;
  value: string;
}

export type EspFlashJourneyStageState =
  | "active"
  | "attention"
  | "done"
  | "upcoming";

export interface EspFlashJourneyStageModel {
  current: boolean;
  detailText: string;
  markerText: string;
  phase: string;
  state: EspFlashJourneyStageState;
  stateText: string;
  titleText: string;
}

export interface EspFlashJourneyPanelModel {
  stages: readonly EspFlashJourneyStageModel[];
  terminalNoteText: string | null;
}

export interface EspFlashEmptyStateModel {
  bodyText: string;
  titleText: string;
}

export interface EspFlashHistoryAttemptModel {
  badge: EspFlashStatusBadgeModel;
  errorText: string | null;
  metaText: string;
  portText: string;
}

export interface EspFlashHistoryPanelModel {
  attempts: readonly EspFlashHistoryAttemptModel[];
  emptyState: EspFlashEmptyStateModel | null;
}

export interface EspFlashLogPanelModel {
  emptyState: EspFlashEmptyStateModel | null;
  text: string;
}

export interface EspFlashReadinessPanelModel {
  errorText: string | null;
  rows: readonly EspFlashStatusGridRowModel[];
  summaryText: string;
}

export interface EspFlashPanelDom {
  espFlashPortSelect: HTMLSelectElement | null;
  espFlashRefreshPortsBtn: HTMLButtonElement | null;
  espFlashStartBtn: HTMLButtonElement;
  espFlashCancelBtn: HTMLButtonElement | null;
  espFlashStartSummary: HTMLElement | null;
  espFlashStatusBanner: HTMLElement | null;
  espFlashReadinessPanel: HTMLElement | null;
  espFlashJourneyPanel: HTMLElement | null;
  espFlashLogPanel: HTMLElement | null;
  espFlashHistoryPanel: HTMLElement | null;
}

export interface EspFlashPanelRenderModel {
  cancelButtonDisabled: boolean;
  cancelButtonHidden: boolean;
  history: EspFlashHistoryPanelModel;
  journey: EspFlashJourneyPanelModel;
  log: EspFlashLogPanelModel;
  portOptions: readonly EspFlashPortOptionModel[];
  portSelectDisabled: boolean;
  readiness: EspFlashReadinessPanelModel;
  refreshPortsDisabled: boolean;
  selectedPortValue: string;
  startButtonDisabled: boolean;
  startButtonHidden: boolean;
  startButtonLabelText: string;
  startSummary: MaintenanceReadinessPanelModel;
  statusBanner: EspFlashStatusBadgeModel;
}

export interface EspFlashPanelActionHandlers {
  onCancel(): void;
  onRefreshPorts(): void;
  onSelectPort(value: string): void;
  onStart(): void;
}

export interface EspFlashPanelView {
  bindActions(handlers: EspFlashPanelActionHandlers): void;
  bindModel(model: ReadonlySignal<EspFlashPanelRenderModel>): void;
}

const DEFAULT_ESP_FLASH_PANEL_MODEL: EspFlashPanelRenderModel = {
  cancelButtonDisabled: true,
  cancelButtonHidden: true,
  history: {
    attempts: [],
    emptyState: null,
  },
  journey: {
    stages: [],
    terminalNoteText: null,
  },
  log: {
    emptyState: null,
    text: "",
  },
  portOptions: [
    {
      labelText: "Auto-detect",
      value: "__auto__",
    },
  ],
  portSelectDisabled: false,
  readiness: {
    errorText: null,
    rows: [],
    summaryText: "",
  },
  refreshPortsDisabled: false,
  selectedPortValue: "__auto__",
  startButtonDisabled: true,
  startButtonHidden: false,
  startButtonLabelText: "Flash latest",
  startSummary: {
    items: [],
    stateLabel: "",
    stateVariant: "muted",
    summary: "",
    title: "",
  },
  statusBanner: {
    text: "Idle",
    variant: "muted",
  },
};

function StatusBadge(props: {
  badge: EspFlashStatusBadgeModel;
}) {
  const { badge } = props;
  return (
    <span class="pill" data-variant={badge.variant}>
      {badge.text}
    </span>
  );
}

function StatusGrid(props: {
  rows: readonly EspFlashStatusGridRowModel[];
}) {
  const { rows } = props;
  return (
    <div class="status-grid">
      {rows.map((row) => (
        <div class="status-grid__row" key={`${row.labelText}:${row.valueText}`}>
          <span class="status-grid__label">{row.labelText}</span>
          <span>{row.valueText}</span>
        </div>
      ))}
    </div>
  );
}

function MaintenanceNote(props: {
  text: string;
  variant?: "bad";
}) {
  const className = props.variant
    ? `maintenance-note maintenance-note--${props.variant}`
    : "maintenance-note";
  return <div class={className}>{props.text}</div>;
}

function InlineEmptyState(props: {
  model: EspFlashEmptyStateModel;
}) {
  const { model } = props;
  return (
    <div class="empty-state empty-state--inline">
      <strong class="empty-state__title">{model.titleText}</strong>
      <span class="empty-state__body">{model.bodyText}</span>
    </div>
  );
}

function EspFlashReadinessSection(props: {
  model: EspFlashReadinessPanelModel;
}) {
  const { model } = props;
  return (
    <div class="maintenance-stack maintenance-stack--tight">
      <div class="subtle">{model.summaryText}</div>
      {model.rows.length > 0 ? <StatusGrid rows={model.rows} /> : null}
      {model.errorText ? (
        <MaintenanceNote text={model.errorText} variant="bad" />
      ) : null}
    </div>
  );
}

function JourneyStageItem(props: {
  stage: EspFlashJourneyStageModel;
}) {
  const { stage } = props;
  return (
    <li
      class="maintenance-stage"
      data-stage-phase={stage.phase}
      data-stage-state={stage.state}
      aria-current={stage.current ? "step" : undefined}
    >
      <span class="maintenance-stage__marker">{stage.markerText}</span>
      <div class="maintenance-stage__body">
        <div class="maintenance-stage__title">{stage.titleText}</div>
        <div class="maintenance-stage__detail">{stage.detailText}</div>
      </div>
      <span class="maintenance-stage__state">{stage.stateText}</span>
    </li>
  );
}

function EspFlashJourneySection(props: {
  model: EspFlashJourneyPanelModel;
}) {
  const { model } = props;
  return (
    <div class="maintenance-journey">
      {model.terminalNoteText ? (
        <MaintenanceNote text={model.terminalNoteText} variant="bad" />
      ) : null}
      <ol class="maintenance-stage-list">
        {model.stages.map((stage) => (
          <JourneyStageItem key={stage.phase} stage={stage} />
        ))}
      </ol>
    </div>
  );
}

function EspFlashLogContent(props: {
  model: EspFlashLogPanelModel;
}) {
  const { model } = props;
  if (model.emptyState) {
    return <InlineEmptyState model={model.emptyState} />;
  }
  return <pre class="log-pre">{model.text}</pre>;
}

function EspFlashHistoryContent(props: {
  model: EspFlashHistoryPanelModel;
}) {
  const { model } = props;
  if (model.emptyState) {
    return <InlineEmptyState model={model.emptyState} />;
  }
  return (
    <ul class="maintenance-attempt-list">
      {model.attempts.map((attempt, index) => (
        <li class="maintenance-attempt" key={`${attempt.portText}:${index}`}>
          <div class="maintenance-attempt__header">
            <StatusBadge badge={attempt.badge} />
            <strong>{attempt.portText}</strong>
          </div>
          <div class="maintenance-attempt__meta subtle">{attempt.metaText}</div>
          {attempt.errorText ? (
            <MaintenanceNote text={attempt.errorText} variant="bad" />
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function EspFlashPanel(props: {
  actions: ReadonlySignal<EspFlashPanelActionHandlers | null>;
  model: ReadonlySignal<EspFlashPanelRenderModel>;
}) {
  const titleText = useUiText("settings.esp_flash.title", "ESP Flash");
  const hintText = useUiText("settings.esp_flash.hint", "Flash ESP firmware from local source on this Pi.");
  const portLabel = useUiText("settings.esp_flash.port", "Serial Port");
  const refreshLabel = useUiText("settings.esp_flash.refresh_ports", "Refresh");
  const detailsTitle = useUiText("settings.esp_flash.details_title", "What happens next");
  const detailsCaption = useUiText(
    "settings.esp_flash.details_caption",
    "Build, erase, and write the current firmware over USB.",
  );
  const preflightNote = useUiText(
    "settings.esp_flash.preflight_note",
    "Starting a flash builds the latest firmware on this Pi, erases the selected board, and writes the new image over USB. Keep the board powered until the staged progress reaches Done.",
  );
  const cancelLabel = useUiText("settings.esp_flash.cancel", "Cancel");
  const journeyTitle = useUiText("settings.esp_flash.journey_title", "Expected stages");
  const logsTitle = useUiText("settings.esp_flash.logs_title", "Live flash output");
  const logsIntro = useUiText(
    "settings.esp_flash.logs_intro",
    "Build, erase, and upload output appears here while the toolchain runs.",
  );
  const historyTitle = useUiText("settings.esp_flash.history", "Recent attempts");
  const historyIntro = useUiText(
    "settings.esp_flash.history_intro",
    "Recent flashes stay here so the next operator can see what happened last.",
  );
  const actions = useComputed(() => props.actions.value);
  const model = useComputed(() => props.model.value);
  const logPanelRef = useRef<HTMLDivElement | null>(null);
  const handleSelectPort = (value: string) => {
    actions.value?.onSelectPort(value);
  };
  const handleRefreshPorts = () => {
    actions.value?.onRefreshPorts();
  };
  const handleStart = () => {
    actions.value?.onStart();
  };
  const handleCancel = () => {
    actions.value?.onCancel();
  };

  useSignalEffect(() => {
    const logPanel = logPanelRef.current;
    const log = model.value.log;
    if (!logPanel || log.emptyState !== null) {
      return;
    }
    logPanel.scrollTop = logPanel.scrollHeight;
  });

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
              <span
                id="espFlashStatusBanner"
                class="pill"
                data-variant={model.value.statusBanner.variant}
              >
                {model.value.statusBanner.text}
              </span>
            </div>
            <div class="maintenance-card__body maintenance-card__body--hero">
              <div class="manual-speed-row">
                <label
                  htmlFor="espFlashPortSelect"

                >
                  {portLabel}
                </label>
                <select
                  id="espFlashPortSelect"
                  disabled={model.value.portSelectDisabled}
                  value={model.value.selectedPortValue}
                  onChange={(event) => handleSelectPort(event.currentTarget.value)}
                >
                  {model.value.portOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.labelText}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  id="espFlashRefreshPortsBtn"
                  class="btn btn--muted"
                  disabled={model.value.refreshPortsDisabled}
                  onClick={handleRefreshPorts}
                >
                  {refreshLabel}
                </button>
              </div>
              <div
                id="espFlashStartSummary"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              >
                <MaintenanceReadinessPanel model={model.value.startSummary} />
              </div>
              <div
                id="espFlashReadinessPanel"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              >
                <EspFlashReadinessSection model={model.value.readiness} />
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
                  <div
                    class="maintenance-note"

                  >
                    {preflightNote}
                  </div>
                </div>
              </details>
              <div class="maintenance-action-row">
                <button
                  type="button"
                  id="espFlashStartBtn"
                  class="btn btn--success"
                  hidden={model.value.startButtonHidden}
                  disabled={model.value.startButtonDisabled}
                  onClick={handleStart}
                >
                  {model.value.startButtonLabelText}
                </button>
                <button
                  type="button"
                  id="espFlashCancelBtn"
                  class="btn btn--danger"
                  hidden={model.value.cancelButtonHidden}
                  disabled={model.value.cancelButtonDisabled}
                  onClick={handleCancel}
                >
                  {cancelLabel}
                </button>
              </div>
            </div>
          </section>

          <div class="maintenance-pair-grid maintenance-pair-grid--focus">
            <section class="maintenance-card">
              <div class="maintenance-card__header">
                <div>
                  <div
                    class="maintenance-card__title"

                  >
                    {journeyTitle}
                  </div>
                </div>
              </div>
              <div
                id="espFlashJourneyPanel"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              >
                <EspFlashJourneySection model={model.value.journey} />
              </div>
            </section>
            <section class="maintenance-card">
              <div class="maintenance-card__header">
                <div>
                  <div
                    class="maintenance-card__title"

                  >
                    {logsTitle}
                  </div>
                  <div
                    class="subtle"

                  >
                    {logsIntro}
                  </div>
                </div>
              </div>
              <div
                id="espFlashLogPanel"
                ref={logPanelRef}
                class={
                  model.value.log.emptyState
                    ? "maintenance-log-slot"
                    : "maintenance-log-slot maintenance-log-panel"
                }
                aria-live="polite"
              >
                <EspFlashLogContent model={model.value.log} />
              </div>
            </section>
          </div>

          <section class="maintenance-card">
            <div class="maintenance-card__header">
              <div>
                <div
                  class="maintenance-card__title"
                >
                  {historyTitle}
                </div>
                <div
                  class="subtle"
                >
                  {historyIntro}
                </div>
              </div>
            </div>
            <div
              id="espFlashHistoryPanel"
              class="maintenance-stack maintenance-stack--tight"
            >
              <EspFlashHistoryContent model={model.value.history} />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

export function mountEspFlashPanel(host: HTMLElement): EspFlashPanelView {
  const actions = signal<EspFlashPanelActionHandlers | null>(null);
  const modelSource = signal<ReadonlySignal<EspFlashPanelRenderModel> | null>(null);
  const model = computed<EspFlashPanelRenderModel>(() => modelSource.value?.value ?? DEFAULT_ESP_FLASH_PANEL_MODEL);
  render(<EspFlashPanel actions={actions} model={model} />, host);

  return {
    bindActions(handlers) {
      actions.value = handlers;
    },
    bindModel(model) {
      modelSource.value = model;
    },
  };
}
