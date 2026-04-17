import type { UpdateStatusPayload } from "../../api/types";
import type {
  UpdateStatusBadgeModel,
  UpdateStatusBadgeVariant,
  UpdateStatusRowModel,
} from "./update_status_models";
import { formatUpdatePhase } from "./update_journey_builder";

const STATE_VARIANT: Readonly<Record<UpdateStatusPayload["state"], UpdateStatusBadgeVariant>> = {
  idle: "muted",
  running: "warn",
  success: "ok",
  failed: "bad",
};

const ASSET_ISSUE_RE = /asset|artifacts|stale|hash|missing/i;

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const rounded = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const secs = rounded % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${secs}s`;
  if (minutes > 0) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

export function buildStatusRow(labelText: string, valueText: string): UpdateStatusRowModel {
  return { labelText, valueText };
}

export function buildStateBadge(
  status: UpdateStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateStatusBadgeModel {
  return {
    variant: STATE_VARIANT[status.state] ?? "muted",
    text: t(`settings.update.state.${status.state}`),
  };
}

export function buildTransportValueText(
  status: UpdateStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  if (status.transport === "usb_internet") {
    return status.uplink_interface
      ? t("settings.update.transport_value.usb_interface", {
          interface: status.uplink_interface,
        })
      : t("settings.update.transport_value.usb");
  }
  if (status.ssid) {
    return t("settings.update.transport_value.wifi_ssid", { ssid: status.ssid });
  }
  return t("settings.update.transport_value.wifi");
}

export function hasAssetRelatedIssue(status: UpdateStatusPayload): boolean {
  return status.issues.some((issue) => ASSET_ISSUE_RE.test(`${issue.message} ${issue.detail}`));
}

export { formatUpdatePhase };
