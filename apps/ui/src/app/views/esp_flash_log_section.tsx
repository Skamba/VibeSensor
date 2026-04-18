import {
  InlineEmptyState,
  type EspFlashLogPanelModel,
} from "./esp_flash_panel_shared";
import { useSignalProperties, type ReadonlySignal } from "../ui_signals";

const ESP_FLASH_LOG_KEYS = ["emptyState", "text"] as const;

export function EspFlashLogContent(props: {
  model: ReadonlySignal<EspFlashLogPanelModel>;
}) {
  const { emptyState, text } = useSignalProperties(props.model, ESP_FLASH_LOG_KEYS);
  if (emptyState.value) {
    return <InlineEmptyState model={emptyState.value} />;
  }
  return <pre class="log-pre log-pre--contained">{text.value}</pre>;
}
