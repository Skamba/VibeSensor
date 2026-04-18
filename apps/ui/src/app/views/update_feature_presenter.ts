import type {
  HealthStatusPayload,
  UpdateStartRequestPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../../api/types";
import type {
  InternetPanelRenderModel,
  UpdateTransportChoiceCardRenderModel,
} from "./internet_panel";
import {
  buildInternetStatusPanelModel,
  formatUsbInternetSummary,
} from "./internet_status_view";
import type { MaintenanceReadinessPanelModel } from "./maintenance_readiness_view";
import type {
  UpdatePanelRenderModel,
} from "./update_panel";
import {
  buildUpdateStatusPanelViewModel,
} from "./update_status_builders";
import {
  getUpdateFailureSummary,
} from "./update_journey_builder";
import {
  batch,
  computed,
  effectOnChange,
  signal,
  untracked,
  type ReadonlySignal,
} from "../ui_signals";

export interface UpdateFeatureRenderState {
  internetStatus: UsbInternetStatusPayload;
  healthStatus: HealthStatusPayload | null;
  updateStatus: UpdateStatusPayload | null;
  updateState: UpdateStatusPayload["state"];
  updateTransport: UpdateStartRequestPayload["transport"];
}

export interface UpdateFeatureStartIntent {
  canStart: boolean;
  password: string;
  ssid: string;
  transport: UpdateStartRequestPayload["transport"];
  usbAvailable: boolean;
}

export interface UpdateFeatureFormSnapshot {
  passwordInputValue: string;
  passwordVisible: boolean;
  selectedTransport: UpdateStartRequestPayload["transport"];
  ssidInputValue: string;
}

interface UpdateFeatureActionSummary {
  canStart: boolean;
  panelModel: MaintenanceReadinessPanelModel;
  startLabel: string;
  transport: UpdateStartRequestPayload["transport"];
}

export interface UpdateFeaturePanelModels {
  canStart: boolean;
  internetPanel: InternetPanelRenderModel;
  transport: UpdateStartRequestPayload["transport"];
  updatePanel: UpdatePanelRenderModel;
}

export interface UpdateFeaturePresenterDeps {
  renderState: ReadonlySignal<UpdateFeatureRenderState>;
  t: (key: string, vars?: Record<string, unknown>) => string;
}

export interface UpdateFeaturePresenter {
  readonly internetPanelModel: ReadonlySignal<InternetPanelRenderModel>;
  readonly updatePanelModel: ReadonlySignal<UpdatePanelRenderModel>;
  setPasswordInput(value: string): void;
  setSelectedTransport(transport: UpdateStartRequestPayload["transport"]): void;
  setSsidInput(value: string): void;
  readStartIntent(): UpdateFeatureStartIntent;
  togglePassword(): void;
  clearPassword(): void;
}

function selectedTransport(
  state: UpdateFeatureRenderState,
  form: UpdateFeatureFormSnapshot,
): UpdateStartRequestPayload["transport"] {
  if (state.updateState === "running") {
    return state.updateTransport;
  }
  if (state.internetStatus.usable && form.selectedTransport === "usb_internet") {
    return "usb_internet";
  }
  return "wifi";
}

function hasBlockingHealthIssue(state: UpdateFeatureRenderState): boolean {
  const health = state.healthStatus;
  if (!health) {
    return false;
  }
  return (
    health.status === "degraded" ||
    health.persistence.write_error != null ||
    health.startup_error != null ||
    health.db_corruption_detected === true
  );
}

function buildActionSummary(
  state: UpdateFeatureRenderState,
  form: UpdateFeatureFormSnapshot,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdateFeatureActionSummary {
  const transport = selectedTransport(state, form);
  const usingUsb = transport === "usb_internet";
  const isRunning = state.updateState === "running";
  const ssid = form.ssidInputValue.trim();
  const usbInterface = state.internetStatus.interface_name;
  const readinessItems = [
    {
      label: t("settings.update.readiness.item.source"),
      detail: usingUsb
        ? t("settings.update.readiness.item.source_usb")
        : t("settings.update.readiness.item.source_wifi"),
      state: "ready" as const,
    },
    usingUsb
      ? {
          label: t("settings.update.readiness.item.connection"),
          detail: state.internetStatus.usable
            ? t("settings.update.readiness.item.connection_usb_ready", {
                interface: usbInterface || t("settings.update.transport.usb_title"),
              })
            : t("settings.update.readiness.item.connection_usb_blocked"),
          state: state.internetStatus.usable
            ? ("ready" as const)
            : ("blocked" as const),
        }
      : {
          label: t("settings.update.readiness.item.connection"),
          detail: ssid
            ? t("settings.update.readiness.item.connection_wifi_ready")
            : t("settings.update.readiness.item.connection_wifi_blocked"),
          state: ssid ? ("ready" as const) : ("blocked" as const),
        },
  ];
  if (hasBlockingHealthIssue(state)) {
    readinessItems.push({
      label: t("settings.update.readiness.item.health"),
      detail: t("settings.update.readiness.item.health_blocked"),
      state: "blocked",
    });
  }
  const hasBlockedItem = readinessItems.some((item) => item.state === "blocked");
  const failure = state.updateStatus
    ? getUpdateFailureSummary(state.updateStatus, t)
    : null;
  const isRecoveryState = failure !== null;
  const stateLabel = isRecoveryState
    ? hasBlockedItem
      ? t("maintenance.readiness.blocked")
      : t("settings.update.state.failed")
    : isRunning
      ? t("maintenance.readiness.running")
      : hasBlockedItem
        ? t("maintenance.readiness.blocked")
        : t("maintenance.readiness.ready");
  const items = failure
    ? [
        {
          label: t("settings.update.recovery.item.failed_step"),
          detail: failure.phaseLabel,
          state: "attention" as const,
        },
        {
          label: t("settings.update.recovery.item.captured_detail"),
          detail: failure.message
            ? failure.detail
              ? `${failure.message} — ${failure.detail}`
              : failure.message
            : failure.detail || failure.phaseLabel,
          state: "attention" as const,
        },
        {
          label: t("settings.update.recovery.item.next_step"),
          detail: hasBlockedItem
            ? t("settings.update.recovery.item.next_step_blocked")
            : `${failure.recoveryTitle} — ${failure.recoveryDetail}`,
          state: hasBlockedItem
            ? ("blocked" as const)
            : ("attention" as const),
        },
      ]
    : readinessItems;
  return {
    canStart: !isRunning && (isRecoveryState || !hasBlockedItem),
    startLabel: t(
      isRecoveryState ? "settings.update.retry" : "settings.update.start",
    ),
    transport,
    panelModel: {
      title: t(
        isRecoveryState
          ? "settings.update.recovery.title"
          : "settings.update.readiness.title",
      ),
      summary: t(
        isRecoveryState
          ? hasBlockedItem
            ? "settings.update.recovery.summary_blocked"
            : "settings.update.recovery.summary_retry"
          : isRunning
            ? "settings.update.readiness.summary_running"
            : hasBlockedItem
              ? "settings.update.readiness.summary_blocked"
              : "settings.update.readiness.summary_ready",
      ),
      stateLabel,
      stateVariant: isRecoveryState
        ? "bad"
        : isRunning
          ? "warn"
          : hasBlockedItem
            ? "bad"
            : "ok",
      items,
    },
  };
}

function buildTransportChoiceModel(
  t: (key: string, vars?: Record<string, unknown>) => string,
  options: {
    badgeSelected: boolean;
    visuallyDisabled: boolean;
  },
): UpdateTransportChoiceCardRenderModel {
  return {
    badgeText: options.badgeSelected
      ? t("settings.update.transport.selected_badge")
      : null,
    disabled: options.visuallyDisabled,
    inputDisabled: false,
    selected: options.badgeSelected,
    state: options.badgeSelected ? "active" : null,
    summaryText: "",
  };
}

function buildUpdatePanelRenderModel(
  state: UpdateFeatureRenderState,
  actionSummary: UpdateFeatureActionSummary,
  t: (key: string, vars?: Record<string, unknown>) => string,
): UpdatePanelRenderModel {
  const isRunning = state.updateState === "running";
  const status =
    state.updateStatus && state.healthStatus
      ? buildUpdateStatusPanelViewModel(state.updateStatus, state.healthStatus, {
          t,
          selectedTransport: actionSummary.transport,
        })
      : null;
  return {
    cancelButtonDisabled: !isRunning,
    cancelButtonHidden: !isRunning,
    startButtonDisabled: isRunning || !actionSummary.canStart,
    startButtonHidden: isRunning,
    startButtonLabelText: actionSummary.startLabel,
    status,
  };
}

function buildInternetPanelRenderModel(
  state: UpdateFeatureRenderState,
  form: UpdateFeatureFormSnapshot,
  actionSummary: UpdateFeatureActionSummary,
  t: (key: string, vars?: Record<string, unknown>) => string,
): InternetPanelRenderModel {
  const usbAvailable = state.internetStatus.usable;
  const controlsLocked = state.updateState === "running";
  const usingUsb = actionSummary.transport === "usb_internet";
  const wifiChoice = buildTransportChoiceModel(t, {
    badgeSelected: !usingUsb,
    visuallyDisabled: false,
  });
  const usbChoice = buildTransportChoiceModel(t, {
    badgeSelected: usingUsb,
    visuallyDisabled: !usbAvailable && !controlsLocked,
  });
  wifiChoice.inputDisabled = controlsLocked;
  wifiChoice.summaryText = t("settings.update.transport.wifi_summary");
  usbChoice.inputDisabled = controlsLocked || !usbAvailable;
  usbChoice.summaryText = usbAvailable
    ? formatUsbInternetSummary(state.internetStatus, t)
    : t("settings.update.transport.usb_summary_unavailable");
  return {
    controlsLocked,
    detailsCaptionText: t(
      usingUsb
        ? "settings.update.details_caption_usb"
        : "settings.update.details_caption_wifi",
    ),
    internetStatus:
      state.updateStatus && state.healthStatus
        ? buildInternetStatusPanelModel(state.internetStatus, { t })
        : null,
    passwordInputType: form.passwordVisible ? "text" : "password",
    passwordInputValue: form.passwordInputValue,
    readiness: actionSummary.panelModel,
    selectedTransport: actionSummary.transport,
    ssidInputValue: form.ssidInputValue,
    togglePasswordDisabled: controlsLocked,
    togglePasswordLabelText: t(
      form.passwordVisible
        ? "settings.update.hide_password"
        : "settings.update.show_password",
    ),
    transportChoices: {
      usb_internet: usbChoice,
      wifi: wifiChoice,
    },
    transportNoteText: t(
      usingUsb
        ? "settings.update.preflight_note_usb"
        : "settings.update.preflight_note_wifi",
    ),
    wifiFieldsHidden: usingUsb,
  };
}

export function buildUpdateFeaturePanelModels(
  state: UpdateFeatureRenderState,
  form: UpdateFeatureFormSnapshot,
  deps: Pick<UpdateFeaturePresenterDeps, "t">,
): UpdateFeaturePanelModels {
  const actionSummary = buildActionSummary(state, form, deps.t);
  return {
    canStart: actionSummary.canStart,
    internetPanel: buildInternetPanelRenderModel(state, form, actionSummary, deps.t),
    transport: actionSummary.transport,
    updatePanel: buildUpdatePanelRenderModel(state, actionSummary, deps.t),
  };
}

export function createUpdateFeaturePresenter(
  ctx: UpdateFeaturePresenterDeps,
): UpdateFeaturePresenter {
  const { renderState, t } = ctx;
  const passwordInputValue = signal("");
  const passwordVisible = signal(false);
  const selectedTransportInput = signal<UpdateStartRequestPayload["transport"]>("wifi");
  const ssidInputValue = signal("");
  let hasHydratedPersistedWifiSettings = false;

  function syncDerivedFormState(state: UpdateFeatureRenderState): void {
    const currentSelectedTransport = untracked(() => selectedTransportInput.value);
    const currentSsid = untracked(() => ssidInputValue.value);
    let nextSelectedTransport: UpdateStartRequestPayload["transport"] | null = null;
    let nextSsid: string | null = null;

    if (!hasHydratedPersistedWifiSettings && state.updateStatus != null) {
      hasHydratedPersistedWifiSettings = true;
      if (
        state.updateStatus.transport === "wifi"
        && state.updateStatus.ssid
        && currentSsid.trim().length === 0
      ) {
        nextSsid = state.updateStatus.ssid;
      }
    }

    if (state.updateState === "running" && currentSelectedTransport !== state.updateTransport) {
      nextSelectedTransport = state.updateTransport;
    }

    if (nextSelectedTransport !== null || nextSsid !== null) {
      batch(() => {
        if (nextSelectedTransport !== null) {
          selectedTransportInput.value = nextSelectedTransport;
        }
        if (nextSsid !== null) {
          ssidInputValue.value = nextSsid;
        }
      });
    }
  }

  syncDerivedFormState(renderState.peek());
  effectOnChange(renderState, (state) => {
    syncDerivedFormState(state);
  });

  const actionSummaryModel = computed(() =>
    buildActionSummary(
      renderState.value,
      {
        passwordInputValue: "",
        passwordVisible: false,
        selectedTransport: selectedTransportInput.value,
        ssidInputValue: ssidInputValue.value,
      },
      t,
    )
  );
  const internetPanelModel = computed(() =>
    buildInternetPanelRenderModel(
      renderState.value,
      {
        passwordInputValue: passwordInputValue.value,
        passwordVisible: passwordVisible.value,
        selectedTransport: selectedTransportInput.value,
        ssidInputValue: ssidInputValue.value,
      },
      actionSummaryModel.value,
      t,
    )
  );
  const updatePanelModel = computed(() =>
    buildUpdatePanelRenderModel(renderState.value, actionSummaryModel.value, t)
  );

  function readStartIntent(): UpdateFeatureStartIntent {
    const currentRenderState = renderState.value;
    const currentActionSummary = actionSummaryModel.value;
    return {
      canStart: currentActionSummary.canStart,
      password: passwordInputValue.value,
      ssid: ssidInputValue.value.trim(),
      transport: currentActionSummary.transport,
      usbAvailable: currentRenderState.internetStatus.usable,
    };
  }

  return {
    internetPanelModel,
    updatePanelModel,
    setPasswordInput(value) {
      passwordInputValue.value = value;
    },
    setSelectedTransport(transport) {
      selectedTransportInput.value = transport;
    },
    setSsidInput(value) {
      ssidInputValue.value = value;
    },
    readStartIntent,
    togglePassword() {
      passwordVisible.value = !passwordVisible.value;
    },
    clearPassword() {
      passwordInputValue.value = "";
    },
  };
}
