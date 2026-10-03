import { useEffect, useRef } from "preact/hooks";

import {
  Card,
  InlineEmpty,
  Note,
  Pill,
  ReadinessPanel,
  StageList,
  StatusGrid,
} from "../../components/maintenance";
import { t } from "../../i18n";
import {
  AUTO_PORT,
  canStart,
  flashState,
  historyItems,
  journeyNote,
  journeyStages,
  logPlaceholder,
  portLabel,
  readinessRows,
  readinessSummary,
  startLabel,
  startReadiness,
  statusBadge,
} from "./esp_flash_model";
import {
  cancelFlash,
  flashView,
  logText,
  refreshPorts,
  selectedPort,
  startFlash,
} from "./esp_flash_store";

function FlashLog() {
  const view = flashView.value;
  const text = logText.value;
  const placeholder = logPlaceholder(view, text, t);
  const panel = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = panel.current;
    if (!element || placeholder) {
      return;
    }
    const frame = requestAnimationFrame(() => {
      element.scrollTop = element.scrollHeight;
    });
    return () => cancelAnimationFrame(frame);
  }, [text, placeholder]);
  return (
    <div
      ref={panel}
      id="espFlashLogPanel"
      class={
        placeholder
          ? "maintenance-log-slot"
          : "maintenance-log-slot maintenance-log-panel"
      }
      aria-live="polite"
    >
      {placeholder ? (
        <InlineEmpty title={placeholder.title} body={placeholder.body} />
      ) : (
        <pre class="log-pre log-pre--contained">{text}</pre>
      )}
    </div>
  );
}

function FlashHistory() {
  const items = historyItems(flashView.value, t);
  if (items.length === 0) {
    return (
      <InlineEmpty
        title={t("settings.esp_flash.history_empty_title")}
        body={t("settings.esp_flash.history_empty_body")}
      />
    );
  }
  return (
    <ul class="maintenance-attempt-list">
      {items.map((item, index) => (
        <li class="maintenance-attempt" key={`${item.port}:${index}`}>
          <div class="maintenance-attempt__header">
            <Pill variant={item.variant}>{item.stateText}</Pill>
            <strong>{item.port}</strong>
          </div>
          <div class="maintenance-attempt__meta subtle">{item.meta}</div>
          {item.error ? <Note bad>{item.error}</Note> : null}
        </li>
      ))}
    </ul>
  );
}

export function EspFlash() {
  const view = flashView.value;
  const running = flashState(view.status) === "running";
  const badge = statusBadge(view, t);
  const rows = readinessRows(view, t);
  const note = journeyNote(view, t);
  return (
    <div class="panel card">
      <div class="maintenance-layout maintenance-layout--compact">
        <div class="maintenance-stack">
          <Card
            hero
            title={t("settings.esp_flash.title")}
            subtitle={t("settings.esp_flash.hint")}
            badge={
              <Pill id="espFlashStatusBanner" variant={badge.variant}>
                {badge.text}
              </Pill>
            }
          >
            <div class="maintenance-card__body maintenance-card__body--hero">
              <div class="manual-speed-row">
                <label htmlFor="espFlashPortSelect">
                  {t("settings.esp_flash.port")}
                </label>
                <select
                  id="espFlashPortSelect"
                  disabled={running}
                  value={selectedPort.value}
                  onChange={(event) => {
                    selectedPort.value = event.currentTarget.value || AUTO_PORT;
                  }}
                >
                  <option value={AUTO_PORT}>
                    {t("settings.esp_flash.auto_detect")}
                  </option>
                  {view.ports.map((port) => (
                    <option key={port.port} value={port.port}>
                      {portLabel(port)}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  id="espFlashRefreshPortsBtn"
                  class="btn btn--muted"
                  disabled={running}
                  onClick={() => void refreshPorts()}
                >
                  {t("settings.esp_flash.refresh_ports")}
                </button>
              </div>
              <div
                id="espFlashStartSummary"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              >
                <ReadinessPanel model={startReadiness(view, t)} />
              </div>
              <div
                id="espFlashReadinessPanel"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              >
                <div class="maintenance-stack maintenance-stack--tight">
                  <div class="subtle">{readinessSummary(view, t)}</div>
                  {rows.length > 0 ? <StatusGrid rows={rows} /> : null}
                  {view.status.error ? (
                    <Note bad>{view.status.error}</Note>
                  ) : null}
                </div>
              </div>
              <details class="settings-help-disclosure settings-help-disclosure--inline">
                <summary class="settings-help-disclosure__summary">
                  <span class="settings-help-disclosure__heading">
                    <span class="settings-help-disclosure__title">
                      {t("settings.esp_flash.details_title")}
                    </span>
                    <span class="settings-help-disclosure__caption">
                      {t("settings.esp_flash.details_caption")}
                    </span>
                  </span>
                </summary>
                <div class="settings-help-disclosure__body">
                  <Note>{t("settings.esp_flash.preflight_note")}</Note>
                </div>
              </details>
              <div class="maintenance-action-row">
                <button
                  type="button"
                  id="espFlashStartBtn"
                  class="btn btn--success"
                  hidden={running}
                  disabled={!canStart(view)}
                  onClick={() => void startFlash()}
                >
                  {startLabel(view, t)}
                </button>
                <button
                  type="button"
                  id="espFlashCancelBtn"
                  class="btn btn--danger"
                  hidden={!running}
                  disabled={!running}
                  onClick={() => void cancelFlash()}
                >
                  {t("settings.esp_flash.cancel")}
                </button>
              </div>
            </div>
          </Card>

          <div class="maintenance-pair-grid maintenance-pair-grid--focus">
            <Card title={t("settings.esp_flash.journey_title")}>
              <div
                id="espFlashJourneyPanel"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              >
                <div class="maintenance-journey">
                  {note ? <Note bad>{note}</Note> : null}
                  <StageList stages={journeyStages(view, t)} />
                </div>
              </div>
            </Card>
            <Card
              title={t("settings.esp_flash.logs_title")}
              subtitle={t("settings.esp_flash.logs_intro")}
            >
              <FlashLog />
            </Card>
          </div>

          <Card
            title={t("settings.esp_flash.history")}
            subtitle={t("settings.esp_flash.history_intro")}
          >
            <div
              id="espFlashHistoryPanel"
              class="maintenance-stack maintenance-stack--tight"
            >
              <FlashHistory />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
