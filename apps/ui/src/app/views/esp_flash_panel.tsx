import { h } from "preact";

import { createUiPreactMount } from "../runtime/ui_preact_mount";

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

export interface EspFlashPanelView {
  readonly dom: EspFlashPanelDom;
}

function EspFlashPanel() {
  return (
    <div class="panel card">
      <strong data-i18n="settings.esp_flash.title">ESP Flash</strong>
      <div class="subtle" data-i18n="settings.esp_flash.hint">
        Flash ESP firmware from local source on this Pi.
      </div>
      <div class="maintenance-layout">
        <div class="maintenance-stack">
          <section class="maintenance-card">
            <div class="maintenance-card__header">
              <div>
                <div
                  class="maintenance-card__title"
                  data-i18n="settings.esp_flash.controls_title"
                >
                  Flash target
                </div>
                <div
                  class="subtle"
                  data-i18n="settings.esp_flash.controls_intro"
                >
                  Choose a serial port or leave auto-detect enabled, then start
                  the firmware build and flash flow.
                </div>
              </div>
            </div>
            <div class="manual-speed-row">
              <label
                htmlFor="espFlashPortSelect"
                data-i18n="settings.esp_flash.port"
              >
                Serial Port
              </label>
              <select id="espFlashPortSelect">
                <option
                  value="__auto__"
                  data-i18n="settings.esp_flash.auto_detect"
                >
                  Auto-detect
                </option>
              </select>
              <button
                type="button"
                id="espFlashRefreshPortsBtn"
                class="btn btn--muted"
                data-i18n="settings.esp_flash.refresh_ports"
              >
                Refresh
              </button>
            </div>
            <div
              id="espFlashStartSummary"
              class="maintenance-stack maintenance-stack--tight"
              aria-live="polite"
            ></div>
            <details class="settings-help-disclosure settings-help-disclosure--inline">
              <summary class="settings-help-disclosure__summary">
                <span class="settings-help-disclosure__heading">
                  <span
                    class="settings-help-disclosure__title"
                    data-i18n="settings.esp_flash.details_title"
                  >
                    What happens next
                  </span>
                  <span
                    class="settings-help-disclosure__caption"
                    data-i18n="settings.esp_flash.details_caption"
                  >
                    Build, erase, and write the current firmware over USB.
                  </span>
                </span>
              </summary>
              <div class="settings-help-disclosure__body">
                <div
                  class="maintenance-note"
                  data-i18n="settings.esp_flash.preflight_note"
                >
                  Starting a flash builds the latest firmware on this Pi, erases
                  the selected board, and writes the new image over USB. Keep
                  the board powered until the staged progress reaches Done.
                </div>
              </div>
            </details>
            <div class="maintenance-action-row">
              <button
                type="button"
                id="espFlashStartBtn"
                class="btn btn--success"
                data-i18n="settings.esp_flash.start"
              >
                Flash latest
              </button>
              <button
                type="button"
                id="espFlashCancelBtn"
                class="btn btn--danger"
                data-i18n="settings.esp_flash.cancel"
                hidden
                disabled
              >
                Cancel
              </button>
            </div>
          </section>

          <div class="maintenance-pair-grid">
            <section class="maintenance-card">
              <div class="maintenance-card__header">
                <div>
                  <div
                    class="maintenance-card__title"
                    data-i18n="settings.esp_flash.current_status_title"
                  >
                    Current readiness
                  </div>
                </div>
                <span
                  id="espFlashStatusBanner"
                  class="pill pill--muted"
                  data-i18n="settings.esp_flash.state.idle"
                >
                  Idle
                </span>
              </div>
              <div
                id="espFlashReadinessPanel"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              ></div>
            </section>

            <section class="maintenance-card">
              <div class="maintenance-card__header">
                <div>
                  <div
                    class="maintenance-card__title"
                    data-i18n="settings.esp_flash.journey_title"
                  >
                    Expected stages
                  </div>
                </div>
              </div>
              <div
                id="espFlashJourneyPanel"
                class="maintenance-stack maintenance-stack--tight"
                aria-live="polite"
              ></div>
            </section>
          </div>

          <section class="maintenance-card">
            <div class="maintenance-card__header">
              <div>
                <div
                  class="maintenance-card__title"
                  data-i18n="settings.esp_flash.logs_title"
                >
                  Live flash output
                </div>
                <div
                  class="subtle"
                  data-i18n="settings.esp_flash.logs_intro"
                >
                  Build, erase, and upload output appears here while the
                  toolchain runs.
                </div>
              </div>
            </div>
            <div
              id="espFlashLogPanel"
              class="maintenance-log-slot"
              aria-live="polite"
            ></div>
          </section>

          <section class="maintenance-card">
            <div class="maintenance-card__header">
              <div>
                <div
                  class="maintenance-card__title"
                  data-i18n="settings.esp_flash.history"
                >
                  Recent attempts
                </div>
                <div
                  class="subtle"
                  data-i18n="settings.esp_flash.history_intro"
                >
                  Recent flashes stay here so the next operator can see what
                  happened last.
                </div>
              </div>
            </div>
            <div
              id="espFlashHistoryPanel"
              class="maintenance-stack maintenance-stack--tight"
            ></div>
          </section>
        </div>
      </div>
    </div>
  );
}

function requiredInHost<T extends Element>(
  host: ParentNode,
  selector: string,
): T {
  const element = host.querySelector<T>(selector);
  if (!element) {
    throw new Error(`ESP flash feature requires ${selector}`);
  }
  return element;
}

function createEspFlashPanelDom(host: HTMLElement): EspFlashPanelDom {
  return {
    espFlashPortSelect: host.querySelector<HTMLSelectElement>("#espFlashPortSelect"),
    espFlashRefreshPortsBtn: host.querySelector<HTMLButtonElement>(
      "#espFlashRefreshPortsBtn",
    ),
    espFlashStartBtn: requiredInHost<HTMLButtonElement>(host, "#espFlashStartBtn"),
    espFlashCancelBtn: host.querySelector<HTMLButtonElement>("#espFlashCancelBtn"),
    espFlashStartSummary: host.querySelector<HTMLElement>("#espFlashStartSummary"),
    espFlashStatusBanner: host.querySelector<HTMLElement>("#espFlashStatusBanner"),
    espFlashReadinessPanel: host.querySelector<HTMLElement>(
      "#espFlashReadinessPanel",
    ),
    espFlashJourneyPanel: host.querySelector<HTMLElement>("#espFlashJourneyPanel"),
    espFlashLogPanel: host.querySelector<HTMLElement>("#espFlashLogPanel"),
    espFlashHistoryPanel: host.querySelector<HTMLElement>("#espFlashHistoryPanel"),
  };
}

export function mountEspFlashPanel(host: HTMLElement): EspFlashPanelView {
  createUiPreactMount(host).render(<EspFlashPanel />);
  return {
    dom: createEspFlashPanelDom(host),
  };
}
