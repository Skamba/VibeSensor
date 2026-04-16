import type { UsbInternetStatusPayload } from "../../transport/http_models";
import type {
  UpdateStatusBadgeModel,
  UpdateStatusRowModel,
} from "./update_status_models";

export interface InternetStatusViewDeps {
  t: (key: string, vars?: Record<string, unknown>) => string;
}

export interface InternetStatusPanelModel {
  badge: UpdateStatusBadgeModel;
  rows: readonly UpdateStatusRowModel[];
  summaryText: string;
  titleText: string;
}

function buildBadgeModel(
  status: UsbInternetStatusPayload,
  deps: InternetStatusViewDeps,
): UpdateStatusBadgeModel {
  const variant = status.usable ? "ok" : status.detected ? "warn" : "muted";
  const key = status.usable
    ? "settings.internet.state.usable"
    : status.detected
      ? "settings.internet.state.detected"
      : "settings.internet.state.not_detected";
  return {
    variant,
    text: deps.t(key),
  };
}

function buildSummaryText(
  status: UsbInternetStatusPayload,
  deps: InternetStatusViewDeps,
): string {
  const key = status.usable
    ? "settings.internet.summary.usable"
    : status.detected
      ? "settings.internet.summary.detected"
      : "settings.internet.summary.not_detected";
  return deps.t(key);
}

function buildStatusRows(
  status: UsbInternetStatusPayload,
  deps: InternetStatusViewDeps,
): UpdateStatusRowModel[] {
  const { t } = deps;
  const rows: UpdateStatusRowModel[] = [
    {
      labelText: t("settings.internet.detected"),
      valueText: t(
        status.detected ? "settings.internet.bool.yes" : "settings.internet.bool.no",
      ),
    },
    {
      labelText: t("settings.internet.usable"),
      valueText: t(
        status.usable ? "settings.internet.bool.yes" : "settings.internet.bool.no",
      ),
    },
  ];
  if (status.interface_name) {
    rows.push({
      labelText: t("settings.internet.interface"),
      valueText: status.interface_name,
    });
  }
  if (status.connection_name) {
    rows.push({
      labelText: t("settings.internet.connection"),
      valueText: status.connection_name,
    });
  }
  if (status.driver) {
    rows.push({
      labelText: t("settings.internet.driver"),
      valueText: status.driver,
    });
  }
  if (status.ipv4_addresses.length) {
    rows.push({
      labelText: t("settings.internet.addresses"),
      valueText: status.ipv4_addresses.join(", "),
    });
  }
  if (status.gateway) {
    rows.push({
      labelText: t("settings.internet.gateway"),
      valueText: status.gateway,
    });
  }
  rows.push(
    {
      labelText: t("settings.internet.default_route"),
      valueText: t(
        status.has_default_route
          ? "settings.internet.bool.yes"
          : "settings.internet.bool.no",
      ),
    },
    {
      labelText: t("settings.internet.diagnostic"),
      valueText: status.diagnostic,
    },
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

export function buildInternetStatusPanelModel(
  status: UsbInternetStatusPayload,
  deps: InternetStatusViewDeps,
): InternetStatusPanelModel {
  return {
    badge: buildBadgeModel(status, deps),
    rows: buildStatusRows(status, deps),
    summaryText: buildSummaryText(status, deps),
    titleText: deps.t("settings.internet.card_title"),
  };
}
