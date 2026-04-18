export interface UiSettingsPanelHostRegistry {
  cars: HTMLElement;
  analysis: HTMLElement;
  internet: HTMLElement;
  update: HTMLElement;
  sensors: HTMLElement;
  speedSource: HTMLElement;
  espFlash: HTMLElement;
}

type UiSettingsPanelHostRef<T extends HTMLElement = HTMLElement> = {
  current: T | null;
};

export interface UiSettingsPanelHostRefs {
  cars: UiSettingsPanelHostRef<HTMLDivElement>;
  analysis: UiSettingsPanelHostRef<HTMLDivElement>;
  internet: UiSettingsPanelHostRef<HTMLDivElement>;
  update: UiSettingsPanelHostRef<HTMLDivElement>;
  sensors: UiSettingsPanelHostRef<HTMLDivElement>;
  speedSource: UiSettingsPanelHostRef<HTMLDivElement>;
  espFlash: UiSettingsPanelHostRef<HTMLDivElement>;
}

function missingElement(message: string): never {
  throw new Error(message);
}

export function createUiSettingsPanelHostRefs(): UiSettingsPanelHostRefs {
  return {
    cars: { current: null },
    analysis: { current: null },
    internet: { current: null },
    update: { current: null },
    sensors: { current: null },
    speedSource: { current: null },
    espFlash: { current: null },
  };
}

export function resolveUiSettingsPanelHosts(
  panelHostRefs: UiSettingsPanelHostRefs,
): UiSettingsPanelHostRegistry {
  return {
    cars:
      panelHostRefs.cars.current ??
      missingElement("Cars feature requires #carsPanelRoot"),
    analysis:
      panelHostRefs.analysis.current ??
      missingElement("Analysis feature requires #analysisPanelRoot"),
    internet:
      panelHostRefs.internet.current ??
      missingElement("Internet settings requires #internetPanelRoot"),
    update:
      panelHostRefs.update.current ??
      missingElement("Update feature requires #updatePanelRoot"),
    sensors:
      panelHostRefs.sensors.current ??
      missingElement("Sensors feature requires #sensorsPanelRoot"),
    speedSource:
      panelHostRefs.speedSource.current ??
      missingElement("Speed source feature requires #speedSourcePanelRoot"),
    espFlash:
      panelHostRefs.espFlash.current ??
      missingElement("ESP flash feature requires #espFlashPanelRoot"),
  };
}
