import type { UsbInternetStatusPayload } from "../../api/types";
import { renderStatusGridRow } from "./dom_helpers";

export interface InternetStatusViewDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
}

function renderBadge(status: UsbInternetStatusPayload, deps: InternetStatusViewDeps): string {
  const { t, escapeHtml } = deps;
  const variant = status.usable ? "ok" : status.detected ? "warn" : "muted";
  const key = status.usable
    ? "settings.internet.state.usable"
    : status.detected
      ? "settings.internet.state.detected"
      : "settings.internet.state.not_detected";
  return `<span class="pill pill--${variant}">${escapeHtml(t(key))}</span>`;
}

function renderSummary(status: UsbInternetStatusPayload, deps: InternetStatusViewDeps): string {
  const { t, escapeHtml } = deps;
  const key = status.usable
    ? "settings.internet.summary.usable"
    : status.detected
      ? "settings.internet.summary.detected"
      : "settings.internet.summary.not_detected";
  return escapeHtml(t(key));
}

function renderRows(status: UsbInternetStatusPayload, deps: InternetStatusViewDeps): string {
  const { t, escapeHtml } = deps;
  const rows: string[] = [
    renderStatusGridRow(
      escapeHtml(t("settings.internet.detected")),
      escapeHtml(t(status.detected ? "settings.internet.bool.yes" : "settings.internet.bool.no")),
    ),
    renderStatusGridRow(
      escapeHtml(t("settings.internet.usable")),
      escapeHtml(t(status.usable ? "settings.internet.bool.yes" : "settings.internet.bool.no")),
    ),
  ];
  if (status.interface_name) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.internet.interface")),
        escapeHtml(status.interface_name),
      ),
    );
  }
  if (status.connection_name) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.internet.connection")),
        escapeHtml(status.connection_name),
      ),
    );
  }
  if (status.driver) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.internet.driver")),
        escapeHtml(status.driver),
      ),
    );
  }
  if (status.ipv4_addresses.length) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.internet.addresses")),
        escapeHtml(status.ipv4_addresses.join(", ")),
      ),
    );
  }
  if (status.gateway) {
    rows.push(
      renderStatusGridRow(
        escapeHtml(t("settings.internet.gateway")),
        escapeHtml(status.gateway),
      ),
    );
  }
  rows.push(
    renderStatusGridRow(
      escapeHtml(t("settings.internet.default_route")),
      escapeHtml(
        t(status.has_default_route ? "settings.internet.bool.yes" : "settings.internet.bool.no"),
      ),
    ),
  );
  rows.push(
    renderStatusGridRow(
      escapeHtml(t("settings.internet.diagnostic")),
      escapeHtml(status.diagnostic),
    ),
  );
  return rows.join("");
}

export function formatUsbInternetSummary(
  status: UsbInternetStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  if (!status.usable) {
    return t("settings.update.transport.usb_summary_unavailable");
  }
  if (status.interface_name) {
    return t("settings.update.transport.usb_summary_interface", {
      interface: status.interface_name,
    });
  }
  return t("settings.update.transport.usb_summary");
}

export function renderInternetStatusPanel(
  panel: HTMLElement,
  status: UsbInternetStatusPayload,
  deps: InternetStatusViewDeps,
): void {
  panel.innerHTML = [
    `<section class="maintenance-card">`,
    `<div class="maintenance-card__header">`,
    `<div>`,
    `<div class="maintenance-card__title">${deps.escapeHtml(deps.t("settings.internet.card_title"))}</div>`,
    `<div class="subtle">${renderSummary(status, deps)}</div>`,
    `</div>`,
    renderBadge(status, deps),
    `</div>`,
    `<div class="maintenance-card__body"><div class="status-grid">${renderRows(status, deps)}</div></div>`,
    `</section>`,
  ].join("");
}
