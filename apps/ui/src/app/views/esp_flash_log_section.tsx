import {
  InlineEmptyState,
  type EspFlashLogPanelModel,
} from "./esp_flash_panel_shared";

export function EspFlashLogContent(props: {
  model: EspFlashLogPanelModel;
}) {
  const { model } = props;
  if (model.emptyState) {
    return <InlineEmptyState model={model.emptyState} />;
  }
  return <pre class="log-pre log-pre--contained">{model.text}</pre>;
}
