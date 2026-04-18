import type { ComponentChildren } from "preact";

import { UiShellChrome, type UiShellChromeBindings } from "./runtime/ui_shell_chrome";
import { DEFAULT_NAVIGATION_MODEL } from "./runtime/shell/ui_shell_chrome_shared";
import { useComputed } from "./ui_signals";
import type { UiMountedLazyPanelHandles, UiMountedPanels } from "./ui_lazy_panels";
import HistoryLazyView from "./views/history_lazy_view";
import { RealtimeLiveOverviewPanel } from "./views/realtime_live_overview";
import { RealtimeLoggingPanelView } from "./views/realtime_logging_panel";
import SettingsLazyView from "./views/settings_lazy_view";
import { SpectrumPanelHost, type CreatedSpectrumPanel } from "./views/spectrum_panel";
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
  const activeViewId = useComputed(() => navigationModel.value.activeViewId);

  return (
    <UiShellChrome {...props.shellChrome.props}>
      <ShellViewSection
        activeViewId={activeViewId.value}
        ariaLabelledBy="tab-dashboard"
        viewId="dashboardView"
      >
        <div class="dashboard-grid">
          <div class="panel card dashboard-grid__overview">
            <RealtimeLiveOverviewPanel view={props.panels.dashboard.liveOverview} />
          </div>
          <div class="panel card dashboard-grid__main">
            <SpectrumPanelHost panel={props.spectrumPanel} />
          </div>
          <div class="panel card dashboard-grid__controls">
            <RealtimeLoggingPanelView view={props.panels.dashboard.logging} />
          </div>
        </div>
      </ShellViewSection>

      <ShellViewSection
        activeViewId={activeViewId.value}
        ariaLabelledBy="tab-history"
        viewId="historyView"
      >
        <div class="panel card">
          <HistoryLazyView view={props.panels.history} />
        </div>
      </ShellViewSection>

      <ShellViewSection
        activeViewId={activeViewId.value}
        ariaLabelledBy="tab-settings"
        viewId="settingsView"
      >
        <SettingsLazyView
          onReady={props.attachSettingsPanels}
          settings={props.panels.settings}
        />
      </ShellViewSection>
    </UiShellChrome>
  );
}
