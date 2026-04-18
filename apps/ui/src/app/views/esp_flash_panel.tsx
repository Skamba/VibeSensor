import { render } from "preact";
import { useRef } from "preact/hooks";

import { getUiText } from "../ui_i18n";
import {
  useComputed,
  useSignalEffect,
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
} from "./esp_flash_panel_shared";
import { EspFlashReadinessSection } from "./esp_flash_readiness_section";

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

function EspFlashPanel(props: {
  actions: ReadonlySignal<EspFlashPanelActionHandlers | null>;
  model: ReadonlySignal<ReadonlySignal<EspFlashPanelRenderModel> | null>;
}) {
  const actions = useComputed(() => props.actions.value);
  const labels = useComputed(() => ({
    cancelLabel: getUiText("settings.esp_flash.cancel", "Cancel"),
    detailsCaption: getUiText(
      "settings.esp_flash.details_caption",
      "Build, erase, and write the current firmware over USB.",
    ),
    detailsTitle: getUiText("settings.esp_flash.details_title", "What happens next"),
    hintText: getUiText(
      "settings.esp_flash.hint",
      "Flash ESP firmware from local source on this Pi.",
    ),
    historyIntro: getUiText(
      "settings.esp_flash.history_intro",
      "Recent flashes stay here so the next operator can see what happened last.",
    ),
    historyTitle: getUiText("settings.esp_flash.history", "Recent attempts"),
    journeyTitle: getUiText("settings.esp_flash.journey_title", "Expected stages"),
    logsIntro: getUiText(
      "settings.esp_flash.logs_intro",
      "Build, erase, and upload output appears here while the toolchain runs.",
    ),
    logsTitle: getUiText("settings.esp_flash.logs_title", "Live flash output"),
    portLabel: getUiText("settings.esp_flash.port", "Serial Port"),
    preflightNote: getUiText(
      "settings.esp_flash.preflight_note",
      "Starting a flash builds the latest firmware on this Pi, erases the selected board, and writes the new image over USB. Keep the board powered until the staged progress reaches Done.",
    ),
    refreshLabel: getUiText("settings.esp_flash.refresh_ports", "Refresh"),
    titleText: getUiText("settings.esp_flash.title", "ESP Flash"),
  }));
  const model = useComputed(() => props.model.value?.value ?? DEFAULT_ESP_FLASH_PANEL_MODEL);
  const logEndRef = useRef<HTMLDivElement | null>(null);
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
    const log = model.value.log;
    const logEnd = logEndRef.current;
    if (!logEnd || log.emptyState !== null) {
      return;
    }
    const animationFrameId = globalThis.requestAnimationFrame(() => {
      logEnd.scrollIntoView({ block: "end", inline: "nearest" });
    });
    return () => globalThis.cancelAnimationFrame(animationFrameId);
  });
  const labelTexts = labels.value;

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
                  {labelTexts.titleText}
                </div>
                <div
                  class="subtle"

                >
                  {labelTexts.hintText}
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
                  {labelTexts.portLabel}
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
                  {labelTexts.refreshLabel}
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
                      {labelTexts.detailsTitle}
                    </span>
                    <span
                      class="settings-help-disclosure__caption"

                    >
                      {labelTexts.detailsCaption}
                    </span>
                  </span>
                </summary>
                <div class="settings-help-disclosure__body">
                  <div
                    class="maintenance-note"

                  >
                    {labelTexts.preflightNote}
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
                  {labelTexts.cancelLabel}
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
                    {labelTexts.journeyTitle}
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
                    {labelTexts.logsTitle}
                  </div>
                  <div
                    class="subtle"

                  >
                    {labelTexts.logsIntro}
                  </div>
                </div>
              </div>
              <div
                id="espFlashLogPanel"
                class={
                  model.value.log.emptyState
                    ? "maintenance-log-slot"
                    : "maintenance-log-slot maintenance-log-panel"
                }
                aria-live="polite"
              >
                <EspFlashLogContent model={model.value.log} />
                {model.value.log.emptyState === null ? (
                  <div
                    ref={logEndRef}
                    class="maintenance-log-anchor"
                    data-log-end="true"
                    aria-hidden="true"
                  />
                ) : null}
              </div>
            </section>
          </div>

          <section class="maintenance-card">
            <div class="maintenance-card__header">
              <div>
                <div
                  class="maintenance-card__title"
                >
                  {labelTexts.historyTitle}
                </div>
                <div
                  class="subtle"
                >
                  {labelTexts.historyIntro}
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

export function mountEspFlashPanel(host: HTMLElement, view: EspFlashPanelView): void {
  render(<EspFlashPanel actions={view.actions} model={view.model} />, host);
}
