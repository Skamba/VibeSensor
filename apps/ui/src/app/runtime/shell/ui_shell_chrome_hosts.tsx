import type { ComponentChildren } from "preact";

import {
  useComputed,
  useSignalProperties,
  type ReadonlySignal,
} from "../../ui_signals";
import {
  SHELL_ACTIVE_VIEW_KEY,
  type UiShellChromeNavigationModel,
  type UiShellChromePendingPanelHosts,
} from "./ui_shell_chrome_shared";

type ShellViewSectionProps = {
  activeViewId: ReadonlySignal<string>;
  ariaLabelledBy: string;
  children: ComponentChildren;
  viewId: string;
};

export function ShellViewHostsContainer(props: {
  navigationModel: ReadonlySignal<UiShellChromeNavigationModel>;
  panelHosts: UiShellChromePendingPanelHosts;
}) {
  const { navigationModel, panelHosts } = props;
  const { activeViewId } = useSignalProperties(navigationModel, SHELL_ACTIVE_VIEW_KEY);

  return (
    <>
      <ShellViewSection
        activeViewId={activeViewId}
        ariaLabelledBy="tab-dashboard"
        viewId="dashboardView"
      >
        <DashboardViewHosts panelHosts={panelHosts.dashboard} />
      </ShellViewSection>

      <ShellViewSection
        activeViewId={activeViewId}
        ariaLabelledBy="tab-history"
        viewId="historyView"
      >
        <HistoryViewHosts panelHosts={panelHosts} />
      </ShellViewSection>

      <ShellViewSection
        activeViewId={activeViewId}
        ariaLabelledBy="tab-settings"
        viewId="settingsView"
      >
        <SettingsViewHosts panelHosts={panelHosts} />
      </ShellViewSection>
    </>
  );
}

function DashboardViewHosts(props: {
  panelHosts: UiShellChromePendingPanelHosts["dashboard"];
}) {
  const { panelHosts } = props;

  return (
    <div class="dashboard-grid">
      <div
        id="liveOverviewRoot"
        ref={(element) => {
          panelHosts.liveOverview = element;
        }}
        class="panel card dashboard-grid__overview"
      ></div>
      <div
        id="spectrumPanelRoot"
        ref={(element) => {
          panelHosts.spectrum = element;
        }}
        class="panel card dashboard-grid__main"
      ></div>
      <div
        id="loggingPanelRoot"
        ref={(element) => {
          panelHosts.logging = element;
        }}
        class="panel card dashboard-grid__controls"
      ></div>
    </div>
  );
}

function HistoryViewHosts(props: {
  panelHosts: UiShellChromePendingPanelHosts;
}) {
  return (
    <div
      id="historyPanelRoot"
      ref={(element) => {
        props.panelHosts.history = element;
      }}
      class="panel card"
    ></div>
  );
}

function SettingsViewHosts(props: {
  panelHosts: UiShellChromePendingPanelHosts;
}) {
  return (
    <div
      id="settingsShellRoot"
      ref={(element) => {
        props.panelHosts.settingsShell = element;
      }}
    ></div>
  );
}

function ShellViewSection(props: ShellViewSectionProps) {
  const { activeViewId, ariaLabelledBy, children, viewId } = props;
  const hidden = useComputed(() => activeViewId.value !== viewId);

  return (
    <section
      id={viewId}
      class="view"
      role="tabpanel"
      aria-labelledby={ariaLabelledBy}
      hidden={hidden}
    >
      {children}
    </section>
  );
}
