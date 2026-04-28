import { useEffect, useState } from "preact/hooks";
import type { FunctionComponent } from "preact";

import { uiLogger } from "../../ui_logger";
import type { RealtimeLoggingPanelBridge } from "./realtime_logging_panel";

export interface RealtimeLoggingPanelLazyProps {
  active: boolean;
  view: RealtimeLoggingPanelBridge;
}

type RealtimeLoggingPanelImpl = FunctionComponent<RealtimeLoggingPanelLazyProps>;

let realtimeLoggingPanelPromise: Promise<RealtimeLoggingPanelImpl> | null = null;

export function preloadRealtimeLoggingPanel(): Promise<RealtimeLoggingPanelImpl> {
  if (realtimeLoggingPanelPromise === null) {
    realtimeLoggingPanelPromise = import("./realtime_logging_panel")
      .then((module) => module.RealtimeLoggingPanelView as RealtimeLoggingPanelImpl)
      .catch((error) => {
        realtimeLoggingPanelPromise = null;
        throw error;
      });
  }
  return realtimeLoggingPanelPromise;
}

export default function RealtimeLoggingPanelLazy(
  props: RealtimeLoggingPanelLazyProps,
) {
  const [LoadedPanel, setLoadedPanel] = useState<RealtimeLoggingPanelImpl | null>(null);

  useEffect(() => {
    if (!props.active || LoadedPanel !== null) {
      return;
    }
    let cancelled = false;
    void preloadRealtimeLoggingPanel()
      .then((nextLoadedPanel) => {
        if (!cancelled) {
          setLoadedPanel(() => nextLoadedPanel);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          uiLogger.error("[VibeSensor] Failed to load realtime logging panel.", error);
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
