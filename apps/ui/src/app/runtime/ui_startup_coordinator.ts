import type { UiStartupFeaturePorts } from "./ui_startup_feature_ports";

type StartupShell = {
  bindUiEvents(): void;
  hydratePersistedPreferences(): Promise<void>;
  applyLanguage(forceReloadInsights?: boolean): void;
  setActiveView(viewId: string): void;
};

type StartupTransport = {
  startTransportMode(): void;
};

type StartupWarn = (message: string, error: unknown) => void;

type UiStartupCoordinatorDeps = {
  shell: StartupShell;
  transport: StartupTransport;
  features: UiStartupFeaturePorts;
  defaultViewId: string;
  warn?: StartupWarn;
};

export class UiStartupCoordinator {
  private readonly shell: StartupShell;

  private readonly transport: StartupTransport;

  private readonly features: UiStartupFeaturePorts;

  private readonly defaultViewId: string;

  private readonly warn: StartupWarn;

  constructor(deps: UiStartupCoordinatorDeps) {
    this.shell = deps.shell;
    this.transport = deps.transport;
    this.features = deps.features;
    this.defaultViewId = deps.defaultViewId;
    this.warn = deps.warn ?? ((message, error) => console.warn(message, error));
  }

  start(): void {
    this.shell.bindUiEvents();
    this.features.settings.syncSettingsInputs();
    this.runAsyncTask("hydrate persisted preferences", () => this.shell.hydratePersistedPreferences());
    this.shell.applyLanguage(false);
    this.shell.setActiveView(this.defaultViewId);
    this.startBackgroundActivity();
    this.transport.startTransportMode();
  }

  private runAsyncTask(taskName: string, task: () => Promise<void>): void {
    void task().catch((error) => {
      this.warn(`UI startup task failed: ${taskName}`, error);
    });
  }

  private startBackgroundActivity(): void {
    this.runAsyncTask("refresh location options", () => this.features.realtime.refreshLocationOptions());
    this.runAsyncTask("load speed source", () => this.features.settings.loadSpeedSourceFromServer());
    this.runAsyncTask("load analysis settings", () =>
      this.features.settings.loadAnalysisSettingsFromServer(),
    );
    this.runAsyncTask("load cars", () => this.features.settings.loadCarsFromServer());
    this.runAsyncTask("refresh logging status", () => this.features.realtime.refreshLoggingStatus());
    this.runAsyncTask("refresh history", () => this.features.history.refreshHistory());
    this.features.update.startPolling();
    this.features.espFlash.startPolling();
    this.features.settings.startGpsStatusPolling();
  }
}
