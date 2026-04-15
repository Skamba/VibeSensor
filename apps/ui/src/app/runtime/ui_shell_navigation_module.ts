import type { ShellState } from "../ui_app_state";
import { signal, type ReadonlySignal } from "../ui_signals";

export const DEFAULT_SHELL_VIEW_ID = "dashboardView";

type UiShellNavigationDeps = {
  onDashboardViewActivated?: () => void;
  shell: ShellState;
  viewIds: readonly string[];
};

export interface UiShellNavigationModule {
  readonly activeViewId: ReadonlySignal<string>;
  setActiveView(viewId: string): void;
}

function normalizeActiveViewId(viewId: string, viewIds: readonly string[]): string {
  return viewIds.some((candidate) => candidate === viewId) ? viewId : DEFAULT_SHELL_VIEW_ID;
}

export function createUiShellNavigationModule(
  deps: UiShellNavigationDeps,
): UiShellNavigationModule {
  const activeViewId = signal(normalizeActiveViewId(deps.shell.activeViewId, deps.viewIds));
  deps.shell.activeViewId = activeViewId.value;

  return {
    activeViewId,
    setActiveView(viewId) {
      const nextViewId = normalizeActiveViewId(viewId, deps.viewIds);
      activeViewId.value = nextViewId;
      deps.shell.activeViewId = nextViewId;
      if (nextViewId === DEFAULT_SHELL_VIEW_ID) {
        deps.onDashboardViewActivated?.();
      }
    },
  };
}
