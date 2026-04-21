import { useEffect } from "preact/hooks";

import "../../styles/history-table.css";
import "../../styles/history-detail.css";
import "../../styles/history-adaptive.css";

import { HistoryPanel } from "./history_panel";
import type { HistoryLazyViewProps } from "./history_lazy_view";

export default function HistoryLazyViewContent(props: HistoryLazyViewProps) {
  useEffect(() => {
    props.onReady?.();
  }, [props.onReady]);

  return <HistoryPanel actions={props.view.actions} model={props.view.model} />;
}
