import type { ComponentChildren, ComponentType } from "preact";
import { useEffect, useState } from "preact/hooks";

import { UiShellChrome, type UiShellChromeBindings } from "./runtime/ui_shell_chrome";
import { DEFAULT_NAVIGATION_MODEL } from "./runtime/shell/ui_shell_chrome_shared";
import { useComputed } from "./ui_signals";
import type { UiMountedLazyPanelHandles, UiMountedPanels } from "./ui_lazy_panels";
import { RealtimeLiveOverviewPanel } from "./views/realtime_live_overview";
import { RealtimeLoggingPanelView } from "./views/realtime_logging_panel";
import { SpectrumPanelHost, type CreatedSpectrumPanel } from "./views/spectrum_panel";
import { useDeferredModel } from "./views/view_model_binding";

type HistoryLazyViewComponent = typeof import("./views/history_lazy_view").default;
type SettingsLazyViewComponent = typeof import("./views/settings_lazy_view").default;

const loadHistoryLazyView = () => import("./views/history_lazy_view");
const loadSettingsLazyView = () => import("./views/settings_lazy_view");

function LazyPanelFallback(props: { text: string }) {
  return (
    <div class="subtle" aria-busy="true">
      {props.text}
    </div>
  );
}

function useLazyView<TProps extends object>(
  loader: () => Promise<{ default: ComponentType<TProps> }>,
): ComponentType<TProps> | null {
  const [component, setComponent] = useState<ComponentType<TProps> | null>(null);

  useEffect(() => {
    let cancelled = false;
    void loader().then((module) => {
      if (!cancelled) {
        setComponent(() => module.default);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [loader]);

  return component;
}

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
  const HistoryLazyView = useLazyView<Parameters<HistoryLazyViewComponent>[0]>(loadHistoryLazyView);
  const SettingsLazyView = useLazyView<Parameters<SettingsLazyViewComponent>[0]>(loadSettingsLazyView);
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
          {HistoryLazyView
            ? <HistoryLazyView view={props.panels.history} />
            : <LazyPanelFallback text="Loading history..." />}
        </div>
      </ShellViewSection>

      <ShellViewSection
        activeViewId={activeViewId.value}
        ariaLabelledBy="tab-settings"
        viewId="settingsView"
      >
        {SettingsLazyView
          ? (
            <SettingsLazyView
              onReady={props.attachSettingsPanels}
              settings={props.panels.settings}
            />
          )
          : <LazyPanelFallback text="Loading settings..." />}
      </ShellViewSection>
    </UiShellChrome>
  );
}
