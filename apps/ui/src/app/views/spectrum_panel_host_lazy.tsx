import { useEffect, useState } from "preact/hooks";
import type { FunctionComponent } from "preact";

import { uiLogger } from "../../ui_logger";
import type { CreatedSpectrumPanel } from "./spectrum_panel";

export interface SpectrumPanelHostLazyProps {
  active: boolean;
  panel: CreatedSpectrumPanel;
}

type SpectrumPanelHostImpl = FunctionComponent<SpectrumPanelHostLazyProps>;

let spectrumPanelHostPromise: Promise<SpectrumPanelHostImpl> | null = null;

export function preloadSpectrumPanelHost(): Promise<SpectrumPanelHostImpl> {
  if (spectrumPanelHostPromise === null) {
    spectrumPanelHostPromise = import("./spectrum_panel_host")
      .then((module) => module.SpectrumPanelHost as SpectrumPanelHostImpl)
      .catch((error) => {
        spectrumPanelHostPromise = null;
        throw error;
      });
  }
  return spectrumPanelHostPromise;
}

export default function SpectrumPanelHostLazy(props: SpectrumPanelHostLazyProps) {
  const [LoadedPanelHost, setLoadedPanelHost] = useState<SpectrumPanelHostImpl | null>(null);

  useEffect(() => {
    if (!props.active || LoadedPanelHost !== null) {
      return;
    }
    let cancelled = false;
    void preloadSpectrumPanelHost()
      .then((nextLoadedPanelHost) => {
        if (!cancelled) {
          setLoadedPanelHost(() => nextLoadedPanelHost);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          uiLogger.error("[VibeSensor] Failed to load spectrum panel host.", error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [LoadedPanelHost, props.active]);

  if (LoadedPanelHost === null) {
    return null;
  }

  return <LoadedPanelHost {...props} />;
}
