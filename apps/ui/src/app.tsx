import type { ComponentChildren, JSX } from "preact";
import { useEffect, useRef } from "preact/hooks";

import {
  activeView,
  confirmation,
  errorBanner,
  languageFeedback,
  navigate,
  saveLanguage,
  saveSpeedUnit,
  selectedLanguage,
  selectedSpeedUnit,
  SETTINGS_TAB_IDS,
  settleConfirmation,
  settingsTab,
  speedUnitFeedback,
  VIEW_IDS,
  type SettingsTabId,
  type ViewId,
} from "./app_store";
import { appState, liveStatusBadge, panels } from "./app/feature_wiring";
import { HistoryPanel } from "./app/views/history_panel";
import { RealtimeLiveOverviewPanel } from "./app/views/realtime_live_overview";
import { RealtimeLoggingPanelView } from "./app/views/realtime_logging_panel";
import { SensorsPanel } from "./app/views/sensors_panel";
import { SpectrumPanelHost } from "./app/views/spectrum_panel_host";
import { FeedbackSlot } from "./components/feedback";
import { t } from "./i18n";
import { EspFlash } from "./pages/esp_flash/EspFlash";
import { SpeedSource } from "./pages/speed_source/SpeedSource";
import { Internet, Update } from "./pages/update/Update";

const NAV: Record<ViewId, { tabId: string; labelKey: string }> = {
  dashboardView: { tabId: "tab-dashboard", labelKey: "nav.live" },
  historyView: { tabId: "tab-history", labelKey: "nav.history" },
  settingsView: { tabId: "tab-settings", labelKey: "nav.settings" },
};

const SETTINGS_TAB_LABEL_KEYS: Record<SettingsTabId, string> = {
  carTab: "settings.tab.car",
  analysisTab: "settings.tab.analysis",
  speedSourceTab: "settings.tab.speed_source",
  sensorsTab: "settings.tab.sensors",
  internetTab: "settings.tab.internet",
  updateTab: "settings.tab.update",
  espFlashTab: "settings.tab.esp_flash",
};

const WS_STATUS: Record<string, { key: string; variant: string }> = {
  connecting: { key: "ws.connecting", variant: "muted" },
  connected: { key: "ws.connected", variant: "ok" },
  no_data: { key: "ws.connected", variant: "ok" },
  reconnecting: { key: "ws.reconnecting", variant: "warn" },
  stale: { key: "ws.stale", variant: "bad" },
};

/** Arrow/Home/End move between tabs; Enter/Space activate (WAI-ARIA tabs). */
function onTabKeyDown<T extends string>(
  event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  ids: readonly T[],
  index: number,
  activate: (id: T) => void,
): void {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    activate(ids[index]);
    return;
  }
  const targets: Record<string, number> = {
    ArrowRight: index + 1,
    ArrowLeft: index - 1,
    Home: 0,
    End: ids.length - 1,
  };
  const target = targets[event.key];
  if (target === undefined) {
    return;
  }
  event.preventDefault();
  const next = (target + ids.length) % ids.length;
  activate(ids[next]);
  const sibling = event.currentTarget.parentElement?.children[next];
  if (sibling instanceof HTMLElement) {
    sibling.focus();
  }
}

function Header() {
  const view = activeView.value;
  return (
    <div class="site-header__main">
      <div class="site-header__nav">
        <h1 class="title" aria-label="VibeSensor">
          <picture class="brandmark">
            <source
              srcSet="/branding/vibesensor-logo-header-dark.svg"
              media="(prefers-color-scheme: dark)"
            />
            <img
              src="/branding/vibesensor-logo-header-light.svg"
              alt="VibeSensor"
              width="222"
              height="46"
            />
          </picture>
        </h1>
        <nav class="menu" aria-label="Primary" role="tablist">
          {VIEW_IDS.map((id, index) => (
            <button
              key={id}
              type="button"
              class="menu-btn"
              data-view={id}
              id={NAV[id].tabId}
              role="tab"
              aria-controls={id}
              aria-selected={view === id ? "true" : "false"}
              tabIndex={view === id ? 0 : -1}
              onClick={() => navigate(id)}
              onKeyDown={(event) => onTabKeyDown(event, VIEW_IDS, index, navigate)}
            >
              <span>{t(NAV[id].labelKey)}</span>
            </button>
          ))}
        </nav>
      </div>
      <Preferences />
    </div>
  );
}

function Preferences() {
  const unitLabel = t("speed.unit");
  const languageLabel = t("settings.language");
  return (
    <div class="site-header__preferences">
      <label class="header-select" htmlFor="speedUnitSelect">
        <span class="mini-label">{unitLabel}</span>
        <select
          id="speedUnitSelect"
          class="unit-picker"
          aria-label={unitLabel}
          aria-describedby={speedUnitFeedback.value ? "speedUnitFeedback" : undefined}
          aria-invalid={speedUnitFeedback.value?.tone === "error" ? "true" : undefined}
          value={selectedSpeedUnit.value}
          onChange={(event) => void saveSpeedUnit(event.currentTarget.value)}
        >
          <option value="kmh">{t("speed.unit.kmh")}</option>
          <option value="mps">{t("speed.unit.mps")}</option>
        </select>
        <FeedbackSlot id="speedUnitFeedback" message={speedUnitFeedback.value} compact />
      </label>
      <label class="header-select" htmlFor="languageSelect">
        <span class="mini-label">{languageLabel}</span>
        <select
          id="languageSelect"
          class="lang-picker"
          aria-label={languageLabel}
          aria-describedby={languageFeedback.value ? "languageFeedback" : undefined}
          aria-invalid={languageFeedback.value?.tone === "error" ? "true" : undefined}
          value={selectedLanguage.value}
          onChange={(event) => void saveLanguage(event.currentTarget.value)}
        >
          <option value="en">🇺🇸 English</option>
          <option value="nl">🇳🇱 Nederlands</option>
        </select>
        <FeedbackSlot id="languageFeedback" message={languageFeedback.value} compact />
      </label>
    </div>
  );
}

function StatusPills() {
  const { payloadError, wsState } = appState.transport;
  const link = payloadError.value
    ? { text: t("ws.payload_error_pill"), variant: "bad" }
    : {
        text: t(WS_STATUS[wsState.value]?.key ?? "ws.connecting"),
        variant: WS_STATUS[wsState.value]?.variant ?? "muted",
      };
  const live = liveStatusBadge.value;
  return (
    <div class="site-header__status" hidden={activeView.value === "dashboardView"}>
      <div class="site-header__status-pills">
        <div id="linkState" class="pill" data-variant={link.variant} aria-live="polite">
          {link.text}
        </div>
        <div id="shellLiveStatus" class="pill" data-variant={live.variant} aria-live="polite">
          {live.text}
        </div>
      </div>
    </div>
  );
}

function ErrorBanner() {
  const message = errorBanner.value;
  return (
    <div
      id="appErrorBanner"
      class="connection-banner app-error-banner"
      hidden={message === null}
      data-variant={message === null ? undefined : "bad"}
      aria-live="assertive"
      role="alert"
    >
      {message ?? ""}
    </div>
  );
}

function ConfirmationDialog() {
  const pending = confirmation.value;
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    confirmRef.current?.focus();
  }, [pending]);
  if (pending === null) {
    return null;
  }
  return (
    <div class="app-modal-layer">
      <div
        class="app-modal-backdrop"
        aria-hidden="true"
        onClick={() => settleConfirmation(false)}
      />
      <div
        class="panel card confirmation-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirmationDialogTitle"
        aria-describedby="confirmationDialogMessage"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            settleConfirmation(false);
          }
        }}
      >
        <div class="confirmation-dialog__body">
          <strong id="confirmationDialogTitle" class="confirmation-dialog__title">
            {t("actions.confirm_title")}
          </strong>
          <p id="confirmationDialogMessage" class="confirmation-dialog__message">
            {pending.message}
          </p>
        </div>
        <div class="confirmation-dialog__actions">
          <button type="button" class="btn" onClick={() => settleConfirmation(false)}>
            {t("actions.cancel")}
          </button>
          <button
            type="button"
            class="btn btn--danger"
            onClick={() => settleConfirmation(true)}
            ref={confirmRef}
          >
            {t("actions.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}

function View(props: { id: ViewId; children: ComponentChildren }) {
  return (
    <section
      id={props.id}
      class="view"
      role="tabpanel"
      aria-labelledby={NAV[props.id].tabId}
      hidden={activeView.value !== props.id}
    >
      {props.children}
    </section>
  );
}

function SettingsTabs() {
  const current = settingsTab.value;
  const activate = (id: SettingsTabId) => {
    settingsTab.value = id;
  };
  return (
    <nav class="settings-tabs" role="tablist">
      {SETTINGS_TAB_IDS.map((id, index) => (
        <button
          key={id}
          type="button"
          class="settings-tab"
          data-settings-tab={id}
          role="tab"
          aria-controls={id}
          aria-selected={current === id ? "true" : "false"}
          tabIndex={current === id ? 0 : -1}
          onClick={() => activate(id)}
          onKeyDown={(event) => onTabKeyDown(event, SETTINGS_TAB_IDS, index, activate)}
        >
          <span>{t(SETTINGS_TAB_LABEL_KEYS[id])}</span>
        </button>
      ))}
    </nav>
  );
}

function SettingsTab(props: { id: SettingsTabId; children: ComponentChildren }) {
  return (
    <div
      id={props.id}
      class="settings-tab-panel"
      role="tabpanel"
      hidden={settingsTab.value !== props.id}
    >
      {props.children}
    </div>
  );
}

export function App() {
  const degraded =
    appState.transport.payloadError.value !== null ||
    appState.transport.wsState.value === "reconnecting" ||
    appState.transport.wsState.value === "stale";
  return (
    <div class="wrap" data-connection-state={degraded ? "degraded" : "live"}>
      <header class="site-header">
        <Header />
        <StatusPills />
      </header>
      <ErrorBanner />
      <View id="dashboardView">
        <div class="dashboard-grid">
          <div class="panel card dashboard-grid__overview">
            <RealtimeLiveOverviewPanel view={panels.liveOverview} />
          </div>
          <div class="panel card dashboard-grid__main">
            <SpectrumPanelHost panel={panels.spectrum} />
          </div>
          <div class="panel card dashboard-grid__controls">
            <RealtimeLoggingPanelView view={panels.logging} />
          </div>
        </div>
      </View>
      <View id="historyView">
        <div class="panel card">
          <HistoryPanel actions={panels.history.actions} model={panels.history.model} />
        </div>
      </View>
      <View id="settingsView">
        <SettingsTabs />
        <SettingsTab id="carTab">
          <panels.cars.Panel />
        </SettingsTab>
        <SettingsTab id="analysisTab">
          <panels.analysis.Panel />
        </SettingsTab>
        <SettingsTab id="speedSourceTab">
          <SpeedSource />
        </SettingsTab>
        <SettingsTab id="sensorsTab">
          <SensorsPanel actions={panels.sensors.actions} model={panels.sensors.model} />
        </SettingsTab>
        <SettingsTab id="internetTab">
          <Internet />
        </SettingsTab>
        <SettingsTab id="updateTab">
          <Update />
        </SettingsTab>
        <SettingsTab id="espFlashTab">
          <EspFlash />
        </SettingsTab>
      </View>
      <ConfirmationDialog />
    </div>
  );
}
