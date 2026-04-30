import type {
  EspFlashJourneyPanelModel,
  EspFlashJourneyStageModel,
  EspFlashJourneyStageState,
} from "./esp_flash_panel";
import {
  safeEspFlashState,
  type EspFlashFeatureRenderState,
} from "./esp_flash_readiness_presenter";

const ESP_FLASH_JOURNEY_STAGES = [
  {
    detailKey: "settings.esp_flash.journey.detail.validating",
    phase: "validating",
    titleKey: "settings.esp_flash.phase.validating",
  },
  {
    detailKey: "settings.esp_flash.journey.detail.preparing",
    phase: "preparing",
    titleKey: "settings.esp_flash.phase.preparing",
  },
  {
    detailKey: "settings.esp_flash.journey.detail.erasing",
    phase: "erasing",
    titleKey: "settings.esp_flash.phase.erasing",
  },
  {
    detailKey: "settings.esp_flash.journey.detail.flashing",
    phase: "flashing",
    titleKey: "settings.esp_flash.phase.flashing",
  },
  {
    detailKey: "settings.esp_flash.journey.detail.done",
    phase: "done",
    titleKey: "settings.esp_flash.phase.done",
  },
] as const;

function stageStateLabel(
  t: (key: string, vars?: Record<string, unknown>) => string,
  state: EspFlashJourneyStageState,
): string {
  return t(`maintenance.stage_state.${state}`);
}

function journeyStageIndex(phase: string | null | undefined): number {
  return ESP_FLASH_JOURNEY_STAGES.findIndex(
    (stage) => stage.phase === (phase || "idle"),
  );
}

function resolvedJourneyPhase(
  state: EspFlashFeatureRenderState,
): string | null {
  if (journeyStageIndex(state.status.phase) !== -1) {
    return state.status.phase || null;
  }
  const safeState = safeEspFlashState(state.status.state);
  if (safeState === "failed" || safeState === "cancelled") {
    return state.lastJourneyPhase;
  }
  return null;
}

function resolveJourneyStageState(
  state: EspFlashFeatureRenderState,
  stageIndex: number,
): EspFlashJourneyStageState {
  const safeState = safeEspFlashState(state.status.state);
  if (safeState === "success") {
    return "done";
  }
  if (safeState === "idle") {
    return "upcoming";
  }
  const currentIndex = journeyStageIndex(resolvedJourneyPhase(state));
  if (currentIndex === -1) {
    return "upcoming";
  }
  if (stageIndex < currentIndex) {
    return "done";
  }
  if (stageIndex === currentIndex) {
    return safeState === "failed" || safeState === "cancelled"
      ? "attention"
      : "active";
  }
  return "upcoming";
}

export function buildJourneyPanelModel(
  state: EspFlashFeatureRenderState,
  t: (key: string, vars?: Record<string, unknown>) => string,
): EspFlashJourneyPanelModel {
  const stages: EspFlashJourneyStageModel[] = ESP_FLASH_JOURNEY_STAGES.map(
    (stage, index) => {
      const stageState = resolveJourneyStageState(state, index);
      return {
        current: stageState === "active",
        detailText: t(stage.detailKey),
        markerText: stageState === "done" ? "\u2713" : `${index + 1}`,
        phase: stage.phase,
        state: stageState,
        stateText: stageStateLabel(t, stageState),
        titleText: t(stage.titleKey),
      };
    },
  );
  const terminalState = safeEspFlashState(state.status.state);
  return {
    stages,
    terminalNoteText:
      terminalState === "failed" || terminalState === "cancelled"
        ? t(`settings.esp_flash.journey_terminal.${terminalState}`)
        : null,
  };
}
