import type { UiShellDom } from "../dom/shell_dom";
import type { ShellState } from "../ui_app_state";

export const DEFAULT_SHELL_VIEW_ID = "dashboardView";

export interface UiShellNavigationModuleDeps {
  shell: ShellState;
  dom: UiShellDom;
  onDashboardViewActivated?: () => void;
}

export interface UiShellNavigationModule {
  setActiveView(viewId: string): void;
}

export function createUiShellNavigationModule(
  ctx: UiShellNavigationModuleDeps,
): UiShellNavigationModule {
  const { shell, dom: els } = ctx;

  function setActiveView(viewId: string): void {
    const valid = els.views.some((view) => view.id === viewId);
    shell.activeViewId = valid ? viewId : DEFAULT_SHELL_VIEW_ID;
    for (const view of els.views) {
      const isActive = view.id === shell.activeViewId;
      view.hidden = !isActive;
    }
    for (const button of els.menuButtons) {
      const isActive = button.dataset.view === shell.activeViewId;
      button.setAttribute("aria-selected", isActive ? "true" : "false");
      button.tabIndex = isActive ? 0 : -1;
    }
    if (els.appShellWrap) {
      els.appShellWrap.setAttribute("data-active-view", shell.activeViewId);
    }
    if (shell.activeViewId === DEFAULT_SHELL_VIEW_ID) {
      ctx.onDashboardViewActivated?.();
    }
  }

  return {
    setActiveView,
  };
}
