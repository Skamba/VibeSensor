import type { ComponentChildren, TargetedKeyboardEvent } from "preact";
import { useEffect, useRef } from "preact/hooks";

import {
  ADVANCED_SETTINGS_TAB_IDS,
  activeView,
  confirmation,
  DAILY_SETTINGS_TAB_IDS,
  dismissHotspotHint,
  errorBanner,
  hotspotHintVisible,
  errorMessage,
  isAdvancedSettingsTab,
  isDemoMode,
  loadPreferences,
  navigate,
  settleConfirmation,
  settingsTab,
  showError,
  VIEW_IDS,
  type AdvancedSettingsTabId,
  type SettingsTabId,
  type ViewId,
} from "./app_store";
import { t } from "./i18n";
import { loadLocationCodes, payloadError, wsState } from "./live_store";
import { startLive } from "./live_transport";
import { Analysis } from "./pages/analysis/Analysis";
import { Cars } from "./pages/cars/Cars";
import { openWizard } from "./pages/cars/wizard_store";
import { Dashboard, DriveAlerts } from "./pages/dashboard/Dashboard";
import { actionBar, health } from "./pages/dashboard/dashboard_store";
import { EspFlash } from "./pages/esp_flash/EspFlash";
import { History } from "./pages/history/History";
import { Sensors } from "./pages/sensors/Sensors";
import { Spectrum } from "./pages/spectrum/Spectrum";
import { SpeedSource } from "./pages/speed_source/SpeedSource";
import { Preferences } from "./pages/preferences/Preferences";
import { SystemUpdate } from "./pages/update/Update";
import { loadCars, loadSpeedSource } from "./settings_store";
import { uiLogger } from "./ui_logger";

const NAV: Record<ViewId, { tabId: string; labelKey: string }> = {
  dashboardView: { tabId: "tab-dashboard", labelKey: "nav.live" },
  historyView: { tabId: "tab-history", labelKey: "nav.history" },
  settingsView: { tabId: "tab-settings", labelKey: "nav.settings" },
};

/** The top strip: the daily tabs, then one tab holding the advanced ones. */
const ADVANCED_TAB = "advancedTab";
type SettingsStripId =
  | (typeof DAILY_SETTINGS_TAB_IDS)[number]
  | typeof ADVANCED_TAB;
const SETTINGS_STRIP_IDS: readonly SettingsStripId[] = [
  ...DAILY_SETTINGS_TAB_IDS,
  ADVANCED_TAB,
];

const SETTINGS_TAB_LABEL_KEYS: Record<SettingsTabId | SettingsStripId, string> =
  {
    carTab: "settings.tab.car",
    speedSourceTab: "settings.tab.speed_source",
    sensorsTab: "settings.tab.sensors",
    generalTab: "settings.tab.general",
    advancedTab: "settings.tab.advanced",
    updateTab: "settings.tab.update",
    analysisTab: "settings.tab.analysis",
    espFlashTab: "settings.tab.esp_flash",
  };

/** The Advanced tab reopens on the advanced page that was open last. */
let lastAdvancedTab: AdvancedSettingsTabId = ADVANCED_SETTINGS_TAB_IDS[0];

const WS_STATUS: Record<string, { key: string; variant: string }> = {
  connecting: { key: "ws.connecting", variant: "muted" },
  connected: { key: "ws.connected", variant: "ok" },
  no_data: { key: "ws.connected", variant: "ok" },
  reconnecting: { key: "ws.reconnecting", variant: "warn" },
  stale: { key: "ws.stale", variant: "bad" },
};

/** Arrow/Home/End move between tabs; Enter/Space activate (WAI-ARIA tabs). */
function onTabKeyDown<T extends string>(
  event: TargetedKeyboardEvent<HTMLButtonElement>,
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
      <div class="menu" aria-label="Primary" role="tablist">
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
            onKeyDown={(event) =>
              onTabKeyDown(event, VIEW_IDS, index, navigate)
            }
          >
            <span>{t(NAV[id].labelKey)}</span>
          </button>
        ))}
      </div>
      <StatusPills />
    </div>
  );
}

/**
 * Connection and run health on every view; while a run records, a red pill
 * with its elapsed time, so the recording shows wherever the page is.
 */
function StatusPills() {
  const link = payloadError.value
    ? { text: t("ws.payload_error_pill"), variant: "bad" }
    : {
        text: t(WS_STATUS[wsState.value]?.key ?? "ws.connecting"),
        variant: WS_STATUS[wsState.value]?.variant ?? "muted",
      };
  const live = health.value;
  const bar = actionBar.value;
  const recordingNow = bar.state === "recording" || bar.state === "stopping";
  return (
    <div class="site-header__status">
      <div
        id="linkState"
        class="pill"
        data-variant={link.variant}
        aria-live="polite"
      >
        {link.text}
      </div>
      {recordingNow ? (
        <div id="shellRecordingPill" class="pill pill--recording">
          <span class="pill__dot" aria-hidden="true" />
          {t("dashboard.bar.recording")} {bar.elapsed}
        </div>
      ) : (
        <div
          id="shellLiveStatus"
          class="pill"
          data-variant={live.variant}
          aria-live="polite"
        >
          {live.text}
        </div>
      )}
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

function HotspotHint() {
  if (!hotspotHintVisible.value) {
    return null;
  }
  return (
    <div
      id="hotspotHint"
      class="connection-banner hotspot-hint"
      data-variant="muted"
    >
      <span>{t("shell.hotspot_hint")}</span>
      <button type="button" class="btn btn--muted" onClick={dismissHotspotHint}>
        {t("shell.hotspot_hint_dismiss")}
      </button>
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
          <strong
            id="confirmationDialogTitle"
            class="confirmation-dialog__title"
          >
            {t("actions.confirm_title")}
          </strong>
          <p
            id="confirmationDialogMessage"
            class="confirmation-dialog__message"
          >
            {pending.message}
          </p>
        </div>
        <div class="confirmation-dialog__actions">
          <button
            type="button"
            class="btn"
            onClick={() => settleConfirmation(false)}
          >
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
  if (isAdvancedSettingsTab(current)) {
    lastAdvancedTab = current;
  }
  const selected: SettingsStripId = isAdvancedSettingsTab(current)
    ? ADVANCED_TAB
    : current;
  const activate = (id: SettingsStripId) => {
    settingsTab.value = id === ADVANCED_TAB ? lastAdvancedTab : id;
  };
  return (
    <div class="settings-tabs" role="tablist">
      {SETTINGS_STRIP_IDS.map((id, index) => (
        <button
          key={id}
          type="button"
          class="settings-tab"
          data-settings-tab={id}
          role="tab"
          aria-controls={id}
          aria-selected={selected === id ? "true" : "false"}
          tabIndex={selected === id ? 0 : -1}
          onClick={() => activate(id)}
          onKeyDown={(event) =>
            onTabKeyDown(event, SETTINGS_STRIP_IDS, index, activate)
          }
        >
          <span>{t(SETTINGS_TAB_LABEL_KEYS[id])}</span>
        </button>
      ))}
    </div>
  );
}

/** Maintenance and tuning pages, one at a time under a second tab row. */
function AdvancedSettings() {
  const current = settingsTab.value;
  const activate = (id: AdvancedSettingsTabId) => {
    settingsTab.value = id;
  };
  return (
    <div
      id={ADVANCED_TAB}
      class="settings-tab-panel settings-advanced"
      role="tabpanel"
      hidden={!isAdvancedSettingsTab(current)}
    >
      <p class="subtle settings-advanced__intro">
        {t("settings.advanced.intro")}
      </p>
      <div
        class="settings-subtabs"
        role="tablist"
        aria-label={t("settings.tab.advanced")}
      >
        {ADVANCED_SETTINGS_TAB_IDS.map((id, index) => (
          <button
            key={id}
            type="button"
            class="settings-subtab"
            data-settings-subtab={id}
            role="tab"
            aria-controls={id}
            aria-selected={current === id ? "true" : "false"}
            tabIndex={current === id ? 0 : -1}
            onClick={() => activate(id)}
            onKeyDown={(event) =>
              onTabKeyDown(event, ADVANCED_SETTINGS_TAB_IDS, index, activate)
            }
          >
            {t(SETTINGS_TAB_LABEL_KEYS[id])}
          </button>
        ))}
      </div>
      <SettingsTab id="updateTab">
        <SystemUpdate />
      </SettingsTab>
      <SettingsTab id="analysisTab">
        <Analysis />
      </SettingsTab>
      <SettingsTab id="espFlashTab">
        <EspFlash />
      </SettingsTab>
    </div>
  );
}

function SettingsTab(props: {
  id: SettingsTabId;
  children: ComponentChildren;
}) {
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

function openAddCar(): void {
  navigate("settingsView", "carTab");
  void openWizard();
}

export function App() {
  const degraded =
    payloadError.value !== null ||
    wsState.value === "reconnecting" ||
    wsState.value === "stale";
  return (
    <div class="wrap" data-connection-state={degraded ? "degraded" : "live"}>
      <header class="site-header">
        <Header />
        <DriveAlerts onLive={activeView.value === "dashboardView"} />
      </header>
      <HotspotHint />
      <ErrorBanner />
      <View id="dashboardView">
        <Dashboard spectrum={<Spectrum />} onAddCar={openAddCar} />
      </View>
      <View id="historyView">
        <div class="panel card">
          <History />
        </div>
      </View>
      <View id="settingsView">
        <SettingsTabs />
        <SettingsTab id="carTab">
          <Cars />
        </SettingsTab>
        <SettingsTab id="speedSourceTab">
          <SpeedSource />
        </SettingsTab>
        <SettingsTab id="sensorsTab">
          <Sensors />
        </SettingsTab>
        <SettingsTab id="generalTab">
          <Preferences />
        </SettingsTab>
        <AdvancedSettings />
      </View>
      <ConfirmationDialog />
    </div>
  );
}

function runStartupTask(name: string, task: () => Promise<unknown>): void {
  void task().catch((error: unknown) => {
    uiLogger.warn(`UI startup task failed: ${name}`, error);
  });
}

/** Loads shared settings and connects the live feed (demo mode skips the server). */
export function startApp(): void {
  if (!isDemoMode()) {
    runStartupTask("load preferences", loadPreferences);
    runStartupTask("load location codes", loadLocationCodes);
    runStartupTask("hydrate dashboard state", () =>
      Promise.all([loadCars(), loadSpeedSource()]).catch((error: unknown) => {
        showError(errorMessage(error, t("status.view_load_failed")));
        throw error;
      }),
    );
  }
  startLive();
}
