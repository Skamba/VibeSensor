import { expect, test } from "@playwright/test";

import { getUiShellChromeHost } from "../src/app/runtime/ui_shell_chrome";
import {
  createUiPanelHostRefs,
  resolveUiPanelHosts,
  type UiPanelHostRefs,
} from "../src/app/ui_panel_host_registry";

function stubElement(id = ""): HTMLElement {
  return {
    id,
    hidden: false,
    dataset: {},
    classList: {
      toggle() {},
      contains() {
        return false;
      },
    },
  } as unknown as HTMLElement;
}

function installDomFixture(overrides: { missingId?: string } = {}): () => void {
  const originalDocument = globalThis.document;
  const ids = new Map([["appShellChromeRoot", stubElement("appShellChromeRoot")]]);

  if (overrides.missingId) {
    ids.delete(overrides.missingId);
  }

  (globalThis as { document?: Document }).document = {
    getElementById(id: string) {
      return ids.get(id) ?? null;
    },
  } as unknown as Document;

  return () => {
    (globalThis as { document?: Document }).document = originalDocument;
  };
}

function createPanelHostRefs(overrides: { missingId?: string } = {}): UiPanelHostRefs {
  const panelHostRefs = createUiPanelHostRefs();
  if (overrides.missingId !== "spectrumPanelRoot") {
    panelHostRefs.dashboard.spectrum.current = stubElement("spectrumPanelRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "liveOverviewRoot") {
    panelHostRefs.dashboard.liveOverview.current = stubElement("liveOverviewRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "loggingPanelRoot") {
    panelHostRefs.dashboard.logging.current = stubElement("loggingPanelRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "historyPanelRoot") {
    panelHostRefs.history.current = stubElement("historyPanelRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "settingsShellRoot") {
    panelHostRefs.settingsShell.current = stubElement("settingsShellRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "carsPanelRoot") {
    panelHostRefs.settings.cars.current = stubElement("carsPanelRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "analysisPanelRoot") {
    panelHostRefs.settings.analysis.current = stubElement("analysisPanelRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "internetPanelRoot") {
    panelHostRefs.settings.internet.current = stubElement("internetPanelRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "updatePanelRoot") {
    panelHostRefs.settings.update.current = stubElement("updatePanelRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "espFlashPanelRoot") {
    panelHostRefs.settings.espFlash.current = stubElement("espFlashPanelRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "sensorsPanelRoot") {
    panelHostRefs.settings.sensors.current = stubElement("sensorsPanelRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "speedSourcePanelRoot") {
    panelHostRefs.settings.speedSource.current = stubElement("speedSourcePanelRoot") as HTMLDivElement;
  }
  return panelHostRefs;
}

const missingTopLevelPanelHostCases = [
  ["spectrumPanelRoot", "Spectrum UI requires #spectrumPanelRoot"],
  ["loggingPanelRoot", "Realtime feature requires #loggingPanelRoot"],
  ["liveOverviewRoot", "Realtime feature requires #liveOverviewRoot"],
  ["historyPanelRoot", "History feature requires #historyPanelRoot"],
  ["settingsShellRoot", "Settings shell requires #settingsShellRoot"],
] as const;

const missingSettingsPanelHostCases = [
  ["carsPanelRoot", "Cars feature requires #carsPanelRoot"],
  ["analysisPanelRoot", "Analysis feature requires #analysisPanelRoot"],
  ["internetPanelRoot", "Internet settings requires #internetPanelRoot"],
  ["updatePanelRoot", "Update feature requires #updatePanelRoot"],
  ["espFlashPanelRoot", "ESP flash feature requires #espFlashPanelRoot"],
  ["sensorsPanelRoot", "Sensors feature requires #sensorsPanelRoot"],
  ["speedSourcePanelRoot", "Speed source feature requires #speedSourcePanelRoot"],
] as const;

test("shell chrome host and panel registry resolve the startup anchors", () => {
  const restore = installDomFixture();
  try {
    expect(getUiShellChromeHost().id).toBe("appShellChromeRoot");
    const hosts = resolveUiPanelHosts(createPanelHostRefs());
    expect(hosts.dashboard.spectrum.id).toBe("spectrumPanelRoot");
    expect(hosts.dashboard.liveOverview.id).toBe("liveOverviewRoot");
    expect(hosts.dashboard.logging.id).toBe("loggingPanelRoot");
    expect(hosts.history.id).toBe("historyPanelRoot");
    expect(hosts.settingsShell.id).toBe("settingsShellRoot");
    const settingsHosts = hosts.resolveSettingsPanels();
    expect(settingsHosts.cars.id).toBe("carsPanelRoot");
    expect(settingsHosts.analysis.id).toBe("analysisPanelRoot");
    expect(settingsHosts.internet.id).toBe("internetPanelRoot");
    expect(settingsHosts.update.id).toBe("updatePanelRoot");
    expect(settingsHosts.espFlash.id).toBe("espFlashPanelRoot");
    expect(settingsHosts.sensors.id).toBe("sensorsPanelRoot");
    expect(settingsHosts.speedSource.id).toBe("speedSourcePanelRoot");
  } finally {
    restore();
  }
});

test.describe("runtime locator missing required feature anchors", () => {
  test("fails at the shell boundary when the chrome host is missing", () => {
    const restore = installDomFixture({ missingId: "appShellChromeRoot" });
    try {
      expect(() => getUiShellChromeHost()).toThrow(
        "UI shell requires #appShellChromeRoot",
      );
    } finally {
      restore();
    }
  });

  for (const [missingId, message] of missingTopLevelPanelHostCases) {
    test(`fails when ${missingId} is missing from the top-level panel registry`, () => {
      const restore = installDomFixture();
      try {
        expect(() => resolveUiPanelHosts(createPanelHostRefs({ missingId }))).toThrow(message);
      } finally {
        restore();
      }
    });
  }

  for (const [missingId, message] of missingSettingsPanelHostCases) {
    test(`fails when ${missingId} is missing from the settings panel registry`, () => {
      const restore = installDomFixture();
      try {
        expect(() => resolveUiPanelHosts(createPanelHostRefs({ missingId })).resolveSettingsPanels()).toThrow(
          message,
        );
      } finally {
        restore();
      }
    });
  }
});
