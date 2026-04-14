import { h } from "preact";

import { createUiPreactMount } from "../runtime/ui_preact_mount";

export interface InternetPanelDom {
  internetStatusPanel: HTMLElement | null;
  updateTransportOptions: HTMLElement | null;
  updateTransportChoiceWifi: HTMLElement | null;
  updateTransportChoiceUsb: HTMLElement | null;
  updateWifiFields: HTMLElement | null;
  updateReadinessSummary: HTMLElement | null;
  updateDetailsCaption: HTMLElement | null;
  updateTransportNote: HTMLElement | null;
  updateTransportWifiRadio: HTMLInputElement | null;
  updateTransportUsbRadio: HTMLInputElement | null;
  updateUsbTransportSummary: HTMLElement | null;
  updateSsidInput: HTMLInputElement | null;
  updatePasswordInput: HTMLInputElement | null;
  updateTogglePasswordBtn: HTMLButtonElement | null;
}

export interface InternetPanelView {
  readonly dom: InternetPanelDom;
}

function InternetPanel() {
  return (
    <div class="maintenance-stack">
      <div class="panel card">
        <strong data-i18n="settings.internet.title">Internet</strong>
        <div class="subtle" data-i18n="settings.internet.hint">
          USB internet is optional. When a compatible phone or USB network
          device is detected, the Pi can keep its hotspot active while using USB
          as the upstream connection.
        </div>
        <div
          id="internetStatusPanel"
          class="maintenance-stack"
          aria-live="polite"
          style="margin-top:1rem;"
        ></div>
      </div>

      <section class="maintenance-card">
        <div class="maintenance-card__header">
          <div>
            <div
              class="maintenance-card__title"
              data-i18n="settings.update.controls_title"
            >
              Update connection
            </div>
            <div
              class="subtle"
              data-i18n="settings.update.controls_intro"
            >
              Use Wi-Fi credentials as before, or choose the existing USB
              internet uplink when the Pi detects one.
            </div>
          </div>
        </div>
        <div class="update-form">
          <div
            id="updateTransportOptions"
            class="maintenance-stack maintenance-stack--tight"
          >
            <div
              class="subtle"
              data-i18n="settings.update.transport_label"
            >
              Internet source
            </div>
            <div class="speed-source-choice-grid">
              <label
                id="updateTransportChoiceWifi"
                class="speed-source-choice update-transport-choice"
                data-update-transport-choice="wifi"
              >
                <input
                  class="speed-source-choice__radio"
                  type="radio"
                  id="updateTransportWifiRadio"
                  name="updateTransport"
                  value="wifi"
                  checked
                />
                <span
                  class="speed-source-choice__title"
                  data-i18n="settings.update.transport.wifi_title"
                >
                  Temporary Wi-Fi
                </span>
                <span
                  class="speed-source-choice__caption"
                  data-i18n="settings.update.transport.wifi_summary"
                >
                  Pause the hotspot, join a Wi-Fi network, install, then restore
                  the hotspot.
                </span>
              </label>
              <label
                id="updateTransportChoiceUsb"
                class="speed-source-choice update-transport-choice"
                data-update-transport-choice="usb_internet"
              >
                <input
                  class="speed-source-choice__radio"
                  type="radio"
                  id="updateTransportUsbRadio"
                  name="updateTransport"
                  value="usb_internet"
                />
                <span
                  class="speed-source-choice__title"
                  data-i18n="settings.update.transport.usb_title"
                >
                  Existing USB internet
                </span>
                <span
                  id="updateUsbTransportSummary"
                  class="speed-source-choice__caption"
                ></span>
              </label>
            </div>
          </div>
          <div id="updateWifiFields">
            <div class="form-group">
              <label htmlFor="updateSsidInput" data-i18n="settings.update.ssid">
                Wi-Fi SSID
              </label>
              <input
                type="text"
                id="updateSsidInput"
                autoComplete="off"
                maxLength={64}
                style="width:100%;max-width:20rem;"
              />
            </div>
            <div class="form-group">
              <label
                htmlFor="updatePasswordInput"
                data-i18n="settings.update.password"
              >
                Wi-Fi Password
              </label>
              <div style="display:flex;gap:0.5rem;align-items:center;">
                <input
                  type="password"
                  id="updatePasswordInput"
                  autoComplete="off"
                  maxLength={128}
                  style="width:100%;max-width:20rem;"
                />
                <button
                  type="button"
                  id="updateTogglePasswordBtn"
                  class="btn btn--small"
                >
                  <span data-i18n="settings.update.show_password">Show</span>
                </button>
              </div>
            </div>
          </div>
          <div
            id="updateReadinessSummary"
            class="maintenance-stack maintenance-stack--tight"
            aria-live="polite"
          ></div>
          <details class="settings-help-disclosure settings-help-disclosure--inline">
            <summary class="settings-help-disclosure__summary">
              <span class="settings-help-disclosure__heading">
                <span
                  class="settings-help-disclosure__title"
                  data-i18n="settings.update.details_title"
                >
                  What happens next
                </span>
                <span
                  id="updateDetailsCaption"
                  class="settings-help-disclosure__caption"
                ></span>
              </span>
            </summary>
            <div class="settings-help-disclosure__body">
              <div
                id="updateTransportNote"
                class="maintenance-note"
                data-i18n="settings.update.preflight_note_wifi"
              >
                Starting a Wi-Fi update temporarily pauses hotspot access while
                the Pi joins Wi-Fi, downloads the next release, and restores the
                local web UI when the job is done.
              </div>
            </div>
          </details>
        </div>
      </section>
    </div>
  );
}

function createInternetPanelDom(host: HTMLElement): InternetPanelDom {
  return {
    internetStatusPanel: host.querySelector<HTMLElement>("#internetStatusPanel"),
    updateTransportOptions: host.querySelector<HTMLElement>(
      "#updateTransportOptions",
    ),
    updateTransportChoiceWifi: host.querySelector<HTMLElement>(
      "#updateTransportChoiceWifi",
    ),
    updateTransportChoiceUsb: host.querySelector<HTMLElement>(
      "#updateTransportChoiceUsb",
    ),
    updateWifiFields: host.querySelector<HTMLElement>("#updateWifiFields"),
    updateReadinessSummary: host.querySelector<HTMLElement>(
      "#updateReadinessSummary",
    ),
    updateDetailsCaption: host.querySelector<HTMLElement>(
      "#updateDetailsCaption",
    ),
    updateTransportNote: host.querySelector<HTMLElement>("#updateTransportNote"),
    updateTransportWifiRadio: host.querySelector<HTMLInputElement>(
      "#updateTransportWifiRadio",
    ),
    updateTransportUsbRadio: host.querySelector<HTMLInputElement>(
      "#updateTransportUsbRadio",
    ),
    updateUsbTransportSummary: host.querySelector<HTMLElement>(
      "#updateUsbTransportSummary",
    ),
    updateSsidInput: host.querySelector<HTMLInputElement>("#updateSsidInput"),
    updatePasswordInput: host.querySelector<HTMLInputElement>(
      "#updatePasswordInput",
    ),
    updateTogglePasswordBtn: host.querySelector<HTMLButtonElement>(
      "#updateTogglePasswordBtn",
    ),
  };
}

export function mountInternetPanel(host: HTMLElement): InternetPanelView {
  createUiPreactMount(host).render(<InternetPanel />);
  return {
    dom: createInternetPanelDom(host),
  };
}
