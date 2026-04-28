import { useEffect, useState } from "preact/hooks";
import type { FunctionComponent } from "preact";

import { uiLogger } from "../../ui_logger";
import type { HistoryPanelView } from "./history_table_view";

export interface HistoryLazyViewProps {
  active: boolean;
  onReady?(): void;
  view: HistoryPanelView;
}

type HistoryLazyViewImpl = FunctionComponent<HistoryLazyViewProps>;

let historyLazyViewPromise: Promise<HistoryLazyViewImpl> | null = null;

export function preloadHistoryLazyView(): Promise<HistoryLazyViewImpl> {
  if (historyLazyViewPromise === null) {
    historyLazyViewPromise = import("./history_lazy_view_content")
      .then((module) => module.default)
      .catch((error) => {
        historyLazyViewPromise = null;
        throw error;
      });
  }
  return historyLazyViewPromise;
}

export default function HistoryLazyView(props: HistoryLazyViewProps) {
  const [LoadedView, setLoadedView] = useState<HistoryLazyViewImpl | null>(null);

  useEffect(() => {
    if (!props.active || LoadedView !== null) {
      return;
    }
    let cancelled = false;
    void preloadHistoryLazyView()
      .then((nextLoadedView) => {
        if (!cancelled) {
          setLoadedView(() => nextLoadedView);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          uiLogger.error("[VibeSensor] Failed to load history view.", error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [LoadedView, props.active]);

  if (LoadedView === null) {
    return null;
  }

  return <LoadedView {...props} />;
}
