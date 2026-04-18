import { memo } from "preact/compat";
import {
  MaintenanceNote,
  StatusGrid,
  type EspFlashReadinessPanelModel,
} from "./esp_flash_panel_shared";
import { useSignalProperties, type ReadonlySignal } from "../ui_signals";

const ESP_FLASH_READINESS_KEYS = ["errorText", "rows", "summaryText"] as const;

export const EspFlashReadinessSection = memo(function EspFlashReadinessSection(props: {
  model: ReadonlySignal<EspFlashReadinessPanelModel>;
}) {
  const { errorText, rows, summaryText } = useSignalProperties(
    props.model,
    ESP_FLASH_READINESS_KEYS,
  );
  return (
    <div class="maintenance-stack maintenance-stack--tight">
      <div class="subtle">{summaryText.value}</div>
      {rows.value.length > 0 ? <StatusGrid rows={rows.value} /> : null}
      {errorText.value ? (
        <MaintenanceNote text={errorText.value} variant="bad" />
      ) : null}
    </div>
  );
});
