import {
  InlineEmptyState,
  MaintenanceNote,
  StatusBadge,
  type EspFlashHistoryPanelModel,
} from "./esp_flash_panel_shared";
import { useSignalProperties, type ReadonlySignal } from "../ui_signals";

const ESP_FLASH_HISTORY_KEYS = ["attempts", "emptyState"] as const;

export function EspFlashHistoryContent(props: {
  model: ReadonlySignal<EspFlashHistoryPanelModel>;
}) {
  const { attempts, emptyState } = useSignalProperties(props.model, ESP_FLASH_HISTORY_KEYS);
  if (emptyState.value) {
    return <InlineEmptyState model={emptyState.value} />;
  }
  return (
    <ul class="maintenance-attempt-list">
      {attempts.value.map((attempt, index) => (
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
