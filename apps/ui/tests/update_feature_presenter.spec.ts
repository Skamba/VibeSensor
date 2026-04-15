import { expect, test } from "@playwright/test";

import type { InternetPanelRenderModel } from "../src/app/views/internet_panel";
import type { UpdatePanelRenderModel } from "../src/app/views/update_panel";
import {
  buildUpdateFeaturePanelModels,
  createUpdateFeaturePresenter,
} from "../src/app/views/update_feature_presenter";
import type {
  HealthStatusPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../src/transport/http_models";

function t(key: string, vars?: Record<string, unknown>): string {
  if (!vars || Object.keys(vars).length === 0) {
    return key;
  }
  return `${key}:${JSON.stringify(vars)}`;
}

function makeStatus(
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

function makeHealth(
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

function makeInternet(
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
    diagnostic: "settings.internet.load_failed",
    ...overrides,
  };
}

test.describe("buildUpdateFeaturePanelModels", () => {
  test("keeps the Wi-Fi path active while readiness is blocked by a missing SSID", () => {
    const models = buildUpdateFeaturePanelModels(
      {
        internetStatus: makeInternet(),
        healthStatus: makeHealth(),
        updateStatus: makeStatus(),
        updateState: "idle",
        updateTransport: "wifi",
      },
      {
        passwordInputValue: "",
        passwordVisible: false,
        selectedTransport: "wifi",
        ssidInputValue: "",
      },
      { t },
    );

    expect(models.canStart).toBe(false);
    expect(models.transport).toBe("wifi");
    expect(models.updatePanel).toMatchObject({
      startButtonDisabled: true,
      startButtonHidden: false,
      startButtonLabelText: "settings.update.start",
      cancelButtonHidden: true,
    });
    expect(models.internetPanel.transportChoices.wifi).toEqual({
      badgeText: "settings.update.transport.selected_badge",
      disabled: false,
      inputDisabled: false,
      selected: true,
      state: "active",
      summaryText: "settings.update.transport.wifi_summary",
    });
    expect(models.internetPanel.transportChoices.usb_internet).toEqual({
      badgeText: null,
      disabled: true,
      inputDisabled: true,
      selected: false,
      state: null,
      summaryText: "settings.update.transport.usb_summary_unavailable",
    });
    expect(models.internetPanel.readiness.summary).toBe(
      "settings.update.readiness.summary_blocked",
    );
    expect(models.internetPanel.readiness.items).toContainEqual({
      label: "settings.update.readiness.item.connection",
      detail: "settings.update.readiness.item.connection_wifi_blocked",
      state: "blocked",
    });
    expect(models.internetPanel.detailsCaptionText).toBe(
      "settings.update.details_caption_wifi",
    );
    expect(models.internetPanel.transportNoteText).toBe(
      "settings.update.preflight_note_wifi",
    );
    expect(models.internetPanel.passwordInputType).toBe("password");
    expect(models.internetPanel.togglePasswordLabelText).toBe(
      "settings.update.show_password",
    );
  });

  test("builds the retry/update recovery surface for a failed USB attempt", () => {
    const models = buildUpdateFeaturePanelModels(
      {
        internetStatus: makeInternet({
          detected: true,
          usable: true,
          interface_name: "usb0",
          diagnostic: "USB internet ready",
        }),
        healthStatus: makeHealth(),
        updateStatus: makeStatus({
          state: "failed",
          phase: "downloading",
          transport: "usb_internet",
          uplink_interface: "usb0",
          issues: [
            {
              phase: "downloading",
              message: "GitHub release download timed out",
              detail: "Upstream connectivity dropped during fetch.",
            },
          ],
          started_at: 1,
          finished_at: 2,
          exit_code: 28,
        }),
        updateState: "failed",
        updateTransport: "usb_internet",
      },
      {
        passwordInputValue: "secret",
        passwordVisible: true,
        selectedTransport: "usb_internet",
        ssidInputValue: "",
      },
      { t },
    );

    expect(models.canStart).toBe(true);
    expect(models.transport).toBe("usb_internet");
    expect(models.updatePanel.startButtonLabelText).toBe("settings.update.retry");
    expect(models.updatePanel.status?.journey.failureNote).toEqual({
      summaryText: "downloading — GitHub release download timed out",
      detailText: "Upstream connectivity dropped during fetch.",
      recoveryTitleText: "settings.update.recovery.network.title",
      recoveryDetailText: "settings.update.recovery.network.detail",
    });
    expect(
      models.updatePanel.status?.journey.stages.find(
        (stage) => stage.phase === "downloading",
      ),
    ).toMatchObject({
      state: "attention",
      current: false,
    });
    expect(models.updatePanel.status?.latestAttempt).not.toBeNull();
    expect(models.internetPanel.transportChoices.usb_internet).toMatchObject({
      badgeText: "settings.update.transport.selected_badge",
      disabled: false,
      inputDisabled: false,
      selected: true,
      state: "active",
    });
    expect(models.internetPanel.transportChoices.usb_internet.summaryText).toContain(
      "settings.update.transport.usb_summary_interface",
    );
    expect(models.internetPanel.readiness.title).toBe(
      "settings.update.recovery.title",
    );
    expect(models.internetPanel.internetStatus).toMatchObject({
      titleText: "settings.internet.card_title",
      summaryText: "settings.internet.summary.usable",
      badge: {
        variant: "ok",
        text: "settings.internet.state.usable",
      },
    });
    expect(models.internetPanel.passwordInputType).toBe("text");
    expect(models.internetPanel.togglePasswordLabelText).toBe(
      "settings.update.hide_password",
    );
  });
});

test.describe("createUpdateFeaturePresenter", () => {
  test("reads and clears presenter-owned form state instead of DOM values", () => {
    let latestInternetPanel: InternetPanelRenderModel | null = null;
    let latestUpdatePanel: UpdatePanelRenderModel | null = null;
    let focusCalls = 0;
    const presenter = createUpdateFeaturePresenter({
      internetPanel: {
        dom: {
          internetStatusPanel: null,
          updateTransportOptions: null,
          updateTransportChoiceWifi: null,
          updateTransportChoiceUsb: null,
          updateWifiFields: null,
          updateReadinessSummary: null,
          updateDetailsCaption: null,
          updateTransportNote: null,
          updateTransportWifiRadio: { checked: false } as HTMLInputElement,
          updateTransportUsbRadio: { checked: true } as HTMLInputElement,
          updateUsbTransportSummary: null,
          updateSsidInput: {
            focus() {
              focusCalls += 1;
            },
            value: "dom-ssid",
          } as HTMLInputElement,
          updatePasswordInput: {
            value: "dom-password",
          } as HTMLInputElement,
          updateTogglePasswordBtn: null,
        },
        bindActions() {},
        setModel(model) {
          latestInternetPanel = model;
        },
      },
      panel: {
        dom: {
          updateOverviewPanel: null,
          updateStartBtn: {} as HTMLButtonElement,
          updateCancelBtn: {} as HTMLButtonElement,
          updateStatusPanel: {} as HTMLElement,
        },
        bindActions() {},
        setModel(model) {
          latestUpdatePanel = model;
        },
      },
      t,
    });
    const state = {
      internetStatus: makeInternet({
        detected: true,
        usable: true,
        interface_name: "usb0",
      }),
      healthStatus: makeHealth(),
      updateStatus: makeStatus(),
      updateState: "idle" as const,
      updateTransport: "wifi" as const,
    };

    presenter.setSelectedTransport("wifi");
    presenter.setSsidInput("presenter-ssid");
    presenter.setPasswordInput("presenter-password");
    presenter.render(state);

    expect(latestInternetPanel?.ssidInputValue).toBe("presenter-ssid");
    expect(latestInternetPanel?.passwordInputValue).toBe("presenter-password");
    expect(latestUpdatePanel?.startButtonDisabled).toBe(false);
    expect(presenter.readStartIntent(state)).toMatchObject({
      password: "presenter-password",
      ssid: "presenter-ssid",
      transport: "wifi",
    });

    presenter.clearPassword();
    expect(latestInternetPanel?.passwordInputValue).toBe("");
    expect(presenter.readStartIntent(state)).toMatchObject({
      password: "",
      ssid: "presenter-ssid",
      transport: "wifi",
    });

    presenter.focusSsidInput();
    expect(focusCalls).toBe(1);
  });
});
