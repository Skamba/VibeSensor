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
} as const;

const SETTINGS_PANEL_HOST_SPECS = {
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
} as const;

export interface UiPanelHostRegistry {
  dashboard: {
    spectrum: HTMLElement;
    liveOverview: HTMLElement;
    logging: HTMLElement;
  };
  history: HTMLElement;
  settingsShell: HTMLElement;
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
}

export interface UiSettingsPanelHostRefs {
  cars: PanelHostRef<HTMLDivElement>;
  analysis: PanelHostRef<HTMLDivElement>;
  internet: PanelHostRef<HTMLDivElement>;
  update: PanelHostRef<HTMLDivElement>;
  sensors: PanelHostRef<HTMLDivElement>;
  speedSource: PanelHostRef<HTMLDivElement>;
  espFlash: PanelHostRef<HTMLDivElement>;
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
  };
}

export function createUiSettingsPanelHostRefs(): UiSettingsPanelHostRefs {
  return {
    cars: createPanelHostRef(),
    analysis: createPanelHostRef(),
    internet: createPanelHostRef(),
    update: createPanelHostRef(),
    sensors: createPanelHostRef(),
    speedSource: createPanelHostRef(),
    espFlash: createPanelHostRef(),
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
  };
}

export function resolveUiSettingsPanelHosts(
  panelHostRefs: UiSettingsPanelHostRefs,
): UiSettingsPanelHostRegistry {
  return {
    cars: resolvePanelHost(panelHostRefs.cars, SETTINGS_PANEL_HOST_SPECS.cars),
    analysis: resolvePanelHost(panelHostRefs.analysis, SETTINGS_PANEL_HOST_SPECS.analysis),
    internet: resolvePanelHost(panelHostRefs.internet, SETTINGS_PANEL_HOST_SPECS.internet),
    update: resolvePanelHost(panelHostRefs.update, SETTINGS_PANEL_HOST_SPECS.update),
    sensors: resolvePanelHost(panelHostRefs.sensors, SETTINGS_PANEL_HOST_SPECS.sensors),
    speedSource: resolvePanelHost(panelHostRefs.speedSource, SETTINGS_PANEL_HOST_SPECS.speedSource),
    espFlash: resolvePanelHost(panelHostRefs.espFlash, SETTINGS_PANEL_HOST_SPECS.espFlash),
  };
}
