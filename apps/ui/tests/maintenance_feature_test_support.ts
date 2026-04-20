import { expect } from "@playwright/test";

import { createEspFlashFeature } from "../src/app/features/esp_flash_feature";
import { createUpdateFeature } from "../src/app/features/update_feature";
import { effect, signal, type ReadonlySignal } from "../src/app/ui_signals";
import type {
  EspSerialPortPayload,
  HealthStatusPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../src/api/types";
import type {
  EspFlashPanelActionHandlers,
  EspFlashPanelDom,
  EspFlashPanelRenderModel,
} from "../src/app/views/esp_flash_panel";
import type {
  InternetPanelActionHandlers,
  InternetPanelRenderModel,
} from "../src/app/views/internet_panel";
import type {
  UpdatePanelActionHandlers,
  UpdatePanelRenderModel,
} from "../src/app/views/update_panel";
import { flushAsyncWork, installWindowGlobal } from "./async_test_helpers";
import type { TimerHarness } from "./async_test_helpers";
import { createPanel, installFakeDomGlobals } from "./dom_render_test_support";
import { http } from "./msw/http";
import { createUiMswTestScope } from "./msw/node";

type ClickListener = (() => void) | null;

type ReadinessPanelModel = {
  items: readonly { detail: string; label: string; state: string }[];
  stateLabel: string | null;
  stateVariant: string | null;
  summary: string;
  title: string;
};

type UpdatePanelDomHarness = {
  updateOverviewPanel: HTMLElement | null;
  updateStartBtn: HTMLButtonElement;
  updateCancelBtn: HTMLButtonElement;
  updateStatusPanel: HTMLElement;
};

type InternetPanelDomHarness = {
  internetStatusPanel: HTMLElement | null;
  updateTransportOptions: HTMLElement | null;
  updateTransportChoiceWifi: HTMLElement | null;
  updateTransportChoiceUsb: HTMLElement | null;
  updateWifiFields: HTMLElement | null;
  updateReadinessSummary: HTMLElement | null;
  updateDetailsCaption: HTMLElement | null;
  updateTransportNote: HTMLElement | null;
  updateTransportWifiRadio: HTMLInputElement | null;
  updateTransportUsbRadio: HTMLInputElement | null;
  updateUsbTransportSummary: HTMLElement | null;
  updateSsidInput: HTMLInputElement | null;
  updatePasswordInput: HTMLInputElement | null;
  updateTogglePasswordBtn: HTMLButtonElement | null;
};

function bindReactiveModel<T>(
  model: ReadonlySignal<T>,
  renderModel: (value: T) => void,
): void {
  effect(() => {
    renderModel(model.value);
  });
}

function pendingPollDelays(timers: TimerHarness): number[] {
  return timers.pendingDelays().filter((delay) => delay !== 10_000);
}

export function installFeatureFetchMock(
  handler: (
    url: URL,
    method: string,
    body: string,
  ) => Promise<Response> | Response,
): () => void {
  const scope = createUiMswTestScope();
  scope.server.use(
    http.all("*", async ({ request }) => {
      const requestBody =
        request.method === "GET" || request.method === "HEAD"
          ? ""
          : await request.text();
      return await handler(new URL(request.url), request.method, requestBody);
    }),
  );

  return () => {
    scope.close();
  };
}

function createButton(): HTMLButtonElement {
  let onClick: ClickListener = null;

  return {
    disabled: false,
    hidden: false,
    textContent: "",
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
    checked: false,
    disabled: false,
    focus() {},
    type,
    value,
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
  element: {
    removeAttribute(name: string): void;
    setAttribute(name: string, value: string): void;
  },
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
  const bodyHtml =
    model.rows.length > 0
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
  const stagesHtml = model.stages
    .map(
      (stage) =>
        `<li class="maintenance-stage" data-stage-phase="${stage.phase}" data-stage-state="${stage.state}"${stage.current ? ' aria-current="step"' : ""}><span class="maintenance-stage__marker">${stage.markerText}</span><div class="maintenance-stage__body"><div class="maintenance-stage__title">${stage.titleText}</div><div class="maintenance-stage__detail">${stage.detailText}</div></div><span class="maintenance-stage__state">${stage.stateText}</span></li>`,
    )
    .join("");
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
  dom: UpdatePanelDomHarness,
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

function serializeReadinessPanel(model: ReadinessPanelModel): string {
  const itemsHtml = model.items
    .map(
      (item) =>
        `<li class="maintenance-readiness__item" data-readiness-state="${item.state}"><span class="maintenance-readiness__marker" aria-hidden="true">${item.state === "ready" ? "✓" : "!"}</span><div class="maintenance-readiness__body"><div class="maintenance-readiness__label">${item.label}</div><div class="maintenance-readiness__detail">${item.detail}</div></div></li>`,
    )
    .join("");
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
  dom: InternetPanelDomHarness,
  model: InternetPanelRenderModel,
): void {
  if (dom.internetStatusPanel) {
    dom.internetStatusPanel.innerHTML = serializeInternetStatusPanel(
      model.internetStatus,
    );
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
    dom.updateTransportWifiRadio.checked =
      model.transportChoices.wifi.selected;
    dom.updateTransportWifiRadio.disabled =
      model.transportChoices.wifi.inputDisabled;
  }
  if (dom.updateTransportUsbRadio) {
    dom.updateTransportUsbRadio.checked =
      model.transportChoices.usb_internet.selected;
    dom.updateTransportUsbRadio.disabled =
      model.transportChoices.usb_internet.inputDisabled;
  }
  if (dom.updateWifiFields) {
    dom.updateWifiFields.hidden = model.wifiFieldsHidden;
  }
  if (dom.updateReadinessSummary) {
    dom.updateReadinessSummary.innerHTML = serializeReadinessPanel(
      model.readiness,
    );
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
  const stagesHtml = model.stages
    .map(
      (stage) =>
        `<li class="maintenance-stage" data-stage-phase="${stage.phase}" data-stage-state="${stage.state}"${stage.current ? ' aria-current="step"' : ""}><span class="maintenance-stage__marker">${stage.markerText}</span><div class="maintenance-stage__body"><div class="maintenance-stage__title">${stage.titleText}</div><div class="maintenance-stage__detail">${stage.detailText}</div></div><span class="maintenance-stage__state">${stage.stateText}</span></li>`,
    )
    .join("");
  return `<div class="maintenance-journey">${noteHtml}<ol class="maintenance-stage-list">${stagesHtml}</ol></div>`;
}

function serializeInlineEmptyState(model: {
  bodyText: string;
  titleText: string;
}): string {
  return `<div class="empty-state empty-state--inline"><strong class="empty-state__title">${model.titleText}</strong><span class="empty-state__body">${model.bodyText}</span></div>`;
}

function serializeEspFlashLog(model: EspFlashPanelRenderModel["log"]): string {
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
    dom.espFlashPortSelect.innerHTML = model.portOptions
      .map(
        (option) =>
          `<option value="${option.value}">${option.labelText}</option>`,
      )
      .join("");
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
    dom.espFlashStartSummary.innerHTML = serializeReadinessPanel(
      model.startSummary,
    );
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
    dom.espFlashReadinessPanel.innerHTML = serializeEspFlashReadinessPanel(
      model.readiness,
    );
  }
  if (dom.espFlashJourneyPanel) {
    dom.espFlashJourneyPanel.innerHTML = serializeEspFlashJourney(
      model.journey,
    );
  }
  if (dom.espFlashLogPanel) {
    dom.espFlashLogPanel.className = model.log.emptyState
      ? "maintenance-log-slot"
      : "maintenance-log-slot maintenance-log-panel";
    dom.espFlashLogPanel.innerHTML = serializeEspFlashLog(model.log);
  }
  if (dom.espFlashHistoryPanel) {
    dom.espFlashHistoryPanel.innerHTML = serializeEspFlashHistory(
      model.history,
    );
  }
}

function createFeatureNavigationHarness(defaultTabId: string) {
  const activeViewId = signal("settingsView");
  const activeSettingsTabId = signal(defaultTabId);

  return {
    ports: {
      activeViewId,
      activeSettingsTabId,
    },
    setActiveSettingsTabId(nextTabId: string) {
      activeSettingsTabId.value = nextTabId;
    },
    setActiveViewId(nextViewId: string) {
      activeViewId.value = nextViewId;
    },
  };
}

function createEspFlashFeatureDeps() {
  const navigation = createFeatureNavigationHarness("espFlashTab");
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

  const panel = {
    actions: signal<EspFlashPanelActionHandlers | null>(null),
    model: signal<ReadonlySignal<EspFlashPanelRenderModel> | null>(null),
  };

  effect(() => {
    const handlers = panel.actions.value;
    if (!handlers) {
      return;
    }
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
  });

  effect(() => {
    const model = panel.model.value;
    if (!model) {
      return;
    }
    bindReactiveModel(model, (nextModel) => {
      renderEspFlashPanelDom(dom, nextModel);
    });
  });

  return {
    panel,
    ports: navigation.ports,
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
      requestConfirmation: async () => true,
      showError: () => {},
    },
    setActiveSettingsTabId: navigation.setActiveSettingsTabId,
    setActiveViewId: navigation.setActiveViewId,
  };
}

function createUpdateFeatureDeps() {
  const navigation = createFeatureNavigationHarness("updateTab");
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
  } satisfies InternetPanelDomHarness;

  const dom = {
    updateOverviewPanel,
    updateStartBtn,
    updateCancelBtn,
    updateStatusPanel,
  } satisfies UpdatePanelDomHarness;

  const updatePanel = {
    actions: signal<UpdatePanelActionHandlers | null>(null),
    model: signal<ReadonlySignal<UpdatePanelRenderModel> | null>(null),
  };
  const internetPanel = {
    actions: signal<InternetPanelActionHandlers | null>(null),
    model: signal<ReadonlySignal<InternetPanelRenderModel> | null>(null),
    focusSsidInput() {
      internetDom.updateSsidInput?.focus();
    },
  };

  effect(() => {
    const handlers = updatePanel.actions.value;
    if (!handlers) {
      return;
    }
    dom.updateStartBtn.addEventListener("click", () => {
      handlers.onStart();
    });
    dom.updateCancelBtn.addEventListener("click", () => {
      handlers.onCancel();
    });
  });

  effect(() => {
    const model = updatePanel.model.value;
    if (!model) {
      return;
    }
    bindReactiveModel(model, (nextModel) => {
      renderUpdatePanelDom(dom, nextModel);
    });
  });

  effect(() => {
    const handlers = internetPanel.actions.value;
    if (!handlers) {
      return;
    }
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
  });

  effect(() => {
    const model = internetPanel.model.value;
    if (!model) {
      return;
    }
    bindReactiveModel(model, (nextModel) => {
      renderInternetPanelDom(internetDom, nextModel);
    });
  });

  return {
    panels: {
      update: updatePanel,
      internet: internetPanel,
    },
    ports: navigation.ports,
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
      requestConfirmation: async () => true,
      showError: () => {},
    },
    setActiveSettingsTabId: navigation.setActiveSettingsTabId,
    setActiveViewId: navigation.setActiveViewId,
  };
}

export function installMaintenanceFeatureGlobals(): () => void {
  const restoreDomGlobals = installFakeDomGlobals();
  installWindowGlobal();
  return restoreDomGlobals;
}

export async function expectPollDelays(
  timers: TimerHarness,
  expected: number[],
): Promise<void> {
  for (let attempt = 0; attempt < 25; attempt += 1) {
    const actual = pendingPollDelays(timers);
    if (
      actual.length === expected.length &&
      actual.every((delay, index) => delay === expected[index])
    ) {
      return;
    }
    await flushAsyncWork(1);
  }
  expect(pendingPollDelays(timers)).toEqual(expected);
}

export async function expectTimerDelays(
  timers: TimerHarness,
  expected: number[],
): Promise<void> {
  for (let attempt = 0; attempt < 25; attempt += 1) {
    const actual = timers.pendingDelays();
    if (
      actual.length === expected.length &&
      actual.every((delay, index) => delay === expected[index])
    ) {
      return;
    }
    await flushAsyncWork(1);
  }
  expect(timers.pendingDelays()).toEqual(expected);
}

export function createEspFlashPort(
  overrides: Partial<EspSerialPortPayload> = {},
): EspSerialPortPayload {
  return {
    description: "USB UART",
    pid: 2,
    port: "/dev/ttyUSB0",
    serial_number: "abc",
    vid: 1,
    ...overrides,
  };
}

export function createIdleUpdateStatus(
  overrides: Partial<UpdateStatusPayload> = {},
): UpdateStatusPayload {
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
    ...overrides,
  };
}

export function createHealthyUpdateStatus(
  overrides: Partial<HealthStatusPayload> = {},
): HealthStatusPayload {
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
    ...overrides,
  };
}

export function createUsbInternetStatus(
  overrides: Partial<UsbInternetStatusPayload> = {},
): UsbInternetStatusPayload {
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

export function createEspFlashFeatureHarness() {
  const deps = createEspFlashFeatureDeps();
  return {
    deps,
    feature: createEspFlashFeature(deps),
  };
}

export function createUpdateFeatureHarness() {
  const deps = createUpdateFeatureDeps();
  return {
    deps,
    feature: createUpdateFeature(deps),
  };
}
