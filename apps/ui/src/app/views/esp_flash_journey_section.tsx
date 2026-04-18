import { memo } from "preact/compat";
import {
  MaintenanceNote,
  type EspFlashJourneyPanelModel,
  type EspFlashJourneyStageModel,
} from "./esp_flash_panel_shared";
import { useSignalProperties, type ReadonlySignal } from "../ui_signals";

const ESP_FLASH_JOURNEY_KEYS = ["stages", "terminalNoteText"] as const;

function JourneyStageItem(props: {
  stage: EspFlashJourneyStageModel;
}) {
  const { stage } = props;
  return (
    <li
      class="maintenance-stage"
      data-stage-phase={stage.phase}
      data-stage-state={stage.state}
      aria-current={stage.current ? "step" : undefined}
    >
      <span class="maintenance-stage__marker">{stage.markerText}</span>
      <div class="maintenance-stage__body">
        <div class="maintenance-stage__title">{stage.titleText}</div>
        <div class="maintenance-stage__detail">{stage.detailText}</div>
      </div>
      <span class="maintenance-stage__state">{stage.stateText}</span>
    </li>
  );
}

export const EspFlashJourneySection = memo(function EspFlashJourneySection(props: {
  model: ReadonlySignal<EspFlashJourneyPanelModel>;
}) {
  const { stages, terminalNoteText } = useSignalProperties(
    props.model,
    ESP_FLASH_JOURNEY_KEYS,
  );
  return (
    <div class="maintenance-journey">
      {terminalNoteText.value ? (
        <MaintenanceNote text={terminalNoteText.value} variant="bad" />
      ) : null}
      <ol class="maintenance-stage-list">
        {stages.value.map((stage) => (
          <JourneyStageItem key={stage.phase} stage={stage} />
        ))}
      </ol>
    </div>
  );
});
