import { render } from "preact";
import { useEffect, useRef } from "preact/hooks";

import {
  mountAnalysisPanel,
  type AnalysisPanelView,
} from "./analysis_panel";
import {
  mountCarsPanel,
  type CarsPanelView,
} from "./cars_panel";
import {
  mountEspFlashPanel,
  type EspFlashPanelView,
} from "./esp_flash_panel";
import {
  mountInternetPanel,
  type InternetPanelView,
} from "./internet_panel";
import {
  mountSensorsPanel,
  type SensorsPanelView,
} from "./sensors_panel";
import {
  mountSettingsShell,
  type SettingsShellView,
} from "./settings_shell";
import {
  mountSpeedSourcePanel,
  type SpeedSourcePanelView,
} from "./speed_source_panel";
import {
  mountUpdatePanel,
  type UpdatePanelView,
} from "./update_panel";

interface SettingsLazyViewReadyHandles {
  settingsShell: SettingsShellView;
  settings: {
    analysis: Pick<AnalysisPanelView, "focusField" | "openGuidance">;
    cars: Pick<CarsPanelView["wizard"], "focus">;
    internet: Pick<InternetPanelView, "focusSsidInput">;
    speedSource: Pick<
      SpeedSourcePanelView,
      "focusManualSpeedInput" | "focusScanObdDevices" | "focusStaleTimeoutInput" | "isObdConfigVisible"
    >;
  };
}

export interface SettingsLazyViewProps {
  onReady(handles: SettingsLazyViewReadyHandles): void;
  panels: {
    settings: {
      analysis: AnalysisPanelView;
      cars: CarsPanelView;
      espFlash: EspFlashPanelView;
      internet: InternetPanelView;
      sensors: SensorsPanelView;
      speedSource: SpeedSourcePanelView;
      update: UpdatePanelView;
    };
  };
}

export default function SettingsLazyView(props: SettingsLazyViewProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) {
      return;
    }

    const settingsShellMount = mountSettingsShell(host);
    const settingsShell = settingsShellMount.view;
    const settingsHosts = settingsShellMount.panelHosts;
    const cars = mountCarsPanel(settingsHosts.cars, props.panels.settings.cars);
    const analysis = mountAnalysisPanel(settingsHosts.analysis, props.panels.settings.analysis);
    const internet = mountInternetPanel(settingsHosts.internet, props.panels.settings.internet);
    mountUpdatePanel(settingsHosts.update, props.panels.settings.update);
    mountSensorsPanel(settingsHosts.sensors, props.panels.settings.sensors);
    const speedSource = mountSpeedSourcePanel(
      settingsHosts.speedSource,
      props.panels.settings.speedSource,
    );
    mountEspFlashPanel(settingsHosts.espFlash, props.panels.settings.espFlash);
    props.onReady({
      settingsShell,
      settings: {
        analysis,
        cars,
        internet,
        speedSource,
      },
    });

    return () => {
      render(null, host);
    };
  }, [props.onReady, props.panels]);

  return <div ref={hostRef} />;
}
