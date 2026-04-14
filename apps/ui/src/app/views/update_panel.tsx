import { h } from "preact";

import { createUiPreactMount } from "../runtime/ui_preact_mount";

export interface UpdatePanelDom {
  updateOverviewPanel: HTMLElement | null;
  updateStartBtn: HTMLButtonElement;
  updateCancelBtn: HTMLButtonElement;
  updateStatusPanel: HTMLElement;
}

export interface UpdatePanelView {
  readonly dom: UpdatePanelDom;
}

function UpdatePanel() {
  return (
    <div class="panel card">
      <div class="maintenance-layout maintenance-layout--compact">
        <section class="maintenance-card maintenance-card--hero">
          <div class="maintenance-card__header">
            <div>
              <div class="maintenance-card__title" data-i18n="settings.update.title">
                System Update
              </div>
              <div class="subtle" data-i18n="settings.update.hint">
                Use either temporary Wi-Fi credentials or an already-connected USB
                internet uplink to update from GitHub. The hotspot only pauses for
                the Wi-Fi path.
              </div>
            </div>
          </div>
          <div class="maintenance-card__body maintenance-card__body--hero">
            <div class="maintenance-note" data-i18n="settings.update.reconnect_note">
              Note: The page may disconnect while the hotspot is down for the
              Wi-Fi path. It will reconnect automatically.
            </div>
            <div
              id="updateOverviewPanel"
              class="maintenance-stack maintenance-stack--tight"
              aria-live="polite"
            ></div>
            <div class="maintenance-action-row">
              <button
                type="button"
                id="updateStartBtn"
                class="btn btn--success"
                data-i18n="settings.update.start"
              >
                Start Update
              </button>
              <button
                type="button"
                id="updateCancelBtn"
                class="btn btn--danger"
                hidden
                data-i18n="settings.update.cancel"
              >
                Cancel Update
              </button>
            </div>
          </div>
        </section>

        <div
          id="updateStatusPanel"
          class="maintenance-stack maintenance-stack--tight"
          aria-live="polite"
        ></div>
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
    throw new Error(`Update feature requires ${selector}`);
  }
  return element;
}

function createUpdatePanelDom(host: HTMLElement): UpdatePanelDom {
  return {
    updateOverviewPanel: host.querySelector<HTMLElement>("#updateOverviewPanel"),
    updateStartBtn: requiredInHost<HTMLButtonElement>(host, "#updateStartBtn"),
    updateCancelBtn: requiredInHost<HTMLButtonElement>(host, "#updateCancelBtn"),
    updateStatusPanel: requiredInHost<HTMLElement>(host, "#updateStatusPanel"),
  };
}

export function mountUpdatePanel(host: HTMLElement): UpdatePanelView {
  createUiPreactMount(host).render(<UpdatePanel />);
  return {
    dom: createUpdatePanelDom(host),
  };
}
