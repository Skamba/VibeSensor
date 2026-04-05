import type { UsbInternetStatusPayload } from "../../transport/http_models";
import { createElementNode, renderChildren } from "./dom_render";
import { createStatusGridRowElement } from "./dom_helpers";

export interface InternetStatusViewDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
}

function createBadgeElement(
  status: UsbInternetStatusPayload,
  deps: InternetStatusViewDeps,
): HTMLSpanElement {
  const { t } = deps;
  const variant = status.usable ? "ok" : status.detected ? "warn" : "muted";
  const key = status.usable
    ? "settings.internet.state.usable"
    : status.detected
      ? "settings.internet.state.detected"
      : "settings.internet.state.not_detected";
  return createElementNode("span", {
    className: "pill",
    data: {
      variant,
    },
    text: t(key),
  });
}

function renderSummary(status: UsbInternetStatusPayload, deps: InternetStatusViewDeps): string {
  const { t } = deps;
  const key = status.usable
    ? "settings.internet.summary.usable"
    : status.detected
      ? "settings.internet.summary.detected"
      : "settings.internet.summary.not_detected";
  return t(key);
}

function createRows(
  status: UsbInternetStatusPayload,
  deps: InternetStatusViewDeps,
): HTMLDivElement[] {
  const { t } = deps;
  const rows = [
    createStatusGridRowElement(
      t("settings.internet.detected"),
      t(status.detected ? "settings.internet.bool.yes" : "settings.internet.bool.no"),
    ),
    createStatusGridRowElement(
      t("settings.internet.usable"),
      t(status.usable ? "settings.internet.bool.yes" : "settings.internet.bool.no"),
    ),
  ];
  if (status.interface_name) {
    rows.push(
      createStatusGridRowElement(
        t("settings.internet.interface"),
        status.interface_name,
      ),
    );
  }
  if (status.connection_name) {
    rows.push(
      createStatusGridRowElement(
        t("settings.internet.connection"),
        status.connection_name,
      ),
    );
  }
  if (status.driver) {
    rows.push(
      createStatusGridRowElement(
        t("settings.internet.driver"),
        status.driver,
      ),
    );
  }
  if (status.ipv4_addresses.length) {
    rows.push(
      createStatusGridRowElement(
        t("settings.internet.addresses"),
        status.ipv4_addresses.join(", "),
      ),
    );
  }
  if (status.gateway) {
    rows.push(
      createStatusGridRowElement(
        t("settings.internet.gateway"),
        status.gateway,
      ),
    );
  }
  rows.push(
    createStatusGridRowElement(
      t("settings.internet.default_route"),
      t(status.has_default_route ? "settings.internet.bool.yes" : "settings.internet.bool.no"),
    ),
  );
  rows.push(
    createStatusGridRowElement(
      t("settings.internet.diagnostic"),
      status.diagnostic,
    ),
  );
  return rows;
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
  renderChildren(
    panel,
    createElementNode("section", {
      className: "maintenance-card",
      children: [
        createElementNode("div", {
          className: "maintenance-card__header",
          children: [
            createElementNode("div", {
              children: [
                createElementNode("div", {
                  className: "maintenance-card__title",
                  text: deps.t("settings.internet.card_title"),
                }),
                createElementNode("div", {
                  className: "subtle",
                  text: renderSummary(status, deps),
                }),
              ],
            }),
            createBadgeElement(status, deps),
          ],
        }),
        createElementNode("div", {
          className: "maintenance-card__body",
          children: [
            createElementNode("div", {
              className: "status-grid",
              children: createRows(status, deps),
            }),
          ],
        }),
      ],
    }),
  );
}
