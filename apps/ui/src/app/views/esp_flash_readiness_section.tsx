import {
  MaintenanceNote,
  StatusGrid,
  type EspFlashReadinessPanelModel,
} from "./esp_flash_panel_shared";

export function EspFlashReadinessSection(props: {
  model: EspFlashReadinessPanelModel;
}) {
  const { model } = props;
  return (
    <div class="maintenance-stack maintenance-stack--tight">
      <div class="subtle">{model.summaryText}</div>
      {model.rows.length > 0 ? <StatusGrid rows={model.rows} /> : null}
      {model.errorText ? (
        <MaintenanceNote text={model.errorText} variant="bad" />
      ) : null}
    </div>
  );
}
