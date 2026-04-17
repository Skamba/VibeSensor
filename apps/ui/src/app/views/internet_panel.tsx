import { render, type ComponentChildren } from "preact";
import { useRef } from "preact/hooks";

import type { UpdateStartRequestPayload } from "../../api/types";
import type { ChoiceCardState } from "../view_style_types";
import { getUiText as t } from "../ui_i18n";
import {
  signal,
  useSignalEffect,
  type ReadonlySignal,
} from "../ui_signals";
import type {
  MaintenanceReadinessItem,
  MaintenanceReadinessPanelModel,
} from "./maintenance_readiness_view";
import type { InternetStatusPanelModel } from "./internet_status_view";
import type {
  UpdateStatusBadgeModel,
  UpdateStatusRowModel,
} from "./update_status_models";

export interface UpdateTransportChoiceCardRenderModel {
  badgeText: string | null;
  disabled: boolean;
  inputDisabled: boolean;
  selected: boolean;
  state: ChoiceCardState | null;
  summaryText: string;
}

export interface InternetPanelRenderModel {
  controlsLocked: boolean;
  detailsCaptionText: string;
  internetStatus: InternetStatusPanelModel | null;
  passwordInputType: "password" | "text";
  passwordInputValue: string;
  readiness: MaintenanceReadinessPanelModel;
  selectedTransport: UpdateStartRequestPayload["transport"];
  ssidInputValue: string;
  togglePasswordDisabled: boolean;
  togglePasswordLabelText: string;
  transportChoices: Record<
    UpdateStartRequestPayload["transport"],
    UpdateTransportChoiceCardRenderModel
  >;
  transportNoteText: string;
  wifiFieldsHidden: boolean;
}

export interface InternetPanelActionHandlers {
  onPasswordInput(value: string): void;
  onSsidInput(value: string): void;
  onTogglePassword(): void;
  onTransportChange(transport: UpdateStartRequestPayload["transport"]): void;
}

export interface InternetPanelView {
  bindActions(handlers: InternetPanelActionHandlers): void;
  bindModel(model: ReadonlySignal<InternetPanelRenderModel>): void;
  focusSsidInput(): void;
}

type InternetPanelBridgeState = {
  actions: InternetPanelActionHandlers | null;
  model: ReadonlySignal<InternetPanelRenderModel> | null;
};

type InternetPanelFocusRequest = {
  field: "ssid";
  token: number;
};

const DEFAULT_INTERNET_PANEL_MODEL: InternetPanelRenderModel = {
  controlsLocked: false,
  detailsCaptionText: "",
  internetStatus: null,
  passwordInputType: "password",
  passwordInputValue: "",
  readiness: {
    title: "Start readiness",
    summary: "",
    stateLabel: "",
    stateVariant: "muted",
    items: [],
  },
  selectedTransport: "wifi",
  ssidInputValue: "",
  togglePasswordDisabled: false,
  togglePasswordLabelText: "Show",
  transportChoices: {
    usb_internet: {
      badgeText: null,
      disabled: true,
      inputDisabled: true,
      selected: false,
      state: null,
      summaryText: "USB internet is not ready yet.",
    },
    wifi: {
      badgeText: "Selected",
      disabled: false,
      inputDisabled: false,
      selected: true,
      state: "active",
      summaryText:
        "Pause the hotspot, join a Wi-Fi network, install, then restore the hotspot.",
    },
  },
  transportNoteText: "",
  wifiFieldsHidden: false,
};

function UpdateBadge(props: { badge: UpdateStatusBadgeModel }) {
  const { badge } = props;
  return (
    <span class="pill" data-variant={badge.variant}>
      {badge.text}
    </span>
  );
}

function StatusGrid(props: { rows: readonly UpdateStatusRowModel[] }) {
  const { rows } = props;
  return (
    <div class="status-grid">
      {rows.map((row) => (
        <div class="status-grid__row" key={`${row.labelText}:${row.valueText}`}>
          <span class="status-grid__label">{row.labelText}</span>
          <span>{row.valueText}</span>
        </div>
      ))}
    </div>
  );
}

function MaintenanceCard(props: {
  badge?: UpdateStatusBadgeModel | null;
  children: ComponentChildren;
  subtitleText: string;
  titleText: string;
}) {
  const { badge, children, subtitleText, titleText } = props;
  return (
    <section class="maintenance-card">
      <div class="maintenance-card__header">
        <div>
          <div class="maintenance-card__title">{titleText}</div>
          <div class="subtle">{subtitleText}</div>
        </div>
        {badge ? <UpdateBadge badge={badge} /> : null}
      </div>
      <div class="maintenance-card__body">{children}</div>
    </section>
  );
}

function MaintenanceReadinessItemRow(props: {
  item: MaintenanceReadinessItem;
}) {
  const { item } = props;
  const marker = item.state === "ready" ? "\u2713" : "!";
  return (
    <li
      class="maintenance-readiness__item"
      data-readiness-state={item.state}
    >
      <span class="maintenance-readiness__marker" aria-hidden="true">
        {marker}
      </span>
      <div class="maintenance-readiness__body">
        <div class="maintenance-readiness__label">{item.label}</div>
        <div class="maintenance-readiness__detail">{item.detail}</div>
      </div>
    </li>
  );
}

function MaintenanceReadinessPanel(props: {
  model: MaintenanceReadinessPanelModel;
}) {
  const { model } = props;
  return (
    <section class="maintenance-readiness">
      <div class="maintenance-readiness__header">
        <div class="maintenance-readiness__heading">
          <div class="maintenance-readiness__title">{model.title}</div>
          <div class="maintenance-readiness__summary">{model.summary}</div>
        </div>
        {model.stateLabel ? (
          <span class="pill" data-variant={model.stateVariant}>
            {model.stateLabel}
          </span>
        ) : null}
      </div>
      <ul class="maintenance-readiness__list">
        {model.items.map((item, index) => (
          <MaintenanceReadinessItemRow
            key={`${item.label}:${index}`}
            item={item}
          />
        ))}
      </ul>
    </section>
  );
}

function InternetStatusCard(props: {
  model: InternetStatusPanelModel;
}) {
  const { model } = props;
  return (
    <MaintenanceCard
      badge={model.badge}
      subtitleText={model.summaryText}
      titleText={model.titleText}
    >
      <StatusGrid rows={model.rows} />
    </MaintenanceCard>
  );
}

function UpdateTransportChoiceCard(props: {
  captionId?: string;
  choiceId: string;
  model: UpdateTransportChoiceCardRenderModel;
  onSelect: ((transport: UpdateStartRequestPayload["transport"]) => void) | null;
  radioId: string;
  titleKey: string;
  titleText: string;
  value: UpdateStartRequestPayload["transport"];
}) {
  const { captionId, choiceId, model, onSelect, radioId, titleKey, titleText, value } = props;
  return (
    <label
      id={choiceId}
      class="speed-source-choice update-transport-choice"
      data-update-transport-choice={value}
      data-selected={model.selected ? "true" : undefined}
      data-disabled={model.disabled ? "true" : undefined}
      data-choice-state={model.state ?? undefined}
      data-choice-badge={model.badgeText ?? undefined}
    >
      <input
        class="speed-source-choice__radio"
        type="radio"
        id={radioId}
        name="updateTransport"
        value={value}
        checked={model.selected}
        disabled={model.inputDisabled}
        onChange={() => onSelect?.(value)}
      />
      <span class="speed-source-choice__title">
        {titleText}
      </span>
      <span id={captionId} class="speed-source-choice__caption">
        {model.summaryText}
      </span>
    </label>
  );
}

function InternetPanel(props: {
  focusRequest: ReadonlySignal<InternetPanelFocusRequest | null>;
  state: ReadonlySignal<InternetPanelBridgeState>;
}) {
  const state = props.state.value;
  const model = state.model?.value ?? DEFAULT_INTERNET_PANEL_MODEL;
  const ssidInputRef = useRef<HTMLInputElement | null>(null);

  useSignalEffect(() => {
    const focusRequest = props.focusRequest.value;
    if (!focusRequest) {
      return;
    }
    ssidInputRef.current?.focus();
  });

  return (
    <div class="maintenance-stack">
      <div class="panel card">
        <strong>
          {t("settings.internet.title", "Internet")}
        </strong>
        <div class="subtle">
          {t(
            "settings.internet.hint",
            "USB internet is optional. When a compatible phone or USB network device is detected, the Pi can keep its hotspot active while using USB as the upstream connection.",
          )}
        </div>
        <div
          id="internetStatusPanel"
          class="maintenance-stack internet-panel__status"
          aria-live="polite"
        >
          {model.internetStatus ? (
            <InternetStatusCard model={model.internetStatus} />
          ) : null}
        </div>
      </div>

      <section class="maintenance-card">
        <div class="maintenance-card__header">
          <div>
            <div
              class="maintenance-card__title"

            >
              {t("settings.update.controls_title", "Update connection")}
            </div>
            <div
              class="subtle"

            >
              {t(
                "settings.update.controls_intro",
                "Use Wi-Fi credentials as before, or choose the existing USB internet uplink when the Pi detects one.",
              )}
            </div>
          </div>
        </div>
        <div class="update-form">
          <div
            id="updateTransportOptions"
            class="maintenance-stack maintenance-stack--tight"
          >
            <div
              class="subtle"

            >
              {t("settings.update.transport_label", "Internet source")}
            </div>
            <div class="speed-source-choice-grid">
              <UpdateTransportChoiceCard
                choiceId="updateTransportChoiceWifi"
                model={model.transportChoices.wifi}
                onSelect={state.actions?.onTransportChange ?? null}
                radioId="updateTransportWifiRadio"
                titleKey="settings.update.transport.wifi_title"
                titleText={t("settings.update.transport.wifi_title", "Temporary Wi-Fi")}
                value="wifi"
              />
              <UpdateTransportChoiceCard
                captionId="updateUsbTransportSummary"
                choiceId="updateTransportChoiceUsb"
                model={model.transportChoices.usb_internet}
                onSelect={state.actions?.onTransportChange ?? null}
                radioId="updateTransportUsbRadio"
                titleKey="settings.update.transport.usb_title"
                titleText={t(
                  "settings.update.transport.usb_title",
                  "Existing USB internet",
                )}
                value="usb_internet"
              />
            </div>
          </div>
          <div id="updateWifiFields" hidden={model.wifiFieldsHidden}>
            <div class="form-group">
              <label htmlFor="updateSsidInput">
                {t("settings.update.ssid", "Wi-Fi SSID")}
              </label>
              <input
                type="text"
                id="updateSsidInput"
                ref={ssidInputRef}
                autoComplete="off"
                maxLength={64}
                class="internet-panel__input"
                value={model.ssidInputValue}
                disabled={model.controlsLocked}
                onInput={(event) =>
                  state.actions?.onSsidInput(event.currentTarget.value)}
              />
            </div>
            <div class="form-group">
              <label
                htmlFor="updatePasswordInput"

              >
                {t("settings.update.password", "Wi-Fi Password")}
              </label>
              <div class="internet-panel__input-row">
                <input
                  type={model.passwordInputType}
                  id="updatePasswordInput"
                  autoComplete="off"
                  maxLength={128}
                  class="internet-panel__input"
                  value={model.passwordInputValue}
                  disabled={model.controlsLocked}
                  onInput={(event) =>
                    state.actions?.onPasswordInput(event.currentTarget.value)}
                />
                <button
                  type="button"
                  id="updateTogglePasswordBtn"
                  class="btn btn--small"
                  disabled={model.togglePasswordDisabled}
                  onClick={() => state.actions?.onTogglePassword()}
                >
                  <span>{model.togglePasswordLabelText}</span>
                </button>
              </div>
            </div>
          </div>
          <div
            id="updateReadinessSummary"
            class="maintenance-stack maintenance-stack--tight"
            aria-live="polite"
          >
            <MaintenanceReadinessPanel model={model.readiness} />
          </div>
          <details class="settings-help-disclosure settings-help-disclosure--inline">
            <summary class="settings-help-disclosure__summary">
              <span class="settings-help-disclosure__heading">
                <span
                  class="settings-help-disclosure__title"

                >
                  {t("settings.update.details_title", "What happens next")}
                </span>
                <span
                  id="updateDetailsCaption"
                  class="settings-help-disclosure__caption"
                >
                  {model.detailsCaptionText}
                </span>
              </span>
            </summary>
            <div class="settings-help-disclosure__body">
              <div id="updateTransportNote" class="maintenance-note">
                {model.transportNoteText}
              </div>
            </div>
          </details>
        </div>
      </section>
    </div>
  );
}

export function mountInternetPanel(host: HTMLElement): InternetPanelView {
  const focusRequest = signal<InternetPanelFocusRequest | null>(null);
  let focusRequestToken = 0;
  const state = signal<InternetPanelBridgeState>({
    actions: null,
    model: null,
  });
  render(<InternetPanel focusRequest={focusRequest} state={state} />, host);

  return {
    bindActions(handlers) {
      state.value = { ...state.value, actions: handlers };
    },
    bindModel(model) {
      state.value = { ...state.value, model };
    },
    focusSsidInput() {
      focusRequestToken += 1;
      focusRequest.value = { field: "ssid", token: focusRequestToken };
    },
  };
}
