import type { ShellState } from "../ui_app_state";
import { signal, type ReadonlySignal } from "../ui_signals";

export const DEFAULT_SHELL_VIEW_ID = "dashboardView";

type UiShellNavigationDeps = {
  onViewActivated?: (viewId: string) => Promise<void> | void;
  onViewActivationFailed?: (viewId: string, error: unknown) => void;
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
  let pendingActivationToken = 0;
  deps.shell.activeViewId = activeViewId.value;

  const applyActiveView = (nextViewId: string): void => {
    activeViewId.value = nextViewId;
    deps.shell.activeViewId = nextViewId;
    if (nextViewId === DEFAULT_SHELL_VIEW_ID) {
      deps.onDashboardViewActivated?.();
    }
  };

  return {
    activeViewId,
    setActiveView(viewId) {
      const nextViewId = normalizeActiveViewId(viewId, deps.viewIds);
      const activationToken = ++pendingActivationToken;
      const activationResult =
        nextViewId === DEFAULT_SHELL_VIEW_ID
          ? undefined
          : deps.onViewActivated?.(nextViewId);
      if (activationResult === undefined) {
        applyActiveView(nextViewId);
        return;
      }
      void Promise.resolve(activationResult).then(() => {
        if (activationToken !== pendingActivationToken) {
          return;
        }
        applyActiveView(nextViewId);
      }).catch((error) => {
        if (activationToken !== pendingActivationToken) {
          return;
        }
        deps.onViewActivationFailed?.(nextViewId, error);
      });
    },
  };
}
