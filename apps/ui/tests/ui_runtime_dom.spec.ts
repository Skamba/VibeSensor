import { expect, test } from "@playwright/test";

import { getUiShellChromeHost } from "../src/app/runtime/ui_shell_chrome";
import { resolveUiPanelHosts } from "../src/app/ui_panel_host_registry";

type SelectorFixture = {
  ids?: Record<string, HTMLElement>;
  selectorOne?: Record<string, Element | null>;
  selectorAll?: Record<string, Element[]>;
};

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

function createBaseFixture(): SelectorFixture {
  return {
    ids: {
      appShellChromeRoot: stubElement("appShellChromeRoot"),
      loggingPanelRoot: stubElement("loggingPanelRoot"),
      spectrumPanelRoot: stubElement("spectrumPanelRoot"),
      liveOverviewRoot: stubElement("liveOverviewRoot"),
      historyPanelRoot: stubElement("historyPanelRoot"),
      settingsShellRoot: stubElement("settingsShellRoot"),
      carsPanelRoot: stubElement("carsPanelRoot"),
      analysisPanelRoot: stubElement("analysisPanelRoot"),
      internetPanelRoot: stubElement("internetPanelRoot"),
      updatePanelRoot: stubElement("updatePanelRoot"),
      espFlashPanelRoot: stubElement("espFlashPanelRoot"),
      sensorsPanelRoot: stubElement("sensorsPanelRoot"),
      speedSourcePanelRoot: stubElement("speedSourcePanelRoot"),
    },
    selectorOne: {
      ".wrap": stubElement("wrap"),
    },
    selectorAll: {
      ".wizard-step-dot": [
        stubElement(),
        stubElement(),
        stubElement(),
        stubElement(),
        stubElement(),
      ],
      'input[name="speedSourceRadio"]': [],
    },
  };
}

function installDomFixture(
  overrides: { missingId?: string; missingSelector?: string } = {},
): () => void {
  const originalDocument = globalThis.document;
  const fixture = createBaseFixture();
  const ids = new Map(Object.entries(fixture.ids ?? {}));
  const selectorOne = new Map(Object.entries(fixture.selectorOne ?? {}));
  const selectorAll = new Map(Object.entries(fixture.selectorAll ?? {}));

  if (overrides.missingId) {
    ids.delete(overrides.missingId);
  }
  if (overrides.missingSelector) {
    selectorOne.delete(overrides.missingSelector);
    selectorAll.delete(overrides.missingSelector);
  }

  (globalThis as { document?: Document }).document = {
    getElementById(id: string) {
      return ids.get(id) ?? null;
    },
    querySelector(selector: string) {
      return selectorOne.get(selector) ?? null;
    },
    querySelectorAll(selector: string) {
      return selectorAll.get(selector) ?? [];
    },
  } as unknown as Document;

  return () => {
    (globalThis as { document?: Document }).document = originalDocument;
  };
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
    const hosts = resolveUiPanelHosts();
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
      const restore = installDomFixture({ missingId });
      try {
        expect(() => resolveUiPanelHosts()).toThrow(message);
      } finally {
        restore();
      }
    });
  }

  for (const [missingId, message] of missingSettingsPanelHostCases) {
    test(`fails when ${missingId} is missing from the settings panel registry`, () => {
      const restore = installDomFixture({ missingId });
      try {
        expect(() => resolveUiPanelHosts().resolveSettingsPanels()).toThrow(
          message,
        );
      } finally {
        restore();
      }
    });
  }
});
