import { useEffect, useState } from "preact/hooks";
import type { FunctionComponent } from "preact";

import { uiLogger } from "../../ui_logger";
import type { RealtimeLiveOverviewBridge } from "./realtime_live_overview";

export interface RealtimeLiveOverviewLazyProps {
  active: boolean;
  view: RealtimeLiveOverviewBridge;
}

type RealtimeLiveOverviewPanelImpl = FunctionComponent<RealtimeLiveOverviewLazyProps>;

let realtimeLiveOverviewPromise: Promise<RealtimeLiveOverviewPanelImpl> | null = null;

export function preloadRealtimeLiveOverviewPanel(): Promise<RealtimeLiveOverviewPanelImpl> {
  if (realtimeLiveOverviewPromise === null) {
    realtimeLiveOverviewPromise = import("./realtime_live_overview")
      .then((module) => module.RealtimeLiveOverviewPanel as RealtimeLiveOverviewPanelImpl)
      .catch((error) => {
        realtimeLiveOverviewPromise = null;
        throw error;
      });
  }
  return realtimeLiveOverviewPromise;
}

export default function RealtimeLiveOverviewLazy(
  props: RealtimeLiveOverviewLazyProps,
) {
  const [LoadedPanel, setLoadedPanel] = useState<RealtimeLiveOverviewPanelImpl | null>(null);

  useEffect(() => {
    if (!props.active || LoadedPanel !== null) {
      return;
    }
    let cancelled = false;
    void preloadRealtimeLiveOverviewPanel()
      .then((nextLoadedPanel) => {
        if (!cancelled) {
          setLoadedPanel(() => nextLoadedPanel);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          uiLogger.error("[VibeSensor] Failed to load live overview panel.", error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [LoadedPanel, props.active]);

  if (LoadedPanel === null) {
    return null;
  }

  return <LoadedPanel {...props} />;
}
