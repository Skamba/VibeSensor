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

type PanelHostRef<T extends HTMLElement = HTMLElement> = {
  current: T | null;
};

export interface UiPanelHostRefs {
  dashboard: {
    spectrum: PanelHostRef<HTMLDivElement>;
    liveOverview: PanelHostRef<HTMLDivElement>;
    logging: PanelHostRef<HTMLDivElement>;
  };
  history: PanelHostRef<HTMLDivElement>;
  settingsShell: PanelHostRef<HTMLDivElement>;
  settings: {
    cars: PanelHostRef<HTMLDivElement>;
    analysis: PanelHostRef<HTMLDivElement>;
    internet: PanelHostRef<HTMLDivElement>;
    update: PanelHostRef<HTMLDivElement>;
    sensors: PanelHostRef<HTMLDivElement>;
    speedSource: PanelHostRef<HTMLDivElement>;
    espFlash: PanelHostRef<HTMLDivElement>;
  };
}

function createPanelHostRef<T extends HTMLElement = HTMLDivElement>(): PanelHostRef<T> {
  return { current: null };
}

function missingElement(owner: string, target: string): never {
  throw new Error(`${owner} requires ${target}`);
}

function resolvePanelHost<T extends HTMLElement>(
  ref: PanelHostRef<T>,
  spec: PanelHostSpec,
): T {
  return ref.current ?? missingElement(spec.owner, `#${spec.id}`);
}

export function createUiPanelHostRefs(): UiPanelHostRefs {
  return {
    dashboard: {
      spectrum: createPanelHostRef(),
      liveOverview: createPanelHostRef(),
      logging: createPanelHostRef(),
    },
    history: createPanelHostRef(),
    settingsShell: createPanelHostRef(),
    settings: {
      cars: createPanelHostRef(),
      analysis: createPanelHostRef(),
      internet: createPanelHostRef(),
      update: createPanelHostRef(),
      sensors: createPanelHostRef(),
      speedSource: createPanelHostRef(),
      espFlash: createPanelHostRef(),
    },
  };
}

export function resolveUiPanelHosts(panelHostRefs: UiPanelHostRefs): UiPanelHostRegistry {
  return {
    dashboard: {
      spectrum: resolvePanelHost(panelHostRefs.dashboard.spectrum, PANEL_HOST_SPECS.dashboard.spectrum),
      liveOverview: resolvePanelHost(
        panelHostRefs.dashboard.liveOverview,
        PANEL_HOST_SPECS.dashboard.liveOverview,
      ),
      logging: resolvePanelHost(panelHostRefs.dashboard.logging, PANEL_HOST_SPECS.dashboard.logging),
    },
    history: resolvePanelHost(panelHostRefs.history, PANEL_HOST_SPECS.history),
    settingsShell: resolvePanelHost(panelHostRefs.settingsShell, PANEL_HOST_SPECS.settingsShell),
    resolveSettingsPanels() {
      return {
        cars: resolvePanelHost(panelHostRefs.settings.cars, PANEL_HOST_SPECS.settings.cars),
        analysis: resolvePanelHost(panelHostRefs.settings.analysis, PANEL_HOST_SPECS.settings.analysis),
        internet: resolvePanelHost(panelHostRefs.settings.internet, PANEL_HOST_SPECS.settings.internet),
        update: resolvePanelHost(panelHostRefs.settings.update, PANEL_HOST_SPECS.settings.update),
        sensors: resolvePanelHost(panelHostRefs.settings.sensors, PANEL_HOST_SPECS.settings.sensors),
        speedSource: resolvePanelHost(
          panelHostRefs.settings.speedSource,
          PANEL_HOST_SPECS.settings.speedSource,
        ),
        espFlash: resolvePanelHost(panelHostRefs.settings.espFlash, PANEL_HOST_SPECS.settings.espFlash),
      };
    },
  };
}
