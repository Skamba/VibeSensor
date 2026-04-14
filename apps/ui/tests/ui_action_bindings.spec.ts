import { expect, test } from "@playwright/test";

import { bindCarsFeatureInteractions } from "../src/app/views/cars_feature_bindings";
import { bindHistoryTableInteractions } from "../src/app/views/history_table_view";
import { bindRealtimeFeatureInteractions } from "../src/app/views/realtime_feature_bindings";
import { bindSettingsCarListActions } from "../src/app/views/settings_car_list_view";
import {
  bindSettingsSpeedSourceInteractions,
  type SettingsSpeedSourceInteraction,
} from "../src/app/views/settings_speed_source_bindings";

type ElementGlobals = {
  Element?: typeof Element;
  HTMLElement?: typeof HTMLElement;
  HTMLButtonElement?: typeof HTMLButtonElement;
  HTMLSelectElement?: typeof HTMLSelectElement;
  HTMLInputElement?: typeof HTMLInputElement;
};

type Listener = EventListenerOrEventListenerObject;

type FakeDispatchedEvent = {
  type: string;
  target: EventTarget | null;
  key?: string;
  defaultPrevented: boolean;
  propagationStopped: boolean;
  preventDefault(): void;
  stopPropagation(): void;
};

class FakeClassList {
  readonly #tokens = new Set<string>();

  add(...tokens: string[]): void {
    for (const token of tokens) {
      this.#tokens.add(token);
    }
  }

  remove(...tokens: string[]): void {
    for (const token of tokens) {
      this.#tokens.delete(token);
    }
  }

  contains(token: string): boolean {
    return this.#tokens.has(token);
  }
}

class FakeElement {
  parentElement: FakeElement | null = null;
  dataset: Record<string, string> = {};
  classList = new FakeClassList();

  readonly #attributes = new Map<string, string>();
  readonly #listeners = new Map<string, Listener[]>();

  constructor(readonly tagName = "div") {}

  addEventListener(type: string, listener: Listener): void {
    const listeners = this.#listeners.get(type) ?? [];
    listeners.push(listener);
    this.#listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: Listener): void {
    const listeners = this.#listeners.get(type) ?? [];
    this.#listeners.set(type, listeners.filter((candidate) => candidate !== listener));
  }

  dispatch(type: string, options: Partial<Omit<FakeDispatchedEvent, "type">> = {}): FakeDispatchedEvent {
    const event: FakeDispatchedEvent = {
      type,
      target: options.target ?? (this as unknown as EventTarget),
      key: options.key,
      defaultPrevented: false,
      propagationStopped: false,
      preventDefault() {
        this.defaultPrevented = true;
      },
      stopPropagation() {
        this.propagationStopped = true;
      },
    };
    for (const listener of this.#listeners.get(type) ?? []) {
      if (typeof listener === "function") {
        listener(event as unknown as Event);
        continue;
      }
      listener.handleEvent(event as unknown as Event);
    }
    return event;
  }

  setAttribute(name: string, value: string): void {
    this.#attributes.set(name, value);
    if (name.startsWith("data-")) {
      this.dataset[dataAttributeToDatasetKey(name)] = value;
    }
  }

  getAttribute(name: string): string | null {
    return this.#attributes.get(name) ?? null;
  }

  removeAttribute(name: string): void {
    this.#attributes.delete(name);
    if (name.startsWith("data-")) {
      delete this.dataset[dataAttributeToDatasetKey(name)];
    }
  }

  closest<T extends Element>(selector: string): T | null {
    let current: FakeElement | null = this;
    while (current) {
      if (current.matches(selector)) {
        return current as unknown as T;
      }
      current = current.parentElement;
    }
    return null;
  }

  matches(selector: string): boolean {
    return selector.split(",").some((candidate) => this.matchesSingleSelector(candidate.trim()));
  }

  private matchesSingleSelector(selector: string): boolean {
    if (!selector) {
      return false;
    }
    let remainder = selector;
    const tagMatch = remainder.match(/^[a-zA-Z][\w-]*/);
    if (tagMatch) {
      if (this.tagName.toLowerCase() !== tagMatch[0].toLowerCase()) {
        return false;
      }
      remainder = remainder.slice(tagMatch[0].length);
    }
    for (const classMatch of remainder.matchAll(/\.([A-Za-z0-9_-]+)/g)) {
      if (!this.classList.contains(classMatch[1])) {
        return false;
      }
    }
    for (const attrMatch of remainder.matchAll(/\[([^=\]]+)(?:="([^"]*)")?\]/g)) {
      const attrName = attrMatch[1];
      const attrValue = attrMatch[2];
      const actual = this.getAttribute(attrName);
      if (actual === null) {
        return false;
      }
      if (attrValue !== undefined && actual !== attrValue) {
        return false;
      }
    }
    return true;
  }
}

class FakeHTMLElement extends FakeElement {}

class FakeHTMLButtonElement extends FakeHTMLElement {
  constructor() {
    super("button");
  }

  click(): void {
    this.dispatch("click");
  }
}

class FakeHTMLSelectElement extends FakeHTMLElement {
  value = "";

  constructor() {
    super("select");
  }
}

class FakeHTMLInputElement extends FakeHTMLElement {
  value = "";

  constructor() {
    super("input");
  }
}

function dataAttributeToDatasetKey(name: string): string {
  return name
    .slice("data-".length)
    .replace(/-([a-z])/g, (_, char: string) => char.toUpperCase());
}

function installFakeDomGlobals(): () => void {
  const globalRef = globalThis as typeof globalThis & ElementGlobals;
  const originals: ElementGlobals = {
    Element: globalRef.Element,
    HTMLElement: globalRef.HTMLElement,
    HTMLButtonElement: globalRef.HTMLButtonElement,
    HTMLSelectElement: globalRef.HTMLSelectElement,
    HTMLInputElement: globalRef.HTMLInputElement,
  };
  globalRef.Element = FakeElement as unknown as typeof Element;
  globalRef.HTMLElement = FakeHTMLElement as unknown as typeof HTMLElement;
  globalRef.HTMLButtonElement = FakeHTMLButtonElement as unknown as typeof HTMLButtonElement;
  globalRef.HTMLSelectElement = FakeHTMLSelectElement as unknown as typeof HTMLSelectElement;
  globalRef.HTMLInputElement = FakeHTMLInputElement as unknown as typeof HTMLInputElement;
  return () => {
    restoreGlobal(globalRef, "Element", originals.Element);
    restoreGlobal(globalRef, "HTMLElement", originals.HTMLElement);
    restoreGlobal(globalRef, "HTMLButtonElement", originals.HTMLButtonElement);
    restoreGlobal(globalRef, "HTMLSelectElement", originals.HTMLSelectElement);
    restoreGlobal(globalRef, "HTMLInputElement", originals.HTMLInputElement);
  };
}

function restoreGlobal<K extends keyof ElementGlobals>(
  globalRef: typeof globalThis & ElementGlobals,
  key: K,
  value: ElementGlobals[K],
): void {
  if (value) {
    globalRef[key] = value;
    return;
  }
  delete globalRef[key];
}

function appendChild<TChild extends FakeElement>(parent: FakeElement, child: TChild): TChild {
  child.parentElement = parent;
  return child;
}

function createButton(options: {
  classes?: string[];
  attrs?: Record<string, string>;
} = {}): FakeHTMLButtonElement {
  const button = new FakeHTMLButtonElement();
  for (const token of options.classes ?? []) {
    button.classList.add(token);
  }
  for (const [name, value] of Object.entries(options.attrs ?? {})) {
    button.setAttribute(name, value);
  }
  return button;
}

function createContainer(tagName = "div"): FakeHTMLElement {
  return new FakeHTMLElement(tagName);
}

function createSelect(options: {
  classes?: string[];
  attrs?: Record<string, string>;
  value?: string;
} = {}): FakeHTMLSelectElement {
  const select = new FakeHTMLSelectElement();
  select.value = options.value ?? "";
  for (const token of options.classes ?? []) {
    select.classList.add(token);
  }
  for (const [name, value] of Object.entries(options.attrs ?? {})) {
    select.setAttribute(name, value);
  }
  return select;
}

function createInput(options: {
  attrs?: Record<string, string>;
  value?: string;
} = {}): FakeHTMLInputElement {
  const input = new FakeHTMLInputElement();
  input.value = options.value ?? "";
  for (const [name, value] of Object.entries(options.attrs ?? {})) {
    input.setAttribute(name, value);
  }
  return input;
}

let restoreDomGlobals = () => undefined;

test.beforeEach(() => {
  restoreDomGlobals = installFakeDomGlobals();
});

test.afterEach(() => {
  restoreDomGlobals();
  restoreDomGlobals = () => undefined;
});

test("realtime view bindings emit typed sensor actions and clean up listeners", () => {
  const sensorsSettingsBody = createContainer("tbody");
  const identifyButton = appendChild(sensorsSettingsBody, createButton({
    classes: ["row-identify"],
    attrs: { "data-client-id": "sensor-1" },
  }));
  const locationSelect = appendChild(sensorsSettingsBody, createSelect({
    classes: ["row-location-select"],
    attrs: { "data-client-id": "sensor-1" },
    value: "front-left",
  }));

  const sensorActions: Array<{ type: string; clientId: string }> = [];
  const locationChanges: Array<{ clientId: string; locationCode: string }> = [];

  const dispose = bindRealtimeFeatureInteractions(
    {
      sensorsSettingsBody: sensorsSettingsBody as unknown as HTMLElement,
    },
    {
      onSensorLocationChange: (change) => {
        locationChanges.push(change);
      },
      onSensorTableAction: (action) => {
        sensorActions.push(action);
      },
    },
  );

  sensorsSettingsBody.dispatch("click", {
    target: identifyButton as unknown as EventTarget,
  });
  sensorsSettingsBody.dispatch("change", {
    target: locationSelect as unknown as EventTarget,
  });

  expect(sensorActions).toEqual([{ type: "identify", clientId: "sensor-1" }]);
  expect(locationChanges).toEqual([{ clientId: "sensor-1", locationCode: "front-left" }]);

  dispose();
  sensorsSettingsBody.dispatch("click", {
    target: identifyButton as unknown as EventTarget,
  });
  expect(sensorActions).toEqual([{ type: "identify", clientId: "sensor-1" }]);
});

test("history table bindings preserve typed row actions and download-raw default navigation", () => {
  const refreshHistoryBtn = createButton();
  const deleteAllRunsBtn = createButton();
  const historyTableBody = createContainer("tbody");
  const inlineButton = appendChild(historyTableBody, createButton({
    attrs: { "data-inline-state-action": "open-live" },
  }));
  const deleteRunButton = appendChild(historyTableBody, createButton({
    attrs: {
      "data-run-action": "delete-run",
      "data-run": "run-1",
    },
  }));
  const downloadRawLink = appendChild(historyTableBody, (() => {
    const link = createContainer("a");
    link.setAttribute("data-run-action", "download-raw");
    link.setAttribute("data-run", "run-2");
    return link;
  })());
  const runRow = appendChild(historyTableBody, (() => {
    const row = createContainer("tr");
    row.setAttribute("data-run-row", "1");
    row.setAttribute("data-run", "run-3");
    return row;
  })());
  const rowCellButton = appendChild(runRow, createButton());

  const interactions: Array<Record<string, string | null>> = [];
  let refreshCalls = 0;
  let deleteAllCalls = 0;

  bindHistoryTableInteractions(
    {
      refreshHistoryBtn: refreshHistoryBtn as unknown as HTMLButtonElement,
      deleteAllRunsBtn: deleteAllRunsBtn as unknown as HTMLButtonElement,
      historyTableBody: historyTableBody as unknown as HTMLElement,
    },
    {
      onRefreshHistory: () => {
        refreshCalls += 1;
      },
      onDeleteAllRuns: () => {
        deleteAllCalls += 1;
      },
      onTableInteraction: (action) => {
        interactions.push(action as unknown as Record<string, string | null>);
      },
    },
  );

  refreshHistoryBtn.click();
  deleteAllRunsBtn.click();
  const inlineEvent = historyTableBody.dispatch("click", {
    target: inlineButton as unknown as EventTarget,
  });
  const deleteRunEvent = historyTableBody.dispatch("click", {
    target: deleteRunButton as unknown as EventTarget,
  });
  const downloadRawEvent = historyTableBody.dispatch("click", {
    target: downloadRawLink as unknown as EventTarget,
  });
  historyTableBody.dispatch("click", {
    target: rowCellButton as unknown as EventTarget,
  });

  expect(refreshCalls).toBe(1);
  expect(deleteAllCalls).toBe(1);
  expect(interactions).toEqual([
    { type: "open-live" },
    { type: "run-action", action: "delete-run", runId: "run-1" },
    { type: "run-action", action: "download-raw", runId: "run-2" },
    { type: "toggle-run", runId: "run-3" },
  ]);
  expect(inlineEvent.defaultPrevented).toBe(true);
  expect(inlineEvent.propagationStopped).toBe(true);
  expect(deleteRunEvent.defaultPrevented).toBe(true);
  expect(deleteRunEvent.propagationStopped).toBe(true);
  expect(downloadRawEvent.defaultPrevented).toBe(false);
  expect(downloadRawEvent.propagationStopped).toBe(true);
});

test("settings car-list bindings surface typed list actions and disposer stops delegated clicks", () => {
  const carListBody = createContainer("tbody");
  const addCarButton = appendChild(carListBody, createButton({
    attrs: { "data-inline-state-action": "add-car" },
  }));
  const activateCarButton = appendChild(carListBody, createButton({
    attrs: {
      "data-car-action": "activate",
      "data-car-id": "car-1",
    },
  }));

  const actions: Array<{ type: string; carId: string | null }> = [];

  const dispose = bindSettingsCarListActions(
    {
      carListBody: carListBody as unknown as HTMLElement,
    },
    {
      onAction: (action) => {
        actions.push(action);
      },
    },
  );

  carListBody.dispatch("click", { target: addCarButton as unknown as EventTarget });
  carListBody.dispatch("click", { target: activateCarButton as unknown as EventTarget });

  expect(actions).toEqual([
    { type: "add", carId: null },
    { type: "activate", carId: "car-1" },
  ]);

  dispose();
  carListBody.dispatch("click", { target: activateCarButton as unknown as EventTarget });
  expect(actions).toEqual([
    { type: "add", carId: null },
    { type: "activate", carId: "car-1" },
  ]);
});

test("cars wizard bindings decode typed wizard actions and stop after disposal", () => {
  const addCarBtn = createButton();
  const addCarWizard = createContainer();
  (addCarWizard as unknown as { hidden: boolean }).hidden = false;
  const wizardBackdrop = createContainer();
  const wizardCloseBtn = createButton();
  const wizardBackBtn = createButton();
  const wizardBrandList = createContainer();
  const wizardBrandButton = appendChild(wizardBrandList, createButton({
    classes: ["wiz-opt"],
    attrs: { "data-value": "BMW" },
  }));
  const wizardCustomBrandInput = createInput({ value: "Volvo" });
  const wizardCustomBrandBtn = createButton();
  const wizardTypeList = createContainer();
  const wizardModelList = createContainer();
  const wizardVariantList = createContainer();
  const wizardTireList = createContainer();
  const wizardGearboxList = createContainer();
  const wizardGearboxButton = appendChild(wizardGearboxList, createButton({
    classes: ["wiz-opt"],
    attrs: { "data-idx": "1" },
  }));
  const wizardCustomTypeInput = createInput({ value: "SUV" });
  const wizardCustomTypeBtn = createButton();
  const wizardCustomModelInput = createInput({ value: "XC90" });
  const wizardCustomModelBtn = createButton();
  const wizardManualAddBtn = createButton();
  const wizTireWidthInput = createInput({ value: "245" });
  const wizTireAspectInput = createInput({ value: "45" });
  const wizRimInput = createInput({ value: "18" });
  const wizFinalDriveInput = createInput({ value: "3.08" });
  const wizGearRatioInput = createInput({ value: "0.68" });
  const keyboardTarget = createContainer();

  const actions: Array<{ type: string; [key: string]: unknown }> = [];

  const dispose = bindCarsFeatureInteractions(
    {
      addCarBtn: addCarBtn as unknown as HTMLButtonElement,
      addCarWizard: addCarWizard as unknown as HTMLElement,
      wizFinalDriveInput: wizFinalDriveInput as unknown as HTMLInputElement,
      wizGearRatioInput: wizGearRatioInput as unknown as HTMLInputElement,
      wizRimInput: wizRimInput as unknown as HTMLInputElement,
      wizTireAspectInput: wizTireAspectInput as unknown as HTMLInputElement,
      wizTireWidthInput: wizTireWidthInput as unknown as HTMLInputElement,
      wizardBackdrop: wizardBackdrop as unknown as HTMLElement,
      wizardBackBtn: wizardBackBtn as unknown as HTMLButtonElement,
      wizardBrandList: wizardBrandList as unknown as HTMLElement,
      wizardCloseBtn: wizardCloseBtn as unknown as HTMLButtonElement,
      wizardCustomBrandBtn: wizardCustomBrandBtn as unknown as HTMLButtonElement,
      wizardCustomBrandInput: wizardCustomBrandInput as unknown as HTMLInputElement,
      wizardCustomModelBtn: wizardCustomModelBtn as unknown as HTMLButtonElement,
      wizardCustomModelInput: wizardCustomModelInput as unknown as HTMLInputElement,
      wizardCustomTypeBtn: wizardCustomTypeBtn as unknown as HTMLButtonElement,
      wizardCustomTypeInput: wizardCustomTypeInput as unknown as HTMLInputElement,
      wizardGearboxList: wizardGearboxList as unknown as HTMLElement,
      wizardManualAddBtn: wizardManualAddBtn as unknown as HTMLButtonElement,
      wizardModelList: wizardModelList as unknown as HTMLElement,
      wizardTireList: wizardTireList as unknown as HTMLElement,
      wizardTypeList: wizardTypeList as unknown as HTMLElement,
      wizardVariantList: wizardVariantList as unknown as HTMLElement,
    },
    {
      onAction: (action) => {
        actions.push(action);
      },
    },
    {
      keyboard: keyboardTarget,
    },
  );

  addCarBtn.dispatch("click");
  wizardBrandList.dispatch("click", { target: wizardBrandButton as unknown as EventTarget });
  wizardCustomBrandBtn.dispatch("click");
  wizardCustomModelBtn.dispatch("click");
  wizardGearboxList.dispatch("click", { target: wizardGearboxButton as unknown as EventTarget });
  wizTireWidthInput.dispatch("input");
  keyboardTarget.dispatch("keydown", { key: "Escape" });
  wizardManualAddBtn.dispatch("click");

  expect(actions).toEqual([
    { type: "open" },
    { type: "select-brand", value: "BMW" },
    { type: "submit-custom-brand", value: "Volvo" },
    { type: "submit-custom-model", value: "XC90" },
    { type: "select-gearbox", index: 1 },
    {
      type: "manual-inputs-changed",
      inputs: {
        finalDrive: "3.08",
        rim: "18",
        tireAspect: "45",
        tireWidth: "245",
        topGear: "0.68",
      },
    },
    { type: "close" },
    { type: "finish" },
  ]);

  dispose();
  addCarBtn.dispatch("click");
  expect(actions).toHaveLength(8);
});

test("speed-source bindings turn form events and OBD pairing clicks into typed actions", () => {
  const speedSourceRadio = createInput({ value: "manual" });
  const manualSpeedInput = createInput({ value: "80" });
  const staleTimeoutInput = createInput({ value: "5" });
  const saveSpeedSourceBtn = createButton();
  const scanObdDevicesBtn = createButton();
  const settingsTab = createContainer("button");
  const shellMenuButton = createContainer("button");
  const obdDeviceList = createContainer();
  const pairButton = appendChild(obdDeviceList, createButton({
    attrs: { "data-obd-pair-mac": "00:22:d9:00:1b:b1" },
  }));

  const actions: SettingsSpeedSourceInteraction[] = [];

  const dispose = bindSettingsSpeedSourceInteractions(
    {
      speedSourceRadios: [speedSourceRadio as unknown as HTMLInputElement],
      manualSpeedInput: manualSpeedInput as unknown as HTMLInputElement,
      staleTimeoutInput: staleTimeoutInput as unknown as HTMLInputElement,
      saveSpeedSourceBtn: saveSpeedSourceBtn as unknown as HTMLButtonElement,
      scanObdDevicesBtn: scanObdDevicesBtn as unknown as HTMLButtonElement,
      settingsTabs: [settingsTab as unknown as HTMLElement],
      obdDeviceList: obdDeviceList as unknown as HTMLElement,
    },
    {
      menuButtons: [shellMenuButton as unknown as HTMLElement],
    },
    {
      onAction: (action) => {
        actions.push(action);
      },
    },
  );

  speedSourceRadio.dispatch("change");
  manualSpeedInput.dispatch("input");
  staleTimeoutInput.dispatch("input");
  saveSpeedSourceBtn.click();
  scanObdDevicesBtn.click();
  settingsTab.dispatch("keydown", { key: "ArrowRight" });
  shellMenuButton.dispatch("keydown", { key: "Escape" });
  shellMenuButton.dispatch("click");
  obdDeviceList.dispatch("click", { target: pairButton as unknown as EventTarget });

  expect(actions).toEqual([
    { type: "speed-source-changed", mode: "manual" },
    { type: "manual-speed-input", value: "80" },
    { type: "stale-timeout-input", value: "5" },
    { type: "save" },
    { type: "scan-obd-devices" },
    { type: "navigate-context" },
    { type: "navigate-context" },
    { type: "pair-obd-device", macAddress: "00:22:d9:00:1b:b1" },
  ]);

  dispose();
  saveSpeedSourceBtn.click();
  expect(actions).toEqual([
    { type: "speed-source-changed", mode: "manual" },
    { type: "manual-speed-input", value: "80" },
    { type: "stale-timeout-input", value: "5" },
    { type: "save" },
    { type: "scan-obd-devices" },
    { type: "navigate-context" },
    { type: "navigate-context" },
    { type: "pair-obd-device", macAddress: "00:22:d9:00:1b:b1" },
  ]);
});
