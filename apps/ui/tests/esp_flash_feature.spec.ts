import { expect, test } from "@playwright/test";

import { createEspFlashFeature } from "../src/app/features/esp_flash_feature";
import { createUpdateFeature } from "../src/app/features/update_feature";
import type {
  EspFlashPanelActionHandlers,
  EspFlashPanelDom,
  EspFlashPanelRenderModel,
} from "../src/app/views/esp_flash_panel";
import type {
  InternetPanelActionHandlers,
  InternetPanelDom,
  InternetPanelRenderModel,
} from "../src/app/views/internet_panel";
import type {
  UpdatePanelActionHandlers,
  UpdatePanelDom,
  UpdatePanelRenderModel,
} from "../src/app/views/update_panel";
import {
  createDeferred,
  flushAsyncWork,
  installTimerHarness,
  installWindowGlobal,
  jsonResponse,
} from "./async_test_helpers";
import type { TimerHarness } from "./async_test_helpers";
import { createPanel, installFakeDomGlobals } from "./dom_render_test_support";

type ClickListener = (() => void) | null;

function pendingPollDelays(timers: TimerHarness): number[] {
  return timers.pendingDelays().filter((delay) => delay !== 10_000);
}

function installFetchMock(
  handler: (
    url: URL,
    method: string,
    body: string,
  ) => Promise<Response> | Response,
): () => void {
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async (
    input: string | URL | RequestInfo,
    init?: RequestInit,
  ) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    const requestMethod =
      init?.method ?? (input instanceof Request ? input.method : "GET");
    const requestBody = typeof init?.body === "string" ? init.body : "";
    return handler(
      new URL(requestUrl, "http://vibesensor.test"),
      requestMethod,
      requestBody,
    );
  }) as typeof fetch;

  return () => {
    globalThis.fetch = originalFetch;
  };
}

function createButton(): HTMLButtonElement {
  let onClick: ClickListener = null;

  return {
    disabled: false,
    hidden: false,
    addEventListener(
      type: string,
      listener: EventListenerOrEventListenerObject,
    ) {
      if (type !== "click") return;
      onClick = () => {
        const event = new Event("click");
        if (typeof listener === "function") {
          listener(event);
          return;
        }
        listener.handleEvent(event);
      };
    },
    click() {
      onClick?.();
    },
    querySelector() {
      return null;
    },
  } as unknown as HTMLButtonElement;
}

function createSelect(value: string): HTMLSelectElement {
  const listeners = new Map<
    string,
    Array<EventListenerOrEventListenerObject>
  >();
  return {
    value,
    disabled: false,
    innerHTML: "",
    addEventListener(
      type: string,
      listener: EventListenerOrEventListenerObject,
    ) {
      const typeListeners = listeners.get(type) ?? [];
      typeListeners.push(listener);
      listeners.set(type, typeListeners);
    },
    dispatchEvent(event: Event) {
      const typeListeners = listeners.get(event.type) ?? [];
      for (const listener of typeListeners) {
        if (typeof listener === "function") {
          listener(event);
          continue;
        }
        listener.handleEvent(event);
      }
      return true;
    },
  } as unknown as HTMLSelectElement;
}

function createInput(value = "", type = "text"): HTMLInputElement {
  const listeners = new Map<
    string,
    Array<EventListenerOrEventListenerObject>
  >();
  return {
    value,
    type,
    disabled: false,
    focus() {},
    addEventListener(
      type: string,
      listener: EventListenerOrEventListenerObject,
    ) {
      const typeListeners = listeners.get(type) ?? [];
      typeListeners.push(listener);
      listeners.set(type, typeListeners);
    },
    dispatchEvent(event: Event) {
      const typeListeners = listeners.get(event.type) ?? [];
      for (const listener of typeListeners) {
        if (typeof listener === "function") {
          listener(event);
          continue;
        }
        listener.handleEvent(event);
      }
      return true;
    },
  } as unknown as HTMLInputElement;
}

function setOptionalAttribute(
  element: { removeAttribute(name: string): void; setAttribute(name: string, value: string): void },
  name: string,
  value: string | null,
): void {
  if (value == null) {
    element.removeAttribute(name);
    return;
  }
  element.setAttribute(name, value);
}

function serializeBadge(
  badge: { text: string; variant: string } | null,
): string {
  return badge
    ? `<span class="pill" data-variant="${badge.variant}">${badge.text}</span>`
    : "";
}

function serializeStatusGrid(
  rows: readonly { labelText: string; valueText: string }[],
): string {
  return `<div class="status-grid">${rows.map((row) => `<div class="status-grid__row"><span class="status-grid__label">${row.labelText}</span><span>${row.valueText}</span></div>`).join("")}</div>`;
}

function serializeMaintenanceCard(options: {
  badge?: { text: string; variant: string } | null;
  bodyHtml: string;
  subtitleText: string;
  titleText: string;
}): string {
  return `<section class="maintenance-card"><div class="maintenance-card__header"><div><div class="maintenance-card__title">${options.titleText}</div><div class="subtle">${options.subtitleText}</div></div>${serializeBadge(options.badge ?? null)}</div><div class="maintenance-card__body">${options.bodyHtml}</div></section>`;
}

function serializeIssueDetail(text: string): string {
  return `<div class="issue-detail">${text}</div>`;
}

function serializeCurrentStatusCard(
  model: NonNullable<UpdatePanelRenderModel["status"]>["currentStatus"],
): string {
  const bodyHtml = model.rows.length > 0
    ? serializeStatusGrid(model.rows)
    : `<div class="maintenance-note">${model.emptyText ?? ""}</div>`;
  return serializeMaintenanceCard({
    badge: model.badge,
    bodyHtml,
    subtitleText: model.summaryText,
    titleText: model.titleText,
  });
}

function serializeHealthCard(
  model: NonNullable<UpdatePanelRenderModel["status"]>["health"],
): string {
  return serializeMaintenanceCard({
    badge: model.badge,
    bodyHtml: serializeStatusGrid(model.rows),
    subtitleText: model.summaryText,
    titleText: model.titleText,
  });
}

function serializeJourneyCard(
  model: NonNullable<UpdatePanelRenderModel["status"]>["journey"],
): string {
  const failureHtml = model.failureNote
    ? `<div class="maintenance-stack maintenance-stack--tight"><div class="maintenance-note maintenance-note--bad"><strong>${model.failureNote.summaryText}</strong>${model.failureNote.detailText ? serializeIssueDetail(model.failureNote.detailText) : ""}</div><div class="maintenance-note"><strong>${model.failureNote.recoveryTitleText}</strong>${serializeIssueDetail(model.failureNote.recoveryDetailText)}</div></div>`
    : "";
  const stagesHtml = model.stages.map((stage) => `<li class="maintenance-stage" data-stage-phase="${stage.phase}" data-stage-state="${stage.state}"${stage.current ? ' aria-current="step"' : ""}><span class="maintenance-stage__marker">${stage.markerText}</span><div class="maintenance-stage__body"><div class="maintenance-stage__title">${stage.titleText}</div><div class="maintenance-stage__detail">${stage.detailText}</div></div><span class="maintenance-stage__state">${stage.stateText}</span></li>`).join("");
  return serializeMaintenanceCard({
    bodyHtml: `<div class="maintenance-journey">${failureHtml}<ol class="maintenance-stage-list">${stagesHtml}</ol></div>`,
    subtitleText: model.subtitleText,
    titleText: model.titleText,
  });
}

function serializeIssuesCard(
  model: NonNullable<UpdatePanelRenderModel["status"]>["issues"],
): string {
  return serializeMaintenanceCard({
    bodyHtml: `<ul class="issue-list">${model.items.map((item) => `<li class="issue-item"><div class="issue-phase">${item.phaseText}</div><div><strong>${item.messageText}</strong>${item.detailText ? serializeIssueDetail(item.detailText) : ""}</div></li>`).join("")}</ul>`,
    subtitleText: model.subtitleText,
    titleText: model.titleText,
  });
}

function serializeLatestAttemptCard(
  model: NonNullable<UpdatePanelRenderModel["status"]>["latestAttempt"],
): string {
  const failureHtml = model.failureNote
    ? `<div class="maintenance-note maintenance-note--bad"><strong>${model.failureNote.summaryText}</strong>${model.failureNote.detailText ? serializeIssueDetail(model.failureNote.detailText) : ""}</div>`
    : "";
  return serializeMaintenanceCard({
    badge: model.badge,
    bodyHtml: `${serializeStatusGrid(model.rows)}${failureHtml}`,
    subtitleText: model.subtitleText,
    titleText: model.titleText,
  });
}

function serializeLogCard(
  model: NonNullable<UpdatePanelRenderModel["status"]>["log"],
): string {
  const bodyHtml = model.emptyState
    ? `<div class="empty-state empty-state--inline"><strong class="empty-state__title">${model.emptyState.titleText}</strong><span class="empty-state__body">${model.emptyState.bodyText}</span></div>`
    : `${model.noteText ? `<div class="maintenance-note">${model.noteText}</div>` : ""}<pre class="log-pre">${model.lines.map((line) => `${line}\n`).join("")}</pre>`;
  return serializeMaintenanceCard({
    bodyHtml,
    subtitleText: model.subtitleText,
    titleText: model.titleText,
  });
}

function serializeUpdateOverview(
  status: UpdatePanelRenderModel["status"],
): string {
  if (!status) {
    return "";
  }
  return `<div class="maintenance-pair-grid maintenance-pair-grid--summary">${serializeCurrentStatusCard(status.currentStatus)}${serializeHealthCard(status.health)}</div>`;
}

function serializeUpdateStatus(
  status: UpdatePanelRenderModel["status"],
): string {
  if (!status) {
    return "";
  }
  return `<div class="maintenance-pair-grid maintenance-pair-grid--focus">${serializeJourneyCard(status.journey)}${serializeLogCard(status.log)}</div>${status.latestAttempt ? serializeLatestAttemptCard(status.latestAttempt) : ""}${status.issues ? serializeIssuesCard(status.issues) : ""}`;
}

function renderUpdatePanelDom(
  dom: UpdatePanelDom,
  model: UpdatePanelRenderModel,
): void {
  dom.updateStartBtn.textContent = model.startButtonLabelText;
  dom.updateStartBtn.disabled = model.startButtonDisabled;
  dom.updateStartBtn.hidden = model.startButtonHidden;
  dom.updateCancelBtn.disabled = model.cancelButtonDisabled;
  dom.updateCancelBtn.hidden = model.cancelButtonHidden;
  if (dom.updateOverviewPanel) {
    dom.updateOverviewPanel.innerHTML = serializeUpdateOverview(model.status);
  }
  dom.updateStatusPanel.innerHTML = serializeUpdateStatus(model.status);
}

function serializeReadinessPanel(
  model: InternetPanelRenderModel["readiness"],
): string {
  const itemsHtml = model.items.map((item) => `<li class="maintenance-readiness__item" data-readiness-state="${item.state}"><span class="maintenance-readiness__marker" aria-hidden="true">${item.state === "ready" ? "✓" : "!"}</span><div class="maintenance-readiness__body"><div class="maintenance-readiness__label">${item.label}</div><div class="maintenance-readiness__detail">${item.detail}</div></div></li>`).join("");
  const badgeHtml = model.stateLabel
    ? `<span class="pill" data-variant="${model.stateVariant}">${model.stateLabel}</span>`
    : "";
  return `<section class="maintenance-readiness"><div class="maintenance-readiness__header"><div class="maintenance-readiness__heading"><div class="maintenance-readiness__title">${model.title}</div><div class="maintenance-readiness__summary">${model.summary}</div></div>${badgeHtml}</div><ul class="maintenance-readiness__list">${itemsHtml}</ul></section>`;
}

function serializeInternetStatusPanel(
  model: InternetPanelRenderModel["internetStatus"],
): string {
  if (!model) {
    return "";
  }
  return serializeMaintenanceCard({
    badge: model.badge,
    bodyHtml: serializeStatusGrid(model.rows),
    subtitleText: model.summaryText,
    titleText: model.titleText,
  });
}

function renderInternetPanelDom(
  dom: InternetPanelDom,
  model: InternetPanelRenderModel,
): void {
  if (dom.internetStatusPanel) {
    dom.internetStatusPanel.innerHTML = serializeInternetStatusPanel(model.internetStatus);
  }
  if (dom.updateTransportOptions) {
    dom.updateTransportOptions.hidden = false;
  }
  if (dom.updateTransportChoiceWifi) {
    setOptionalAttribute(
      dom.updateTransportChoiceWifi,
      "data-selected",
      model.transportChoices.wifi.selected ? "true" : null,
    );
    setOptionalAttribute(
      dom.updateTransportChoiceWifi,
      "data-disabled",
      model.transportChoices.wifi.disabled ? "true" : null,
    );
    setOptionalAttribute(
      dom.updateTransportChoiceWifi,
      "data-choice-state",
      model.transportChoices.wifi.state,
    );
    setOptionalAttribute(
      dom.updateTransportChoiceWifi,
      "data-choice-badge",
      model.transportChoices.wifi.badgeText,
    );
  }
  if (dom.updateTransportChoiceUsb) {
    setOptionalAttribute(
      dom.updateTransportChoiceUsb,
      "data-selected",
      model.transportChoices.usb_internet.selected ? "true" : null,
    );
    setOptionalAttribute(
      dom.updateTransportChoiceUsb,
      "data-disabled",
      model.transportChoices.usb_internet.disabled ? "true" : null,
    );
    setOptionalAttribute(
      dom.updateTransportChoiceUsb,
      "data-choice-state",
      model.transportChoices.usb_internet.state,
    );
    setOptionalAttribute(
      dom.updateTransportChoiceUsb,
      "data-choice-badge",
      model.transportChoices.usb_internet.badgeText,
    );
  }
  if (dom.updateTransportWifiRadio) {
    dom.updateTransportWifiRadio.checked = model.transportChoices.wifi.selected;
    dom.updateTransportWifiRadio.disabled = model.transportChoices.wifi.inputDisabled;
  }
  if (dom.updateTransportUsbRadio) {
    dom.updateTransportUsbRadio.checked = model.transportChoices.usb_internet.selected;
    dom.updateTransportUsbRadio.disabled = model.transportChoices.usb_internet.inputDisabled;
  }
  if (dom.updateWifiFields) {
    dom.updateWifiFields.hidden = model.wifiFieldsHidden;
  }
  if (dom.updateReadinessSummary) {
    dom.updateReadinessSummary.innerHTML = serializeReadinessPanel(model.readiness);
  }
  if (dom.updateDetailsCaption) {
    dom.updateDetailsCaption.textContent = model.detailsCaptionText;
  }
  if (dom.updateTransportNote) {
    dom.updateTransportNote.textContent = model.transportNoteText;
  }
  if (dom.updateUsbTransportSummary) {
    dom.updateUsbTransportSummary.textContent =
      model.transportChoices.usb_internet.summaryText;
  }
  if (dom.updateSsidInput) {
    dom.updateSsidInput.value = model.ssidInputValue;
    dom.updateSsidInput.disabled = model.controlsLocked;
  }
  if (dom.updatePasswordInput) {
    dom.updatePasswordInput.value = model.passwordInputValue;
    dom.updatePasswordInput.type = model.passwordInputType;
    dom.updatePasswordInput.disabled = model.controlsLocked;
  }
  if (dom.updateTogglePasswordBtn) {
    dom.updateTogglePasswordBtn.disabled = model.togglePasswordDisabled;
    dom.updateTogglePasswordBtn.textContent = model.togglePasswordLabelText;
  }
}

function serializeEspFlashReadinessPanel(
  model: EspFlashPanelRenderModel["readiness"],
): string {
  return `<div class="maintenance-stack maintenance-stack--tight"><div class="subtle">${model.summaryText}</div>${model.rows.length > 0 ? serializeStatusGrid(model.rows) : ""}${model.errorText ? `<div class="maintenance-note maintenance-note--bad">${model.errorText}</div>` : ""}</div>`;
}

function serializeEspFlashJourney(
  model: EspFlashPanelRenderModel["journey"],
): string {
  const noteHtml = model.terminalNoteText
    ? `<div class="maintenance-note maintenance-note--bad">${model.terminalNoteText}</div>`
    : "";
  const stagesHtml = model.stages.map((stage) => `<li class="maintenance-stage" data-stage-phase="${stage.phase}" data-stage-state="${stage.state}"${stage.current ? ' aria-current="step"' : ""}><span class="maintenance-stage__marker">${stage.markerText}</span><div class="maintenance-stage__body"><div class="maintenance-stage__title">${stage.titleText}</div><div class="maintenance-stage__detail">${stage.detailText}</div></div><span class="maintenance-stage__state">${stage.stateText}</span></li>`).join("");
  return `<div class="maintenance-journey">${noteHtml}<ol class="maintenance-stage-list">${stagesHtml}</ol></div>`;
}

function serializeInlineEmptyState(model: {
  bodyText: string;
  titleText: string;
}): string {
  return `<div class="empty-state empty-state--inline"><strong class="empty-state__title">${model.titleText}</strong><span class="empty-state__body">${model.bodyText}</span></div>`;
}

function serializeEspFlashLog(
  model: EspFlashPanelRenderModel["log"],
): string {
  return model.emptyState
    ? serializeInlineEmptyState(model.emptyState)
    : `<pre class="log-pre">${model.text}</pre>`;
}

function serializeEspFlashHistory(
  model: EspFlashPanelRenderModel["history"],
): string {
  if (model.emptyState) {
    return serializeInlineEmptyState(model.emptyState);
  }
  return `<ul class="maintenance-attempt-list">${model.attempts.map((attempt) => `<li class="maintenance-attempt"><div class="maintenance-attempt__header"><span class="pill" data-variant="${attempt.badge.variant}">${attempt.badge.text}</span><strong>${attempt.portText}</strong></div><div class="maintenance-attempt__meta subtle">${attempt.metaText}</div>${attempt.errorText ? `<div class="maintenance-note maintenance-note--bad">${attempt.errorText}</div>` : ""}</li>`).join("")}</ul>`;
}

function renderEspFlashPanelDom(
  dom: EspFlashPanelDom,
  model: EspFlashPanelRenderModel,
): void {
  if (dom.espFlashPortSelect) {
    dom.espFlashPortSelect.innerHTML = model.portOptions.map((option) => `<option value="${option.value}">${option.labelText}</option>`).join("");
    dom.espFlashPortSelect.value = model.selectedPortValue;
    dom.espFlashPortSelect.disabled = model.portSelectDisabled;
  }
  if (dom.espFlashRefreshPortsBtn) {
    dom.espFlashRefreshPortsBtn.disabled = model.refreshPortsDisabled;
  }
  dom.espFlashStartBtn.textContent = model.startButtonLabelText;
  dom.espFlashStartBtn.disabled = model.startButtonDisabled;
  dom.espFlashStartBtn.hidden = model.startButtonHidden;
  if (dom.espFlashCancelBtn) {
    dom.espFlashCancelBtn.disabled = model.cancelButtonDisabled;
    dom.espFlashCancelBtn.hidden = model.cancelButtonHidden;
  }
  if (dom.espFlashStartSummary) {
    dom.espFlashStartSummary.innerHTML = serializeReadinessPanel(model.startSummary);
  }
  if (dom.espFlashStatusBanner) {
    dom.espFlashStatusBanner.className = "pill";
    setOptionalAttribute(
      dom.espFlashStatusBanner,
      "data-variant",
      model.statusBanner.variant,
    );
    dom.espFlashStatusBanner.textContent = model.statusBanner.text;
  }
  if (dom.espFlashReadinessPanel) {
    dom.espFlashReadinessPanel.innerHTML = serializeEspFlashReadinessPanel(model.readiness);
  }
  if (dom.espFlashJourneyPanel) {
    dom.espFlashJourneyPanel.innerHTML = serializeEspFlashJourney(model.journey);
  }
  if (dom.espFlashLogPanel) {
    dom.espFlashLogPanel.className = model.log.emptyState
      ? "maintenance-log-slot"
      : "maintenance-log-slot maintenance-log-panel";
    dom.espFlashLogPanel.innerHTML = serializeEspFlashLog(model.log);
  }
  if (dom.espFlashHistoryPanel) {
    dom.espFlashHistoryPanel.innerHTML = serializeEspFlashHistory(model.history);
  }
}

function createDeps() {
  const espFlashPortSelect = createSelect("__auto__");
  const espFlashRefreshPortsBtn = createButton();
  const espFlashStartBtn = createButton();
  const espFlashCancelBtn = createButton();
  const espFlashStartSummary = createPanel();
  const espFlashStatusBanner = createPanel();
  const espFlashReadinessPanel = createPanel();
  const espFlashJourneyPanel = createPanel();
  const espFlashLogPanel = createPanel();
  const espFlashHistoryPanel = createPanel();

  const dom = {
    menuButtons: [],
    views: [],
    settingsTabs: [],
    settingsTabPanels: [],
    espFlashPortSelect,
    espFlashRefreshPortsBtn,
    espFlashStartBtn,
    espFlashCancelBtn,
    espFlashStartSummary,
    espFlashStatusBanner,
    espFlashReadinessPanel,
    espFlashJourneyPanel,
    espFlashLogPanel,
    espFlashHistoryPanel,
  } as EspFlashPanelDom;

  return {
    panel: {
      bindActions(handlers: EspFlashPanelActionHandlers) {
        dom.espFlashStartBtn.addEventListener("click", () => {
          handlers.onStart();
        });
        dom.espFlashCancelBtn?.addEventListener("click", () => {
          handlers.onCancel();
        });
        dom.espFlashRefreshPortsBtn?.addEventListener("click", () => {
          handlers.onRefreshPorts();
        });
        dom.espFlashPortSelect?.addEventListener("change", () => {
          handlers.onSelectPort(dom.espFlashPortSelect?.value || "__auto__");
        });
      },
      setModel(model: EspFlashPanelRenderModel) {
        renderEspFlashPanelDom(dom, model);
      },
    },
    els: dom,
    espFlashPortSelect,
    espFlashRefreshPortsBtn,
    espFlashStartBtn,
    espFlashCancelBtn,
    espFlashStartSummary,
    espFlashReadinessPanel,
    espFlashJourneyPanel,
    services: {
      t: (key: string) => key,
      showError: () => {},
    },
  };
}

let restoreDomGlobals = () => undefined;

test.beforeEach(() => {
  restoreDomGlobals = installFakeDomGlobals();
});

test.afterEach(() => {
  restoreDomGlobals();
  restoreDomGlobals = () => undefined;
});

async function expectDelays(
  readDelays: () => number[],
  expected: number[],
): Promise<void> {
  for (let attempt = 0; attempt < 25; attempt += 1) {
    const actual = readDelays();
    if (
      actual.length === expected.length &&
      actual.every((delay, index) => delay === expected[index])
    ) {
      expect(actual).toEqual(expected);
      return;
    }
    await flushAsyncWork(1);
  }
  expect(readDelays()).toEqual(expected);
}

async function expectPollDelays(
  timers: TimerHarness,
  expected: number[],
): Promise<void> {
  await expectDelays(() => pendingPollDelays(timers), expected);
}

async function expectTimerDelays(
  timers: TimerHarness,
  expected: number[],
): Promise<void> {
  await expectDelays(() => timers.pendingDelays(), expected);
}

function createIdleUpdateStatus() {
  return {
    state: "idle",
    phase: "idle",
    transport: "wifi",
    ssid: null,
    uplink_interface: null,
    started_at: null,
    phase_started_at: null,
    phase_elapsed_s: null,
    finished_at: null,
    last_success_at: null,
    updated_at: null,
    issues: [],
    log_tail: [],
    exit_code: null,
    runtime: {
      version: "1.2.3",
      commit: "abcdef1234567890",
      ui_source_hash: "ui-hash",
      static_assets_hash: "feedfacecafebeef",
      static_build_source_hash: "build-hash",
      static_build_commit: "build-commit",
      assets_verified: true,
      has_packaged_static: true,
    },
  };
}

function createHealthyUpdateStatus() {
  return {
    status: "ok",
    processing_state: "idle",
    processing_failures: 0,
    degradation_reasons: [],
    data_loss: {
      affected_clients: 0,
      tracked_clients: 0,
      frames_dropped: 0,
      queue_overflow_drops: 0,
      server_queue_drops: 0,
      parse_errors: 0,
    },
    persistence: {
      analysis_in_progress: false,
      analysis_queue_depth: 0,
      write_error: null,
      analysis_active_run_id: null,
      analysis_started_at: null,
      analysis_elapsed_s: null,
    },
  };
}

function createUpdateDeps() {
  const internetStatusPanel = createPanel();
  const updateTransportOptions = createPanel();
  const updateTransportChoiceWifi = createPanel();
  const updateTransportChoiceUsb = createPanel();
  const updateWifiFields = createPanel();
  const updateReadinessSummary = createPanel();
  const updateDetailsCaption = createPanel();
  const updateTransportNote = createPanel();
  const updateUsbTransportSummary = createPanel();
  const updateTransportWifiRadio = createInput("", "radio");
  updateTransportWifiRadio.checked = true;
  const updateTransportUsbRadio = createInput("", "radio");
  updateTransportUsbRadio.checked = false;
  const updateSsidInput = createInput("MyWiFi");
  const updatePasswordInput = createInput("secret", "password");
  const updateTogglePasswordBtn = createButton();
  const updateStartBtn = createButton();
  const updateCancelBtn = createButton();
  const updateOverviewPanel = createPanel();
  const updateStatusPanel = createPanel();

  const internetDom = {
    internetStatusPanel,
    updateTransportOptions,
    updateTransportChoiceWifi,
    updateTransportChoiceUsb,
    updateWifiFields,
    updateReadinessSummary,
    updateDetailsCaption,
    updateTransportNote,
    updateTransportWifiRadio,
    updateTransportUsbRadio,
    updateUsbTransportSummary,
    updateSsidInput,
    updatePasswordInput,
    updateTogglePasswordBtn,
  } as InternetPanelDom;

  const dom = {
    updateOverviewPanel,
    updateStartBtn,
    updateCancelBtn,
    updateStatusPanel,
  } as UpdatePanelDom;

  return {
    panels: {
      update: {
        dom,
        bindActions(handlers: UpdatePanelActionHandlers) {
          dom.updateStartBtn.addEventListener("click", () => {
            handlers.onStart();
          });
          dom.updateCancelBtn.addEventListener("click", () => {
            handlers.onCancel();
          });
        },
        setModel(model: UpdatePanelRenderModel) {
          renderUpdatePanelDom(dom, model);
        },
      },
      internet: {
        dom: internetDom,
        bindActions(handlers: InternetPanelActionHandlers) {
          internetDom.updatePasswordInput?.addEventListener("input", () => {
            handlers.onPasswordInput(internetDom.updatePasswordInput?.value ?? "");
          });
          internetDom.updateTogglePasswordBtn?.addEventListener("click", () => {
            handlers.onTogglePassword();
          });
          internetDom.updateTransportWifiRadio?.addEventListener("change", () => {
            handlers.onTransportChange("wifi");
          });
          internetDom.updateTransportUsbRadio?.addEventListener("change", () => {
            handlers.onTransportChange("usb_internet");
          });
          internetDom.updateSsidInput?.addEventListener("input", () => {
            handlers.onSsidInput(internetDom.updateSsidInput?.value ?? "");
          });
        },
        setModel(model: InternetPanelRenderModel) {
          renderInternetPanelDom(internetDom, model);
        },
      },
    },
    els: dom,
    internetStatusPanel,
    updateTransportOptions,
    updateTransportChoiceWifi,
    updateTransportChoiceUsb,
    updateWifiFields,
    updateReadinessSummary,
    updateDetailsCaption,
    updateTransportNote,
    updateTransportWifiRadio,
    updateTransportUsbRadio,
    updateUsbTransportSummary,
    updateSsidInput,
    updatePasswordInput,
    updateStartBtn,
    updateCancelBtn,
    services: {
      t: (key: string) => key,
      showError: () => {},
    },
  };
}

function createUsbInternetStatus(overrides: Record<string, unknown> = {}) {
  return {
    detected: false,
    usable: false,
    interface_name: null,
    connection_name: null,
    driver: null,
    ipv4_addresses: [],
    gateway: null,
    has_default_route: false,
    diagnostic: "No USB network interface is currently detected.",
    ...overrides,
  };
}

test.beforeEach(() => {
  installWindowGlobal();
});

test.describe("createEspFlashFeature polling", () => {
  test("idle state renders readiness, empty log, and empty history context", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({
          ports: [
            {
              port: "/dev/ttyUSB0",
              description: "USB UART",
              vid: 1,
              pid: 2,
              serial_number: "abc",
            },
          ],
        });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({
          state: "idle",
          phase: "idle",
          selected_port: null,
          auto_detect: true,
          last_success_at: null,
          error: null,
          log_count: 0,
        });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.summary_ready",
      );
      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.item.connection_ready",
      );
      expect(deps.espFlashStartBtn.disabled).toBe(false);
      expect(deps.espFlashCancelBtn.hidden).toBe(true);
      expect(deps.espFlashReadinessPanel.innerHTML).toContain(
        "settings.esp_flash.readiness.summary.ready_ports",
      );
      expect(deps.espFlashReadinessPanel.innerHTML).toContain(
        "settings.esp_flash.readiness.one_port",
      );
      expect(deps.espFlashReadinessPanel.innerHTML).toContain(
        "settings.esp_flash.auto_detect",
      );
      expect(deps.espFlashReadinessPanel.innerHTML).not.toContain(
        "settings.esp_flash.journey_title",
      );
      expect(deps.espFlashReadinessPanel.innerHTML).not.toContain(
        "settings.esp_flash.phase.validating",
      );
      expect(deps.espFlashJourneyPanel.innerHTML).toContain(
        "settings.esp_flash.phase.validating",
      );
      expect((deps.els.espFlashLogPanel as HTMLElement).innerHTML).toContain(
        "settings.esp_flash.logs_idle_title",
      );
      expect(
        (deps.els.espFlashHistoryPanel as HTMLElement).innerHTML,
      ).toContain("settings.esp_flash.history_empty_title");
    } finally {
      restoreFetch();
    }
  });

  test("no detected ports keep the flash action blocked until hardware is present", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({ ports: [] });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({
          state: "idle",
          phase: "idle",
          selected_port: null,
          auto_detect: true,
          last_success_at: null,
          error: null,
          log_count: 0,
        });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.summary_blocked",
      );
      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.item.connection_blocked",
      );
      expect(deps.espFlashStartBtn.disabled).toBe(true);
      expect(deps.espFlashCancelBtn.hidden).toBe(true);
    } finally {
      restoreFetch();
    }
  });

  test("running state highlights the active stage and marks completed stages done", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({
          ports: [
            {
              port: "/dev/ttyUSB0",
              description: "USB UART",
              vid: 1,
              pid: 2,
              serial_number: "abc",
            },
          ],
        });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({
          state: "running",
          phase: "flashing",
          selected_port: "/dev/ttyUSB0",
          auto_detect: false,
          last_success_at: null,
          error: null,
          log_count: 0,
        });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.start_readiness.summary_running",
      );
      expect(deps.espFlashStartBtn.hidden).toBe(true);
      expect(deps.espFlashCancelBtn.hidden).toBe(false);
      expect((deps.els.espFlashLogPanel as HTMLElement).innerHTML).toContain(
        "settings.esp_flash.logs_running_title",
      );
      const html = deps.espFlashJourneyPanel.innerHTML;
      expect(html).toMatch(
        /data-stage-phase="flashing" data-stage-state="active" aria-current="step"/,
      );
      expect(deps.espFlashReadinessPanel.innerHTML).toContain(
        "settings.esp_flash.readiness.current_step",
      );
      expect(html.match(/data-stage-state="done"/g)).toHaveLength(3);
      expect(
        html.match(/<span class="maintenance-stage__marker">✓<\/span>/g),
      ).toHaveLength(3);
    } finally {
      restoreFetch();
    }
  });

  test("failed refresh keeps the last running stage marked as stopped here", async () => {
    let status = {
      state: "running",
      phase: "flashing",
      selected_port: "/dev/ttyUSB0",
      auto_detect: false,
      last_success_at: null,
      error: null,
      log_count: 0,
    };
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({
          ports: [
            {
              port: "/dev/ttyUSB0",
              description: "USB UART",
              vid: 1,
              pid: 2,
              serial_number: "abc",
            },
          ],
        });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse(status);
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      status = {
        ...status,
        state: "failed",
        phase: "failed",
        error: "serial port disconnected",
      };
      feature.stopPolling();
      feature.startPolling();
      await flushAsyncWork();

      const html = deps.espFlashJourneyPanel.innerHTML;
      expect(html).toMatch(
        /data-stage-phase="flashing" data-stage-state="attention"/,
      );
      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.recovery.title",
      );
      expect(deps.espFlashStartSummary.innerHTML).toContain(
        "settings.esp_flash.recovery.flashing.detail",
      );
      expect(deps.espFlashStartBtn.textContent).toBe(
        "settings.esp_flash.retry",
      );
      expect((deps.els.espFlashLogPanel as HTMLElement).innerHTML).toContain(
        "settings.esp_flash.logs_failed_title",
      );
      expect(
        (deps.els.espFlashHistoryPanel as HTMLElement).innerHTML,
      ).toContain("serial port disconnected");
      expect(html.match(/data-stage-state="done"/g)).toHaveLength(3);
      expect(deps.espFlashReadinessPanel.innerHTML).toContain(
        "serial port disconnected",
      );
    } finally {
      restoreFetch();
    }
  });

  test("start replaces the previous poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFetchMock(async (url, method) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({
          ports: [
            {
              port: "/dev/ttyUSB0",
              description: "USB UART",
              vid: 1,
              pid: 2,
              serial_number: "abc",
            },
          ],
        });
      }
      if (url.pathname === "/api/esp-flash/start" && method === "POST") {
        return jsonResponse({ status: "started", job_id: 1 });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", log_count: 0, error: null });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.bindHandlers();
      feature.startPolling();
      await expectPollDelays(timers, [4_000]);

      deps.espFlashStartBtn.click();
      await expectPollDelays(timers, [4_000]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("manual port selection is reflected in the flash start payload", async () => {
    let startBody: Record<string, unknown> | null = null;
    const restoreFetch = installFetchMock(async (url, method, body) => {
      if (url.pathname === "/api/esp-flash/ports") {
        return jsonResponse({
          ports: [
            {
              port: "/dev/ttyUSB0",
              description: "USB UART",
              vid: 1,
              pid: 2,
              serial_number: "abc",
            },
            {
              port: "/dev/ttyUSB1",
              description: "ESP32 Bootloader",
              vid: 3,
              pid: 4,
              serial_number: "def",
            },
          ],
        });
      }
      if (url.pathname === "/api/esp-flash/start" && method === "POST") {
        startBody = JSON.parse(body) as Record<string, unknown>;
        return jsonResponse({ status: "started", job_id: 1 });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", log_count: 0, error: null });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.bindHandlers();
      feature.startPolling();
      await flushAsyncWork();

      deps.els.espFlashPortSelect.value = "/dev/ttyUSB1";
      deps.els.espFlashPortSelect.dispatchEvent(new Event("change"));
      deps.espFlashStartBtn.click();
      await flushAsyncWork();

      expect(startBody).toEqual({
        auto_detect: false,
        port: "/dev/ttyUSB1",
      });
    } finally {
      restoreFetch();
    }
  });

  test("cancel replaces the previous poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFetchMock(async (url, method) => {
      if (url.pathname === "/api/esp-flash/ports")
        return jsonResponse({ ports: [] });
      if (url.pathname === "/api/esp-flash/cancel" && method === "POST") {
        return jsonResponse({ status: "cancelled" });
      }
      if (url.pathname === "/api/esp-flash/status") {
        return jsonResponse({ state: "idle", log_count: 0, error: null });
      }
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.bindHandlers();
      feature.startPolling();
      await expectPollDelays(timers, [4_000]);

      deps.espFlashCancelBtn.click();
      await expectPollDelays(timers, [4_000]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("stopPolling prevents an in-flight poll from reviving the loop", async () => {
    const timers = installTimerHarness();
    const deferredStatus = createDeferred<Response>();
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/esp-flash/ports")
        return jsonResponse({ ports: [] });
      if (url.pathname === "/api/esp-flash/status")
        return deferredStatus.promise;
      if (url.pathname === "/api/esp-flash/logs") {
        return jsonResponse({ from_index: 0, next_index: 0, lines: [] });
      }
      if (url.pathname === "/api/esp-flash/history") {
        return jsonResponse({ attempts: [] });
      }
      return jsonResponse({});
    });

    try {
      const deps = createDeps();
      const feature = createEspFlashFeature(deps);

      feature.startPolling();
      await flushAsyncWork();
      expect(pendingPollDelays(timers)).toEqual([]);

      feature.stopPolling();
      deferredStatus.resolve(
        jsonResponse({ state: "idle", log_count: 0, error: null }),
      );
      await flushAsyncWork();

      expect(pendingPollDelays(timers)).toEqual([]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });
});

test.describe("createUpdateFeature polling", () => {
  test("idle update status renders readiness and the expected journey", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.bindUpdateHandlers();
      deps.updateSsidInput.value = "MyWiFi";
      deps.updateSsidInput.dispatchEvent(new Event("input"));
      feature.startPolling();
      await flushAsyncWork();

      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain(
        "settings.update.journey_title",
      );
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain(
        "settings.update.phase.validating",
      );
      expect(
        (deps.els.updateStatusPanel as HTMLElement).innerHTML,
      ).not.toContain("settings.update.issues_empty_title");
      expect((deps.els.updateStatusPanel as HTMLElement).innerHTML).toContain(
        "settings.update.log_empty_title",
      );
      expect((deps.els.updateOverviewPanel as HTMLElement).innerHTML).toContain(
        "settings.update.current_status_title",
      );
      expect((deps.els.updateOverviewPanel as HTMLElement).innerHTML).toContain(
        "settings.update.current_status_summary.ready",
      );
      expect((deps.els.updateOverviewPanel as HTMLElement).innerHTML).toContain(
        "1.2.3",
      );
      expect((deps.els.updateOverviewPanel as HTMLElement).innerHTML).toContain(
        "settings.update.health_card_title",
      );
      expect((deps.internetStatusPanel as HTMLElement).innerHTML).toContain(
        "settings.internet.card_title",
      );
      expect((deps.internetStatusPanel as HTMLElement).innerHTML).toContain(
        "settings.internet.summary.not_detected",
      );
      expect(deps.updateTransportOptions.hidden).toBe(false);
      expect(deps.updateTransportChoiceWifi.getAttribute("data-selected")).toBe(
        "true",
      );
      expect(
        deps.updateTransportChoiceWifi.getAttribute("data-choice-state"),
      ).toBe("active");
      expect(
        deps.updateTransportChoiceWifi.getAttribute("data-choice-badge"),
      ).toBe("settings.update.transport.selected_badge");
      expect(deps.updateTransportChoiceUsb.getAttribute("data-disabled")).toBe(
        "true",
      );
      expect(deps.updateTransportUsbRadio.disabled).toBe(true);
      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.readiness.summary_ready",
      );
      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.readiness.item.connection_wifi_ready",
      );
      expect(deps.updateDetailsCaption.textContent).toBe(
        "settings.update.details_caption_wifi",
      );
      expect(deps.updateStartBtn.disabled).toBe(false);
      expect(deps.updateUsbTransportSummary.textContent).toBe(
        "settings.update.transport.usb_summary_unavailable",
      );
    } finally {
      restoreFetch();
    }
  });

  test("degraded health blocks update start until maintenance issues are resolved", async () => {
    const healthy = createHealthyUpdateStatus();
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse({
          ...healthy,
          status: "degraded",
          degradation_reasons: ["persistence_write_error"],
          persistence: {
            ...healthy.persistence,
            write_error: "database locked",
          },
        });
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.readiness.item.health_blocked",
      );
      expect(deps.updateStartBtn.disabled).toBe(true);
    } finally {
      restoreFetch();
    }
  });

  test("running update state highlights the active journey stage", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") {
        return jsonResponse({
          ...createIdleUpdateStatus(),
          state: "running",
          phase: "installing",
          transport: "wifi",
          ssid: "MyWiFi",
        });
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      const html = (deps.els.updateStatusPanel as HTMLElement).innerHTML;
      expect(html).toContain("settings.update.log_running_title");
      expect(html).toMatch(
        /data-stage-phase="installing" data-stage-state="active" aria-current="step"/,
      );
      expect(html.match(/data-stage-state="done"/g)).toHaveLength(5);
      expect(
        html.match(/<span class="maintenance-stage__marker">✓<\/span>/g),
      ).toHaveLength(5);
    } finally {
      restoreFetch();
    }
  });

  test("persisted Wi-Fi ssid rehydrates the update input after startup", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") {
        return jsonResponse({
          ...createIdleUpdateStatus(),
          ssid: "Workshop Wi-Fi",
          updated_at: 123,
          last_success_at: 123,
        });
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      deps.panels.internet.dom.updateSsidInput.value = "";
      const feature = createUpdateFeature(deps);

      feature.startPolling();
      await flushAsyncWork();

      expect(deps.panels.internet.dom.updateSsidInput.value).toBe("Workshop Wi-Fi");
      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.readiness.summary_ready",
      );
      expect(deps.updateStartBtn.disabled).toBe(false);
    } finally {
      restoreFetch();
    }
  });

  test("persisted Wi-Fi ssid does not overwrite a user edit already in progress", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") {
        return jsonResponse({
          ...createIdleUpdateStatus(),
          ssid: "Workshop Wi-Fi",
          updated_at: 123,
          last_success_at: 123,
        });
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.bindUpdateHandlers();
      deps.updateSsidInput.value = "Driver-entered Wi-Fi";
      deps.updateSsidInput.dispatchEvent(new Event("input"));
      feature.startPolling();
      await flushAsyncWork();

      expect(deps.panels.internet.dom.updateSsidInput.value).toBe(
        "Driver-entered Wi-Fi",
      );
    } finally {
      restoreFetch();
    }
  });

  test("failed update state surfaces the failed stage and issue details", async () => {
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") {
        return jsonResponse({
          ...createIdleUpdateStatus(),
          state: "failed",
          phase: "restoring_hotspot",
          transport: "wifi",
          issues: [
            {
              phase: "restoring_hotspot",
              message: "Hotspot restart timed out",
              detail: "NetworkManager is still reconnecting to the uplink.",
            },
          ],
        });
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.bindUpdateHandlers();
      deps.updateSsidInput.value = "MyWiFi";
      deps.updateSsidInput.dispatchEvent(new Event("input"));
      feature.startPolling();
      await flushAsyncWork();

      const html = (deps.els.updateStatusPanel as HTMLElement).innerHTML;
      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.recovery.title",
      );
      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.recovery.wifi.title",
      );
      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.recovery.wifi.detail",
      );
      expect(deps.updateStartBtn.textContent).toBe("settings.update.retry");
      expect(html).toContain("settings.update.issues");
      expect(html).toContain("settings.update.attempt_title");
      expect(html).toContain("settings.update.log_failed_title");
      expect(html).toContain("Hotspot restart timed out");
      expect(html).toContain(
        "NetworkManager is still reconnecting to the uplink.",
      );
      expect(html).toMatch(
        /data-stage-phase="restoring_hotspot" data-stage-state="attention"/,
      );
    } finally {
      restoreFetch();
    }
  });

  test("start replaces the previous update poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    let startBody = "";
    const restoreFetch = installFetchMock(async (url, method, body) => {
      if (url.pathname === "/api/update/start" && method === "POST") {
        startBody = body;
        return jsonResponse({
          status: "started",
          transport: "wifi",
          ssid: "MyWiFi",
        });
      }
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.bindUpdateHandlers();
      feature.startPolling();
      await expectTimerDelays(timers, [10_000]);
      deps.updatePasswordInput.value = "secret";
      deps.updatePasswordInput.dispatchEvent(new Event("input"));
      deps.updateSsidInput.value = "MyWiFi";
      deps.updateSsidInput.dispatchEvent(new Event("input"));

      deps.updateStartBtn.click();
      await expectTimerDelays(timers, [10_000]);
      expect(deps.updatePasswordInput.value).toBe("");
      expect(JSON.parse(startBody)).toEqual({
        transport: "wifi",
        ssid: "MyWiFi",
        password: "secret",
      });
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("usable USB internet shows the USB option and starts with the USB transport payload", async () => {
    let startBody = "";
    const restoreFetch = installFetchMock(async (url, method, body) => {
      if (url.pathname === "/api/update/start" && method === "POST") {
        startBody = body;
        return jsonResponse({
          status: "started",
          transport: "usb_internet",
          ssid: null,
        });
      }
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(
          createUsbInternetStatus({
            detected: true,
            usable: true,
            interface_name: "usb0",
            connection_name: "iPhone USB",
            driver: "ipheth",
            ipv4_addresses: ["172.20.10.2/28"],
            gateway: "172.20.10.1",
            has_default_route: true,
            diagnostic: "USB internet is ready on 'usb0'.",
          }),
        );
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      deps.updateTransportWifiRadio.checked = false;
      deps.updateTransportUsbRadio.checked = true;
      const feature = createUpdateFeature(deps);

      feature.bindUpdateHandlers();
      feature.startPolling();
      await flushAsyncWork();
      deps.updatePasswordInput.value = "secret";
      deps.updatePasswordInput.dispatchEvent(new Event("input"));
      deps.updateTransportWifiRadio.checked = false;
      deps.updateTransportUsbRadio.checked = true;
      deps.updateTransportUsbRadio.dispatchEvent(new Event("change"));

      expect(deps.updateTransportOptions.hidden).toBe(false);
      expect(deps.updateWifiFields.hidden).toBe(true);
      expect(deps.updateStartBtn.disabled).toBe(false);
      expect(deps.updateReadinessSummary.innerHTML).toContain(
        "settings.update.readiness.item.connection_usb_ready",
      );
      expect(deps.updateDetailsCaption.textContent).toBe(
        "settings.update.details_caption_usb",
      );
      expect(deps.updateTransportNote.textContent).toBe(
        "settings.update.preflight_note_usb",
      );
      expect(deps.updateUsbTransportSummary.textContent).toBe(
        "settings.update.transport.usb_summary_interface",
      );
      expect(
        deps.updateTransportChoiceWifi.getAttribute("data-selected"),
      ).toBeNull();
      expect(
        deps.updateTransportChoiceWifi.getAttribute("data-choice-state"),
      ).toBeNull();
      expect(
        deps.updateTransportChoiceWifi.getAttribute("data-choice-badge"),
      ).toBeNull();
      expect(deps.updateTransportChoiceUsb.getAttribute("data-selected")).toBe(
        "true",
      );
      expect(
        deps.updateTransportChoiceUsb.getAttribute("data-choice-state"),
      ).toBe("active");
      expect(
        deps.updateTransportChoiceUsb.getAttribute("data-choice-badge"),
      ).toBe("settings.update.transport.selected_badge");
      expect(
        deps.updateTransportChoiceUsb.getAttribute("data-disabled"),
      ).toBeNull();
      expect((deps.internetStatusPanel as HTMLElement).innerHTML).toContain(
        "usb0",
      );

      deps.updateStartBtn.click();
      await flushAsyncWork();

      expect(JSON.parse(startBody)).toEqual({
        transport: "usb_internet",
        password: "",
      });
    } finally {
      restoreFetch();
    }
  });

  test("cancel replaces the previous update poll timeout instead of creating a second chain", async () => {
    const timers = installTimerHarness();
    const restoreFetch = installFetchMock(async (url, method) => {
      if (url.pathname === "/api/update/cancel" && method === "POST") {
        return jsonResponse({ status: "cancelled" });
      }
      if (url.pathname === "/api/update/status") {
        return jsonResponse(createIdleUpdateStatus());
      }
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.bindUpdateHandlers();
      feature.startPolling();
      await expectTimerDelays(timers, [10_000]);

      deps.updateCancelBtn.click();
      await expectTimerDelays(timers, [10_000]);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });

  test("stopPolling prevents an in-flight update poll from reviving the loop", async () => {
    const timers = installTimerHarness();
    const deferredStatus = createDeferred<Response>();
    const restoreFetch = installFetchMock(async (url) => {
      if (url.pathname === "/api/update/status") return deferredStatus.promise;
      if (url.pathname === "/api/health") {
        return jsonResponse(createHealthyUpdateStatus());
      }
      if (url.pathname === "/api/update/internet-status") {
        return jsonResponse(createUsbInternetStatus());
      }
      return jsonResponse({});
    });

    try {
      const deps = createUpdateDeps();
      const feature = createUpdateFeature(deps);

      feature.startPolling();
      await expectTimerDelays(timers, [10_000]);

      feature.stopPolling();
      deferredStatus.resolve(jsonResponse(createIdleUpdateStatus()));
      await expectTimerDelays(timers, []);
    } finally {
      restoreFetch();
      timers.restore();
    }
  });
});
