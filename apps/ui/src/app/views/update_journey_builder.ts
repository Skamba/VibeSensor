import type { UpdateIssue, UpdateStatusPayload } from "../../api/types";
import type {
  JourneyStageState,
  UpdateFailureSummary,
  UpdateJourneyFailureNoteModel,
  UpdateJourneySectionModel,
  UpdateJourneyTransport,
  UpdateStatusViewDeps,
} from "./update_status_models";

type UpdateJourneyStage = {
  phase: string;
  titleKey: string;
  detailKey: string;
};

const WIFI_JOURNEY_STAGES: readonly UpdateJourneyStage[] = [
  {
    phase: "validating",
    titleKey: "settings.update.phase.validating",
    detailKey: "settings.update.journey.detail.validating",
  },
  {
    phase: "stopping_hotspot",
    titleKey: "settings.update.phase.stopping_hotspot",
    detailKey: "settings.update.journey.detail.stopping_hotspot",
  },
  {
    phase: "connecting_wifi",
    titleKey: "settings.update.phase.connecting_wifi",
    detailKey: "settings.update.journey.detail.connecting_wifi",
  },
  {
    phase: "checking",
    titleKey: "settings.update.phase.checking",
    detailKey: "settings.update.journey.detail.checking",
  },
  {
    phase: "downloading",
    titleKey: "settings.update.phase.downloading",
    detailKey: "settings.update.journey.detail.downloading",
  },
  {
    phase: "installing",
    titleKey: "settings.update.phase.installing",
    detailKey: "settings.update.journey.detail.installing",
  },
  {
    phase: "restoring_hotspot",
    titleKey: "settings.update.phase.restoring_hotspot",
    detailKey: "settings.update.journey.detail.restoring_hotspot",
  },
  {
    phase: "done",
    titleKey: "settings.update.phase.done",
    detailKey: "settings.update.journey.detail.done",
  },
] as const;

const USB_JOURNEY_STAGES: readonly UpdateJourneyStage[] = [
  {
    phase: "validating",
    titleKey: "settings.update.phase.validating",
    detailKey: "settings.update.journey.detail.validating",
  },
  {
    phase: "connecting_usb_internet",
    titleKey: "settings.update.phase.connecting_usb_internet",
    detailKey: "settings.update.journey.detail.connecting_usb_internet",
  },
  {
    phase: "checking",
    titleKey: "settings.update.phase.checking",
    detailKey: "settings.update.journey.detail.checking",
  },
  {
    phase: "downloading",
    titleKey: "settings.update.phase.downloading",
    detailKey: "settings.update.journey.detail.downloading",
  },
  {
    phase: "installing",
    titleKey: "settings.update.phase.installing",
    detailKey: "settings.update.journey.detail.installing",
  },
  {
    phase: "done",
    titleKey: "settings.update.phase.done",
    detailKey: "settings.update.journey.detail.done",
  },
] as const;

function translateKeyOrFallback(
  key: string,
  fallback: string,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  const translated = t(key);
  return translated === key ? fallback : translated;
}

function normalizeUpdatePhase(phase: string | null | undefined): string {
  if (!phase) return "idle";
  if (phase === "restore") return "restoring_hotspot";
  return phase;
}

function journeyStages(
  transport: UpdateJourneyTransport,
): readonly UpdateJourneyStage[] {
  return transport === "usb_internet"
    ? USB_JOURNEY_STAGES
    : WIFI_JOURNEY_STAGES;
}

function resolvedJourneyTransport(
  status: UpdateStatusPayload,
  selectedTransport: UpdateJourneyTransport,
): UpdateJourneyTransport {
  if (status.state === "idle") {
    return selectedTransport;
  }
  return status.transport === "usb_internet" ? "usb_internet" : "wifi";
}

function journeyStageIndex(
  phase: string | null | undefined,
  stages: readonly UpdateJourneyStage[],
): number {
  const normalized = normalizeUpdatePhase(phase);
  return stages.findIndex((stage) => stage.phase === normalized);
}

function resolveJourneyStageState(
  status: UpdateStatusPayload,
  stages: readonly UpdateJourneyStage[],
  stageIndex: number,
): JourneyStageState {
  if (status.state === "success") return "done";
  if (status.state === "idle") return "upcoming";
  const currentIndex = journeyStageIndex(status.phase, stages);
  if (currentIndex === -1) {
    return "upcoming";
  }
  if (stageIndex < currentIndex) return "done";
  if (stageIndex === currentIndex) {
    return status.state === "failed" ? "attention" : "active";
  }
  return "upcoming";
}

function primaryJourneyIssue(status: UpdateStatusPayload): UpdateIssue | null {
  const currentPhase = normalizeUpdatePhase(status.phase);
  for (let index = status.issues.length - 1; index >= 0; index -= 1) {
    const issue = status.issues[index];
    if (normalizeUpdatePhase(issue.phase) === currentPhase) {
      return issue;
    }
  }
  return status.issues.length > 0
    ? status.issues[status.issues.length - 1]
    : null;
}

function recoveryGuidanceKey(phase: string): string {
  switch (normalizeUpdatePhase(phase)) {
    case "stopping_hotspot":
    case "connecting_wifi":
    case "restoring_hotspot":
      return "settings.update.recovery.wifi";
    case "connecting_usb_internet":
      return "settings.update.recovery.usb";
    case "checking":
    case "downloading":
      return "settings.update.recovery.network";
    case "installing":
      return "settings.update.recovery.install";
    default:
      return "settings.update.recovery.generic";
  }
}

function buildJourneyFailureNoteModel(
  status: UpdateStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateJourneyFailureNoteModel | null {
  const failure = getUpdateFailureSummary(status, t);
  if (!failure) {
    return null;
  }
  return {
    summaryText: failure.message
      ? `${failure.phaseLabel} — ${failure.message}`
      : failure.phaseLabel,
    detailText: failure.detail,
    recoveryTitleText: failure.recoveryTitle,
    recoveryDetailText: failure.recoveryDetail,
  };
}

export function formatUpdatePhase(
  phase: string | null | undefined,
  t: (key: string, vars?: Record<string, unknown>) => string,
): string {
  const normalized = normalizeUpdatePhase(phase);
  return translateKeyOrFallback(
    `settings.update.phase.${normalized}`,
    normalized,
    t,
  );
}

export function getUpdateFailureSummary(
  status: UpdateStatusPayload,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateFailureSummary | null {
  if (status.state !== "failed") {
    return null;
  }
  const issue = primaryJourneyIssue(status);
  const phase = issue?.phase ?? status.phase;
  const keyBase = recoveryGuidanceKey(phase);
  return {
    detail: issue?.detail ?? null,
    message: issue?.message ?? null,
    phaseLabel: formatUpdatePhase(phase, t),
    recoveryTitle: t(`${keyBase}.title`),
    recoveryDetail: t(`${keyBase}.detail`),
  };
}

export function buildUpdateJourneySectionModel(
  status: UpdateStatusPayload,
  deps: UpdateStatusViewDeps,
): UpdateJourneySectionModel {
  const stages = journeyStages(
    resolvedJourneyTransport(status, deps.selectedTransport),
  );
  return {
    titleText: deps.t("settings.update.journey_title"),
    subtitleText: deps.t("settings.update.journey_intro"),
    failureNote: buildJourneyFailureNoteModel(status, deps.t),
    stages: stages.map((stage, index) => {
      const state = resolveJourneyStageState(status, stages, index);
      return {
        phase: stage.phase,
        titleText: deps.t(stage.titleKey),
        detailText: deps.t(stage.detailKey),
        markerText: state === "done" ? "✓" : `${index + 1}`,
        state,
        stateText: deps.t(`maintenance.stage_state.${state}`),
        current: state === "active",
      };
    }),
  };
}
