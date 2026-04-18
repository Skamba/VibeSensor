import { render } from "preact";
import { useEffect, useRef } from "preact/hooks";

import "../../styles/maintenance-cards.css";
import "../../styles/maintenance-readiness.css";
import "../../styles/maintenance-journey.css";
import "../../styles/maintenance-details.css";
import "../../styles/maintenance-layout.css";
import "../../styles/settings-common.css";
import "../../styles/settings-shell.css";
import "../../styles/settings-transport.css";
import "../../styles/settings-speed-source.css";
import "../../styles/settings-cars.css";
import "../../styles/settings-sensors.css";
import "../../styles/settings-cars-wizard.css";
import "../../styles/settings-adaptive.css";

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
      "focusManualSpeedInput" | "focusScanObdDevices" | "focusStaleTimeoutInput"
    >;
  };
}

export interface SettingsLazyViewProps {
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
    const cars = mountCarsPanel(settingsHosts.cars, props.settings.cars);
    const analysis = mountAnalysisPanel(settingsHosts.analysis, props.settings.analysis);
    const internet = mountInternetPanel(settingsHosts.internet, props.settings.internet);
    mountUpdatePanel(settingsHosts.update, props.settings.update);
    mountSensorsPanel(settingsHosts.sensors, props.settings.sensors);
    const speedSource = mountSpeedSourcePanel(
      settingsHosts.speedSource,
      props.settings.speedSource,
    );
    mountEspFlashPanel(settingsHosts.espFlash, props.settings.espFlash);
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
  }, [props.onReady, props.settings]);

  return <div ref={hostRef} />;
}
