import { requiredById } from "./dom/dom_query";

type PanelHostSpec = {
  id: string;
  owner: string;
};

const PANEL_HOST_SPECS = {
  dashboard: {
    spectrum: {
      id: "spectrumPanelRoot",
      owner: "Spectrum UI",
    },
    liveOverview: {
      id: "liveOverviewRoot",
      owner: "Realtime feature",
    },
    logging: {
      id: "loggingPanelRoot",
      owner: "Realtime feature",
    },
  },
  history: {
    id: "historyPanelRoot",
    owner: "History feature",
  },
  settingsShell: {
    id: "settingsShellRoot",
    owner: "Settings shell",
  },
  settings: {
    cars: {
      id: "carsPanelRoot",
      owner: "Cars feature",
    },
    analysis: {
      id: "analysisPanelRoot",
      owner: "Analysis feature",
    },
    internet: {
      id: "internetPanelRoot",
      owner: "Internet settings",
    },
    update: {
      id: "updatePanelRoot",
      owner: "Update feature",
    },
    sensors: {
      id: "sensorsPanelRoot",
      owner: "Sensors feature",
    },
    speedSource: {
      id: "speedSourcePanelRoot",
      owner: "Speed source feature",
    },
    espFlash: {
      id: "espFlashPanelRoot",
      owner: "ESP flash feature",
    },
  },
} as const;

export interface UiPanelHostRegistry {
  dashboard: {
    spectrum: HTMLElement;
    liveOverview: HTMLElement;
    logging: HTMLElement;
  };
  history: HTMLElement;
  settingsShell: HTMLElement;
  resolveSettingsPanels(): UiSettingsPanelHostRegistry;
}

export interface UiSettingsPanelHostRegistry {
  cars: HTMLElement;
  analysis: HTMLElement;
  internet: HTMLElement;
  update: HTMLElement;
  sensors: HTMLElement;
  speedSource: HTMLElement;
  espFlash: HTMLElement;
}

function resolvePanelHost(spec: PanelHostSpec): HTMLElement {
  return requiredById<HTMLElement>(spec.id, spec.owner);
}

export function resolveUiPanelHosts(): UiPanelHostRegistry {
  return {
    dashboard: {
      spectrum: resolvePanelHost(PANEL_HOST_SPECS.dashboard.spectrum),
      liveOverview: resolvePanelHost(PANEL_HOST_SPECS.dashboard.liveOverview),
      logging: resolvePanelHost(PANEL_HOST_SPECS.dashboard.logging),
    },
    history: resolvePanelHost(PANEL_HOST_SPECS.history),
    settingsShell: resolvePanelHost(PANEL_HOST_SPECS.settingsShell),
    resolveSettingsPanels() {
      return {
        cars: resolvePanelHost(PANEL_HOST_SPECS.settings.cars),
        analysis: resolvePanelHost(PANEL_HOST_SPECS.settings.analysis),
        internet: resolvePanelHost(PANEL_HOST_SPECS.settings.internet),
        update: resolvePanelHost(PANEL_HOST_SPECS.settings.update),
        sensors: resolvePanelHost(PANEL_HOST_SPECS.settings.sensors),
        speedSource: resolvePanelHost(PANEL_HOST_SPECS.settings.speedSource),
        espFlash: resolvePanelHost(PANEL_HOST_SPECS.settings.espFlash),
      };
    },
  };
}
