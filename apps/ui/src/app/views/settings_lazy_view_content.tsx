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

import { mountAnalysisPanel } from "./analysis_panel";
import { mountCarsPanel } from "./cars_panel";
import { mountEspFlashPanel } from "./esp_flash_panel";
import { mountInternetPanel } from "./internet_panel";
import { mountSensorsPanel } from "./sensors_panel";
import { mountSettingsShell } from "./settings_shell";
import { mountSpeedSourcePanel } from "./speed_source_panel";
import { mountUpdatePanel } from "./update_panel";
import type { SettingsLazyViewProps } from "./settings_lazy_view";

export default function SettingsLazyViewContent(props: SettingsLazyViewProps) {
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
