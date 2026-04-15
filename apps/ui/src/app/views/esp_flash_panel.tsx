import { h } from "preact";
import { useEffect, useRef } from "preact/hooks";

import { createUiPreactMount } from "../runtime/ui_preact_mount";
import { useUiTranslation } from "../ui_i18n";
import type { VisualVariant } from "../style_state";
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
  render(model: EspFlashPanelRenderModel): void;
}

type EspFlashPanelBridgeState = {
  actions: EspFlashPanelActionHandlers | null;
  model: EspFlashPanelRenderModel;
};

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
  state: EspFlashPanelBridgeState;
}) {
  const { state } = props;
  const { model } = state;
  const t = useUiTranslation();
  const logPanelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const logPanel = logPanelRef.current;
    if (!logPanel || model.log.emptyState !== null) {
      return;
    }
    logPanel.scrollTop = logPanel.scrollHeight;
  }, [model.log.emptyState, model.log.text]);

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
                  {t("settings.esp_flash.title", "ESP Flash")}
                </div>
                <div
                  class="subtle"

                >
                  {t(
                    "settings.esp_flash.hint",
                    "Flash ESP firmware from local source on this Pi.",
                  )}
                </div>
              </div>
              <span
                id="espFlashStatusBanner"
                class="pill"
                data-variant={model.statusBanner.variant}
              >
                {model.statusBanner.text}
              </span>
            </div>
            <div class="maintenance-card__body maintenance-card__body--hero">
              <div class="manual-speed-row">
                <label
                  htmlFor="espFlashPortSelect"

                >
                  {t("settings.esp_flash.port", "Serial Port")}
                </label>
                <select
                  id="espFlashPortSelect"
                  disabled={model.portSelectDisabled}
                  value={model.selectedPortValue}
                  onChange={(event) =>
                    state.actions?.onSelectPort(event.currentTarget.value)}
                >
                  {model.portOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.labelText}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  id="espFlashRefreshPortsBtn"
                  class="btn btn--muted"

                  disabled={model.refreshPortsDisabled}
                  onClick={() => state.actions?.onRefreshPorts()}
                >
                  {t("settings.esp_flash.refresh_ports", "Refresh")}
                </button>
              </div>
              <div
                id="espFlashStartSummary"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              >
                <MaintenanceReadinessPanel model={model.startSummary} />
              </div>
              <div
                id="espFlashReadinessPanel"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              >
                <EspFlashReadinessSection model={model.readiness} />
              </div>
              <details class="settings-help-disclosure settings-help-disclosure--inline">
                <summary class="settings-help-disclosure__summary">
                  <span class="settings-help-disclosure__heading">
                    <span
                      class="settings-help-disclosure__title"

                    >
                      {t("settings.esp_flash.details_title", "What happens next")}
                    </span>
                    <span
                      class="settings-help-disclosure__caption"

                    >
                      {t(
                        "settings.esp_flash.details_caption",
                        "Build, erase, and write the current firmware over USB.",
                      )}
                    </span>
                  </span>
                </summary>
                <div class="settings-help-disclosure__body">
                  <div
                    class="maintenance-note"

                  >
                    {t(
                      "settings.esp_flash.preflight_note",
                      "Starting a flash builds the latest firmware on this Pi, erases the selected board, and writes the new image over USB. Keep the board powered until the staged progress reaches Done.",
                    )}
                  </div>
                </div>
              </details>
              <div class="maintenance-action-row">
                <button
                  type="button"
                  id="espFlashStartBtn"
                  class="btn btn--success"
                  hidden={model.startButtonHidden}
                  disabled={model.startButtonDisabled}
                  onClick={() => state.actions?.onStart()}
                >
                  {model.startButtonLabelText}
                </button>
                <button
                  type="button"
                  id="espFlashCancelBtn"
                  class="btn btn--danger"

                  hidden={model.cancelButtonHidden}
                  disabled={model.cancelButtonDisabled}
                  onClick={() => state.actions?.onCancel()}
                >
                  {t("settings.esp_flash.cancel", "Cancel")}
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
                    {t("settings.esp_flash.journey_title", "Expected stages")}
                  </div>
                </div>
              </div>
              <div
                id="espFlashJourneyPanel"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              >
                <EspFlashJourneySection model={model.journey} />
              </div>
            </section>
            <section class="maintenance-card">
              <div class="maintenance-card__header">
                <div>
                  <div
                    class="maintenance-card__title"

                  >
                    {t("settings.esp_flash.logs_title", "Live flash output")}
                  </div>
                  <div
                    class="subtle"

                  >
                    {t(
                      "settings.esp_flash.logs_intro",
                      "Build, erase, and upload output appears here while the toolchain runs.",
                    )}
                  </div>
                </div>
              </div>
              <div
                id="espFlashLogPanel"
                ref={logPanelRef}
                class={
                  model.log.emptyState
                    ? "maintenance-log-slot"
                    : "maintenance-log-slot maintenance-log-panel"
                }
                aria-live="polite"
              >
                <EspFlashLogContent model={model.log} />
              </div>
            </section>
          </div>

          <section class="maintenance-card">
            <div class="maintenance-card__header">
              <div>
                <div
                  class="maintenance-card__title"

                  >
                    {t("settings.esp_flash.history", "Recent attempts")}
                  </div>
                <div
                  class="subtle"

                  >
                    {t(
                      "settings.esp_flash.history_intro",
                      "Recent flashes stay here so the next operator can see what happened last.",
                    )}
                  </div>
              </div>
            </div>
            <div
              id="espFlashHistoryPanel"
              class="maintenance-stack maintenance-stack--tight"
            >
              <EspFlashHistoryContent model={model.history} />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

export function mountEspFlashPanel(host: HTMLElement): EspFlashPanelView {
  let state: EspFlashPanelBridgeState = {
    actions: null,
    model: DEFAULT_ESP_FLASH_PANEL_MODEL,
  };
  const mount = createUiPreactMount(host);

  function render(): void {
    mount.render(<EspFlashPanel state={state} />);
  }

  render();

  return {
    bindActions(handlers) {
      state = { ...state, actions: handlers };
      render();
    },
    render(model) {
      state = { ...state, model };
      render();
    },
  };
}
