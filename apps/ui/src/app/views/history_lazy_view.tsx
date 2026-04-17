import { useEffect } from "preact/hooks";

import { HistoryPanel } from "./history_panel";
import type { HistoryPanelView } from "./history_table_view";

export interface HistoryLazyViewProps {
  onReady?(): void;
  view: HistoryPanelView;
}

export default function HistoryLazyView(props: HistoryLazyViewProps) {
  useEffect(() => {
    props.onReady?.();
  }, [props.onReady]);

  return <HistoryPanel actions={props.view.actions} model={props.view.model} />;
}
