import { expect, test } from "@playwright/test";

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
      specChart: stubElement("specChart"),
      startLoggingBtn: stubElement("startLoggingBtn"),
      historyTableBody: stubElement("historyTableBody"),
      addCarBtn: stubElement("addCarBtn"),
      addCarWizard: stubElement("addCarWizard"),
      updateStartBtn: stubElement("updateStartBtn"),
      espFlashStartBtn: stubElement("espFlashStartBtn"),
    },
    selectorOne: {
      ".wrap": stubElement("wrap"),
    },
    selectorAll: {
      ".menu-btn": [stubElement("tab-dashboard"), stubElement("tab-history")],
      ".view": [stubElement("dashboardView"), stubElement("historyView")],
      ".settings-tab": [stubElement("analysisTab"), stubElement("carTab")],
      ".settings-tab-panel": [stubElement("analysisTab"), stubElement("carTab")],
      ".wizard-step-dot": [stubElement(), stubElement(), stubElement(), stubElement(), stubElement()],
      'input[name="speedSourceRadio"]': [],
    },
  };
}

function installDomFixture(overrides: {
  missingId?: string;
  missingSelector?: string;
} = {}): () => void {
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
    expect(dom.realtime.startLoggingBtn.id).toBe("startLoggingBtn");
    expect(dom.history.historyTableBody.id).toBe("historyTableBody");
    expect(dom.settings.settingsTabs).toHaveLength(2);
    expect(dom.cars.addCarBtn.id).toBe("addCarBtn");
    expect(dom.update.updateStartBtn.id).toBe("updateStartBtn");
    expect(dom.espFlash.espFlashStartBtn.id).toBe("espFlashStartBtn");
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
      expect(() => createUiRuntimeDom()).toThrow("Spectrum UI requires #specChart");
    } finally {
      restore();
    }
  });

  test("fails at the realtime boundary when logging controls are missing", () => {
    const restore = installDomFixture({ missingId: "startLoggingBtn" });
    try {
      expect(() => createUiRuntimeDom()).toThrow("Realtime feature requires #startLoggingBtn");
    } finally {
      restore();
    }
  });

  test("fails at the history boundary when the history table is missing", () => {
    const restore = installDomFixture({ missingId: "historyTableBody" });
    try {
      expect(() => createUiRuntimeDom()).toThrow("History feature requires #historyTableBody");
    } finally {
      restore();
    }
  });

  test("fails at the settings boundary when tab controls are missing", () => {
    const restore = installDomFixture({ missingSelector: ".settings-tab" });
    try {
      expect(() => createUiRuntimeDom()).toThrow("Settings feature requires .settings-tab");
    } finally {
      restore();
    }
  });

  test("fails at the cars boundary when the add-car trigger is missing", () => {
    const restore = installDomFixture({ missingId: "addCarBtn" });
    try {
      expect(() => createUiRuntimeDom()).toThrow("Cars feature requires #addCarBtn");
    } finally {
      restore();
    }
  });

  test("fails at the update boundary when the updater trigger is missing", () => {
    const restore = installDomFixture({ missingId: "updateStartBtn" });
    try {
      expect(() => createUiRuntimeDom()).toThrow("Update feature requires #updateStartBtn");
    } finally {
      restore();
    }
  });

  test("fails at the ESP flash boundary when the flash trigger is missing", () => {
    const restore = installDomFixture({ missingId: "espFlashStartBtn" });
    try {
      expect(() => createUiRuntimeDom()).toThrow("ESP flash feature requires #espFlashStartBtn");
    } finally {
      restore();
    }
  });
});
