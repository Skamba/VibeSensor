import { expect, test } from "@playwright/test";

import { getUiAnalysisPanelHost } from "../src/app/dom/analysis_dom";
import { getUiCarsPanelHost } from "../src/app/dom/cars_dom";
import { getUiEspFlashPanelHost } from "../src/app/dom/esp_flash_dom";
import { getUiHistoryPanelHost } from "../src/app/dom/history_dom";
import { getUiInternetPanelHost } from "../src/app/dom/internet_dom";
import { getUiSensorsPanelHost } from "../src/app/dom/sensors_dom";
import { getUiSettingsShellHost } from "../src/app/dom/settings_shell_dom";
import { getUiSpeedSourcePanelHost } from "../src/app/dom/speed_source_dom";
import { getUiUpdatePanelHost } from "../src/app/dom/update_dom";
import {
  getUiLiveOverviewHost,
  getUiLoggingPanelHost,
} from "../src/app/dom/realtime_dom";
import { getUiSpectrumPanelHost } from "../src/app/dom/spectrum_dom";
import { createUiRuntimeDom } from "../src/app/ui_runtime_dom";

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
      loggingPanelRoot: stubElement("loggingPanelRoot"),
      spectrumPanelRoot: stubElement("spectrumPanelRoot"),
      specChart: stubElement("specChart"),
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
      ".menu-btn": [stubElement("tab-dashboard"), stubElement("tab-history")],
      ".view": [stubElement("dashboardView"), stubElement("historyView")],
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

test("createUiRuntimeDom returns the feature-scoped startup bundle when required anchors exist", () => {
  const restore = installDomFixture();
  try {
    const dom = createUiRuntimeDom();
    expect(dom.shell.menuButtons).toHaveLength(2);
    expect(dom.spectrum.specChart.id).toBe("specChart");
  } finally {
    restore();
  }
});

test("getUiLiveOverviewHost resolves the overview island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiLiveOverviewHost().id).toBe("liveOverviewRoot");
  } finally {
    restore();
  }
});

test("getUiLoggingPanelHost resolves the logging island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiLoggingPanelHost().id).toBe("loggingPanelRoot");
  } finally {
    restore();
  }
});

test("getUiSpectrumPanelHost resolves the spectrum island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiSpectrumPanelHost().id).toBe("spectrumPanelRoot");
  } finally {
    restore();
  }
});

test("getUiHistoryPanelHost resolves the history island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiHistoryPanelHost().id).toBe("historyPanelRoot");
  } finally {
    restore();
  }
});

test("getUiSettingsShellHost resolves the settings shell island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiSettingsShellHost().id).toBe("settingsShellRoot");
  } finally {
    restore();
  }
});

test("getUiCarsPanelHost resolves the cars island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiCarsPanelHost().id).toBe("carsPanelRoot");
  } finally {
    restore();
  }
});

test("getUiAnalysisPanelHost resolves the analysis island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiAnalysisPanelHost().id).toBe("analysisPanelRoot");
  } finally {
    restore();
  }
});

test("getUiInternetPanelHost resolves the internet island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiInternetPanelHost().id).toBe("internetPanelRoot");
  } finally {
    restore();
  }
});

test("getUiUpdatePanelHost resolves the update island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiUpdatePanelHost().id).toBe("updatePanelRoot");
  } finally {
    restore();
  }
});

test("getUiEspFlashPanelHost resolves the ESP flash island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiEspFlashPanelHost().id).toBe("espFlashPanelRoot");
  } finally {
    restore();
  }
});

test("getUiSensorsPanelHost resolves the sensors island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiSensorsPanelHost().id).toBe("sensorsPanelRoot");
  } finally {
    restore();
  }
});

test("getUiSpeedSourcePanelHost resolves the speed-source island host", () => {
  const restore = installDomFixture();
  try {
    expect(getUiSpeedSourcePanelHost().id).toBe("speedSourcePanelRoot");
  } finally {
    restore();
  }
});

test.describe("createUiRuntimeDom missing required feature anchors", () => {
  test("fails at the shell boundary when menu tabs are missing", () => {
    const restore = installDomFixture({ missingSelector: ".menu-btn" });
    try {
      expect(() => createUiRuntimeDom()).toThrow("UI shell requires .menu-btn");
    } finally {
      restore();
    }
  });

  test("fails at the spectrum boundary when the chart host is missing", () => {
    const restore = installDomFixture({ missingId: "specChart" });
    try {
      expect(() => createUiRuntimeDom()).toThrow(
        "Spectrum UI requires #specChart",
      );
    } finally {
      restore();
    }
  });

  test("fails when the spectrum panel host is missing", () => {
    const restore = installDomFixture({ missingId: "spectrumPanelRoot" });
    try {
      expect(() => getUiSpectrumPanelHost()).toThrow(
        "Spectrum UI requires #spectrumPanelRoot",
      );
    } finally {
      restore();
    }
  });

  test("fails when the logging panel host is missing", () => {
    const restore = installDomFixture({ missingId: "loggingPanelRoot" });
    try {
      expect(() => getUiLoggingPanelHost()).toThrow(
        "Realtime feature requires #loggingPanelRoot",
      );
    } finally {
      restore();
    }
  });

  test("fails when the live overview host is missing", () => {
    const restore = installDomFixture({ missingId: "liveOverviewRoot" });
    try {
      expect(() => getUiLiveOverviewHost()).toThrow(
        "Realtime feature requires #liveOverviewRoot",
      );
    } finally {
      restore();
    }
  });

  test("fails when the history panel host is missing", () => {
    const restore = installDomFixture({ missingId: "historyPanelRoot" });
    try {
      expect(() => getUiHistoryPanelHost()).toThrow(
        "History feature requires #historyPanelRoot",
      );
    } finally {
      restore();
    }
  });

  test("fails when the cars panel host is missing", () => {
    const restore = installDomFixture({ missingId: "carsPanelRoot" });
    try {
      expect(() => getUiCarsPanelHost()).toThrow(
        "Cars feature requires #carsPanelRoot",
      );
    } finally {
      restore();
    }
  });

  test("fails when the analysis panel host is missing", () => {
    const restore = installDomFixture({ missingId: "analysisPanelRoot" });
    try {
      expect(() => getUiAnalysisPanelHost()).toThrow(
        "Analysis feature requires #analysisPanelRoot",
      );
    } finally {
      restore();
    }
  });

  test("fails when the internet panel host is missing", () => {
    const restore = installDomFixture({ missingId: "internetPanelRoot" });
    try {
      expect(() => getUiInternetPanelHost()).toThrow(
        "Internet settings requires #internetPanelRoot",
      );
    } finally {
      restore();
    }
  });

  test("fails when the update panel host is missing", () => {
    const restore = installDomFixture({ missingId: "updatePanelRoot" });
    try {
      expect(() => getUiUpdatePanelHost()).toThrow(
        "Update feature requires #updatePanelRoot",
      );
    } finally {
      restore();
    }
  });

  test("fails when the ESP flash panel host is missing", () => {
    const restore = installDomFixture({ missingId: "espFlashPanelRoot" });
    try {
      expect(() => getUiEspFlashPanelHost()).toThrow(
        "ESP flash feature requires #espFlashPanelRoot",
      );
    } finally {
      restore();
    }
  });

  test("fails when the settings shell host is missing", () => {
    const restore = installDomFixture({ missingId: "settingsShellRoot" });
    try {
      expect(() => getUiSettingsShellHost()).toThrow(
        "Settings shell requires #settingsShellRoot",
      );
    } finally {
      restore();
    }
  });

  test("fails when the sensors panel host is missing", () => {
    const restore = installDomFixture({ missingId: "sensorsPanelRoot" });
    try {
      expect(() => getUiSensorsPanelHost()).toThrow(
        "Sensors feature requires #sensorsPanelRoot",
      );
    } finally {
      restore();
    }
  });

  test("fails when the speed-source panel host is missing", () => {
    const restore = installDomFixture({ missingId: "speedSourcePanelRoot" });
    try {
      expect(() => getUiSpeedSourcePanelHost()).toThrow(
        "Speed source feature requires #speedSourcePanelRoot",
      );
    } finally {
      restore();
    }
  });
});
