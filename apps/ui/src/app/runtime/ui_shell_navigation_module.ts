import type { ShellState } from "../ui_app_state";

export const DEFAULT_SHELL_VIEW_ID = "dashboardView";

type UiShellNavigationDom = {
  appShellWrap: HTMLElement | null;
  views: HTMLElement[];
};

type UiShellNavigationDeps = {
  dom: UiShellNavigationDom;
  onDashboardViewActivated?: () => void;
  shell: ShellState;
};

export interface UiShellNavigationModule {
  setActiveView(viewId: string): void;
}

export function createUiShellNavigationModule(
  deps: UiShellNavigationDeps,
): UiShellNavigationModule {
  return {
    setActiveView(viewId) {
      const valid = deps.dom.views.some((view) => view.id === viewId);
      deps.shell.activeViewId = valid ? viewId : DEFAULT_SHELL_VIEW_ID;
      for (const view of deps.dom.views) {
        view.hidden = view.id !== deps.shell.activeViewId;
      }
      if (deps.dom.appShellWrap) {
        deps.dom.appShellWrap.dataset.activeView = deps.shell.activeViewId;
      }
      if (deps.shell.activeViewId === DEFAULT_SHELL_VIEW_ID) {
        deps.onDashboardViewActivated?.();
      }
    },
  };
}
