import type { UiStartupFeaturePorts } from "./ui_startup_feature_ports";
import { uiLogger } from "../../ui_logger";

type StartupShell = {
  start(defaultViewId: string): void;
  hydratePersistedPreferences(): Promise<void>;
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

type UiStartupAsyncTask = {
  name: string;
  run: () => Promise<void>;
};

type UiStartupPlan = {
  asyncTasks: readonly UiStartupAsyncTask[];
  finalSyncTasks: ReadonlyArray<() => void>;
  initialSyncTasks: ReadonlyArray<() => void>;
};

export class UiStartupCoordinator {
  private readonly shell: StartupShell;

  private readonly transport: StartupTransport;

  private readonly features: UiStartupFeaturePorts;

  private readonly defaultViewId: string;

  private readonly isDemoMode: boolean;

  private readonly warn: StartupWarn;

  constructor(deps: UiStartupCoordinatorDeps) {
    this.shell = deps.shell;
    this.transport = deps.transport;
    this.features = deps.features;
    this.defaultViewId = deps.defaultViewId;
    this.isDemoMode = new URLSearchParams(window.location.search).has("demo");
    this.warn = deps.warn ?? uiLogger.warn;
  }

  start(): void {
    const plan = this.createStartupPlan();
    for (const task of plan.initialSyncTasks) {
      task();
    }
    for (const task of plan.asyncTasks) {
      this.runAsyncTask(task.name, task.run);
    }
    for (const task of plan.finalSyncTasks) {
      task();
    }
  }

  private runAsyncTask(taskName: string, task: () => Promise<void>): void {
    void task().catch((error) => {
      this.warn(`UI startup task failed: ${taskName}`, error);
    });
  }

  private createStartupPlan(): UiStartupPlan {
    const asyncTasks = this.isDemoMode
      ? []
      : [
          {
            name: "hydrate persisted preferences",
            run: () => this.shell.hydratePersistedPreferences(),
          },
          {
            name: "refresh location options",
            run: () => this.features.realtime.refreshLocationOptions(),
          },
          {
            name: "refresh logging status",
            run: () => this.features.realtime.refreshLoggingStatus(),
          },
          {
            name: "hydrate dashboard state",
            run: () => this.features.dashboard.hydrateStartupState(),
          },
        ];

    return {
      initialSyncTasks: [
        () => this.shell.start(this.defaultViewId),
      ],
      finalSyncTasks: [
        () => this.transport.startTransportMode(),
      ],
      asyncTasks,
    };
  }
}
