import {
  MaintenanceNote,
  type EspFlashJourneyPanelModel,
  type EspFlashJourneyStageModel,
} from "./esp_flash_panel_shared";

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

export function EspFlashJourneySection(props: {
  model: EspFlashJourneyPanelModel;
}) {
  const { model } = props;
  return (
    <div class="maintenance-journey">
      {model.terminalNoteText ? (
        <MaintenanceNote text={model.terminalNoteText} variant="bad" />
      ) : null}
      <ol class="maintenance-stage-list">
        {model.stages.map((stage) => (
          <JourneyStageItem key={stage.phase} stage={stage} />
        ))}
      </ol>
    </div>
  );
}
