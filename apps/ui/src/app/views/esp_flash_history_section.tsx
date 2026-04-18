import {
  InlineEmptyState,
  MaintenanceNote,
  StatusBadge,
  type EspFlashHistoryPanelModel,
} from "./esp_flash_panel_shared";

export function EspFlashHistoryContent(props: {
  model: EspFlashHistoryPanelModel;
}) {
  const { model } = props;
  if (model.emptyState) {
    return <InlineEmptyState model={model.emptyState} />;
  }
  return (
    <ul class="maintenance-attempt-list">
      {model.attempts.map((attempt, index) => (
        <li class="maintenance-attempt" key={`${attempt.portText}:${index}`}>
          <div class="maintenance-attempt__header">
            <StatusBadge badge={attempt.badge} />
            <strong>{attempt.portText}</strong>
          </div>
          <div class="maintenance-attempt__meta subtle">{attempt.metaText}</div>
          {attempt.errorText ? (
            <MaintenanceNote text={attempt.errorText} variant="bad" />
          ) : null}
        </li>
      ))}
    </ul>
  );
}
