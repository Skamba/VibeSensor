import type { ComponentChildren } from "preact";

import { UiShellChrome, type UiShellChromeBindings } from "./runtime/ui_shell_chrome";
import { DEFAULT_NAVIGATION_MODEL } from "./runtime/shell/ui_shell_chrome_shared";
import type { UiMountedLazyPanelHandles, UiMountedPanels } from "./ui_lazy_panels";
import HistoryLazyView from "./views/history_lazy_view";
import RealtimeLiveOverviewLazy from "./views/realtime_live_overview_lazy";
import RealtimeLoggingPanelLazy from "./views/realtime_logging_panel_lazy";
import SettingsLazyView from "./views/settings_lazy_view";
import type { CreatedSpectrumPanel } from "./views/spectrum_panel";
import SpectrumPanelHostLazy from "./views/spectrum_panel_host_lazy";
import { useDeferredModel } from "./views/view_model_binding";

function ShellViewSection(props: {
  activeViewId: string;
  ariaLabelledBy: string;
  children: ComponentChildren;
  viewId: string;
}) {
  const hidden = props.activeViewId !== props.viewId;

  return (
    <section
      id={props.viewId}
      class="view"
      role="tabpanel"
      aria-labelledby={props.ariaLabelledBy}
      hidden={hidden}
    >
      {props.children}
    </section>
  );
}

export function UiAppRoot(props: {
  attachSettingsPanels(handles: UiMountedLazyPanelHandles): void;
  panels: UiMountedPanels;
  shellChrome: UiShellChromeBindings;
  spectrumPanel: CreatedSpectrumPanel;
}) {
  const navigationModel = useDeferredModel(
    props.shellChrome.props.navigationModel,
    DEFAULT_NAVIGATION_MODEL,
  );
  const activeViewId = navigationModel.value.activeViewId;

  return (
    <UiShellChrome {...props.shellChrome.props}>
      <ShellViewSection
        activeViewId={activeViewId}
        ariaLabelledBy="tab-dashboard"
        viewId="dashboardView"
      >
        <div class="dashboard-grid">
          <div class="panel card dashboard-grid__overview">
            <RealtimeLiveOverviewLazy
              active={activeViewId === "dashboardView"}
              view={props.panels.dashboard.liveOverview}
            />
          </div>
          <div class="panel card dashboard-grid__main">
            <SpectrumPanelHostLazy
              active={activeViewId === "dashboardView"}
              panel={props.spectrumPanel}
            />
          </div>
          <div class="panel card dashboard-grid__controls">
            <RealtimeLoggingPanelLazy
              active={activeViewId === "dashboardView"}
              view={props.panels.dashboard.logging}
            />
          </div>
        </div>
      </ShellViewSection>

      <ShellViewSection
        activeViewId={activeViewId}
        ariaLabelledBy="tab-history"
        viewId="historyView"
      >
        <div class="panel card">
          <HistoryLazyView
            active={activeViewId === "historyView"}
            view={props.panels.history}
          />
        </div>
      </ShellViewSection>

      <ShellViewSection
        activeViewId={activeViewId}
        ariaLabelledBy="tab-settings"
        viewId="settingsView"
      >
        <SettingsLazyView
          active={activeViewId === "settingsView"}
          onReady={props.attachSettingsPanels}
          settings={props.panels.settings}
        />
      </ShellViewSection>
    </UiShellChrome>
  );
}
