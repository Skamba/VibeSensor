import { describe, expect, test } from "vitest";
import { getUiShellChromeHost } from "../src/app/runtime/ui_shell_chrome";
import {
  createUiSettingsPanelHostRefs,
  resolveUiSettingsPanelHosts,
  type UiSettingsPanelHostRefs,
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
  const ids = new Map([
    ["appShellChromeRoot", stubElement("appShellChromeRoot")],
  ]);

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

function createSettingsPanelHostRefs(
  overrides: { missingId?: string } = {},
): UiSettingsPanelHostRefs {
  const panelHostRefs = createUiSettingsPanelHostRefs();
  if (overrides.missingId !== "carsPanelRoot") {
    panelHostRefs.cars.current = stubElement("carsPanelRoot") as HTMLDivElement;
  }
  if (overrides.missingId !== "analysisPanelRoot") {
    panelHostRefs.analysis.current = stubElement(
      "analysisPanelRoot",
    ) as HTMLDivElement;
  }
  if (overrides.missingId !== "internetPanelRoot") {
    panelHostRefs.internet.current = stubElement(
      "internetPanelRoot",
    ) as HTMLDivElement;
  }
  if (overrides.missingId !== "updatePanelRoot") {
    panelHostRefs.update.current = stubElement(
      "updatePanelRoot",
    ) as HTMLDivElement;
  }
  if (overrides.missingId !== "espFlashPanelRoot") {
    panelHostRefs.espFlash.current = stubElement(
      "espFlashPanelRoot",
    ) as HTMLDivElement;
  }
  if (overrides.missingId !== "sensorsPanelRoot") {
    panelHostRefs.sensors.current = stubElement(
      "sensorsPanelRoot",
    ) as HTMLDivElement;
  }
  if (overrides.missingId !== "speedSourcePanelRoot") {
    panelHostRefs.speedSource.current = stubElement(
      "speedSourcePanelRoot",
    ) as HTMLDivElement;
  }
  return panelHostRefs;
}

const missingSettingsPanelHostCases = [
  ["carsPanelRoot", "Cars feature requires #carsPanelRoot"],
  ["analysisPanelRoot", "Analysis feature requires #analysisPanelRoot"],
  ["internetPanelRoot", "Internet settings requires #internetPanelRoot"],
  ["updatePanelRoot", "Update feature requires #updatePanelRoot"],
  ["espFlashPanelRoot", "ESP flash feature requires #espFlashPanelRoot"],
  ["sensorsPanelRoot", "Sensors feature requires #sensorsPanelRoot"],
  [
    "speedSourcePanelRoot",
    "Speed source feature requires #speedSourcePanelRoot",
  ],
] as const;

test("shell chrome host and panel registry resolve the startup anchors", () => {
  const restore = installDomFixture();
  try {
    expect(getUiShellChromeHost().id).toBe("appShellChromeRoot");
    const settingsHosts = resolveUiSettingsPanelHosts(
      createSettingsPanelHostRefs(),
    );
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

describe("runtime locator missing required feature anchors", () => {
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

  for (const [missingId, message] of missingSettingsPanelHostCases) {
    test(`fails when ${missingId} is missing from the settings panel registry`, () => {
      const restore = installDomFixture();
      try {
        expect(() =>
          resolveUiSettingsPanelHosts(
            createSettingsPanelHostRefs({ missingId }),
          ),
        ).toThrow(message);
      } finally {
        restore();
      }
    });
  }
});
