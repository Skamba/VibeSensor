import type {
  InlineStateActionVariant,
  InlineStatePanelElement,
} from "./dom_helpers";
import {
  captureReadinessCheck,
  captureReadinessDetailText,
  type CaptureReadinessPayload,
  type CaptureReadinessTextDeps,
  type CaptureReadinessCheckPayload,
} from "./realtime_capture_readiness_models";

export const REALTIME_LOGGING_SUMMARY_ACTIONS = [
  "open-history",
  "open-cars",
  "open-add-car",
  "open-sensors",
  "open-speed-source",
] as const;

export type RealtimeLoggingSummaryAction = (typeof REALTIME_LOGGING_SUMMARY_ACTIONS)[number];

export interface RealtimeLoggingSummaryPanelModel
  extends Omit<InlineStatePanelElement, "action"> {
  action?: {
    action: RealtimeLoggingSummaryAction;
    labelText: string;
    variant?: InlineStateActionVariant;
  };
}

function setupRecordingAction(
  check: CaptureReadinessCheckPayload,
  deps: CaptureReadinessTextDeps,
): RealtimeLoggingSummaryPanelModel["action"] | undefined {
  const { t } = deps;
  if (check.check_key === "sensors_ready") {
    return {
      action: "open-sensors",
      labelText: t("dashboard.logging.blocked.setup.action.sensors"),
    };
  }
  if (check.check_key === "reference_ready") {
    if (check.reason_key === "active_car_missing" || check.reason_key === "order_reference_incomplete") {
      return {
        action: "open-cars",
        labelText: t("dashboard.logging.blocked.setup.action.cars"),
      };
    }
    return {
      action: "open-speed-source",
      labelText: t("dashboard.logging.blocked.setup.action.speed_source"),
    };
  }
  if (check.check_key === "speed_stable" && check.reason_key === "speed_sample_missing") {
    return {
      action: "open-speed-source",
      labelText: t("dashboard.logging.blocked.setup.action.speed_source"),
    };
  }
  return undefined;
}

export function buildBlockedRecordingPanel(
  blockReason: "no_cars" | "no_active",
  deps: CaptureReadinessTextDeps,
): RealtimeLoggingSummaryPanelModel {
  const { t } = deps;
  if (blockReason === "no_cars") {
    return {
      titleText: t("dashboard.logging.blocked.no_cars.title"),
      bodyText: t("dashboard.logging.blocked.no_cars.body"),
      detailText: t("dashboard.logging.blocked.no_cars.detail"),
      action: {
        action: "open-add-car",
        labelText: t("dashboard.logging.blocked.no_cars.action"),
        variant: "success",
      },
    };
  }
  return {
    titleText: t("dashboard.logging.blocked.no_active.title"),
    bodyText: t("dashboard.logging.blocked.no_active.body"),
    detailText: t("dashboard.logging.blocked.no_active.detail"),
    action: {
      action: "open-cars",
      labelText: t("dashboard.logging.blocked.no_active.action"),
    },
  };
}

export function buildSetupRecordingPanel(
  readiness: CaptureReadinessPayload | null,
  deps: CaptureReadinessTextDeps,
): RealtimeLoggingSummaryPanelModel | null {
  if (!readiness || readiness.is_ready) {
    return null;
  }
  const primaryCheck = readiness.checks.find((check) => (
    check.state === "fail" && check.check_key !== "capture_ready"
  )) ?? captureReadinessCheck(readiness, "capture_ready");
  if (!primaryCheck) {
    return null;
  }
  return {
    titleText: deps.t("dashboard.logging.blocked.setup.title"),
    bodyText: captureReadinessDetailText(primaryCheck, deps),
    action: setupRecordingAction(primaryCheck, deps),
  };
}

export function buildPostRunSummaryPanel(
  kind: "processing" | "saved",
  runId: string,
  deps: CaptureReadinessTextDeps,
): RealtimeLoggingSummaryPanelModel {
  const { t } = deps;
  if (kind === "processing") {
    return {
      titleText: t("dashboard.logging.processing.title", { runId }),
      bodyText: t("dashboard.logging.processing.body"),
      detailText: t("dashboard.logging.processing.detail"),
      action: {
        action: "open-history",
        labelText: t("dashboard.logging.processing.action"),
      },
    };
  }
  return {
    titleText: t("dashboard.logging.saved.title", { runId }),
    bodyText: t("dashboard.logging.saved.body"),
    detailText: t("dashboard.logging.saved.detail"),
    action: {
      action: "open-history",
      labelText: t("dashboard.logging.saved.action"),
    },
  };
}
