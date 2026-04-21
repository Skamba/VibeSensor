import { useEffect, useState } from "preact/hooks";
import type { FunctionComponent } from "preact";

import type { AnalysisPanelView } from "./analysis_panel";
import type { CarsPanelView } from "./cars_panel";
import type { EspFlashPanelView } from "./esp_flash_panel";
import type { InternetPanelView } from "./internet_panel";
import type { SensorsPanelView } from "./sensors_panel";
import type { SettingsShellView } from "./settings_shell";
import type { SpeedSourcePanelView } from "./speed_source_panel";
import type { UpdatePanelView } from "./update_panel";

interface SettingsLazyViewReadyHandles {
  settingsShell: SettingsShellView;
  settings: {
    analysis: Pick<AnalysisPanelView, "focusField" | "openGuidance">;
    cars: Pick<CarsPanelView["wizard"], "focus">;
    internet: Pick<InternetPanelView, "focusSsidInput">;
    speedSource: Pick<
      SpeedSourcePanelView,
      "focusManualSpeedInput" | "focusScanObdDevices" | "focusStaleTimeoutInput"
    >;
  };
}

export interface SettingsLazyViewProps {
  active: boolean;
  onReady(handles: SettingsLazyViewReadyHandles): void;
  settings: {
    analysis: AnalysisPanelView;
    cars: CarsPanelView;
    espFlash: EspFlashPanelView;
    internet: InternetPanelView;
    sensors: SensorsPanelView;
    speedSource: SpeedSourcePanelView;
    update: UpdatePanelView;
  };
}

type SettingsLazyViewImpl = FunctionComponent<SettingsLazyViewProps>;

let settingsLazyViewPromise: Promise<SettingsLazyViewImpl> | null = null;

function loadSettingsLazyView(): Promise<SettingsLazyViewImpl> {
  if (settingsLazyViewPromise === null) {
    settingsLazyViewPromise = import("./settings_lazy_view_content")
      .then((module) => module.default)
      .catch((error) => {
        settingsLazyViewPromise = null;
        throw error;
      });
  }
  return settingsLazyViewPromise;
}

export default function SettingsLazyView(props: SettingsLazyViewProps) {
  const [LoadedView, setLoadedView] = useState<SettingsLazyViewImpl | null>(null);

  useEffect(() => {
    if (!props.active || LoadedView !== null) {
      return;
    }
    let cancelled = false;
    void loadSettingsLazyView()
      .then((nextLoadedView) => {
        if (!cancelled) {
          setLoadedView(() => nextLoadedView);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error("[VibeSensor] Failed to load settings view.", error);
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
