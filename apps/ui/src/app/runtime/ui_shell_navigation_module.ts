import type { UiDomElements } from "../ui_dom_registry";
import type { ShellState } from "../ui_app_state";

export const DEFAULT_SHELL_VIEW_ID = "dashboardView";

export interface UiShellNavigationModuleDeps {
  shell: ShellState;
  els: UiDomElements;
  onDashboardViewActivated?: () => void;
}

export interface UiShellNavigationModule {
  setActiveView(viewId: string): void;
  bindHandlers(): void;
}

export function createUiShellNavigationModule(
  ctx: UiShellNavigationModuleDeps,
): UiShellNavigationModule {
  const { shell, els } = ctx;

  function setActiveView(viewId: string): void {
    const valid = els.views.some((view) => view.id === viewId);
    shell.activeViewId = valid ? viewId : DEFAULT_SHELL_VIEW_ID;
    for (const view of els.views) {
      const isActive = view.id === shell.activeViewId;
      view.classList.toggle("active", isActive);
      view.hidden = !isActive;
    }
    for (const button of els.menuButtons) {
      const isActive = button.dataset.view === shell.activeViewId;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-selected", isActive ? "true" : "false");
      button.tabIndex = isActive ? 0 : -1;
    }
    if (els.appShellWrap) {
      els.appShellWrap.classList.toggle("wrap--dashboard-view", shell.activeViewId === DEFAULT_SHELL_VIEW_ID);
    }
    if (shell.activeViewId === DEFAULT_SHELL_VIEW_ID) {
      ctx.onDashboardViewActivated?.();
    }
  }

  function activateMenuButton(button: HTMLElement): void {
    const viewId = button.dataset.view;
    if (!viewId) return;
    setActiveView(viewId);
  }

  function activateMenuTabByIndex(index: number): void {
    if (!els.menuButtons.length) return;
    const safeIndex = ((index % els.menuButtons.length) + els.menuButtons.length)
      % els.menuButtons.length;
    const button = els.menuButtons[safeIndex];
    activateMenuButton(button);
    button.focus();
  }

  function bindHandlers(): void {
    els.menuButtons.forEach((button, index) => {
      const activate = (): void => activateMenuButton(button);
      button.addEventListener("click", activate);
      button.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
          return;
        }
        if (event.key === "ArrowRight") {
          event.preventDefault();
          activateMenuTabByIndex(index + 1);
          return;
        }
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          activateMenuTabByIndex(index - 1);
          return;
        }
        if (event.key === "Home") {
          event.preventDefault();
          activateMenuTabByIndex(0);
          return;
        }
        if (event.key === "End") {
          event.preventDefault();
          activateMenuTabByIndex(els.menuButtons.length - 1);
        }
      });
    });
  }

  return {
    setActiveView,
    bindHandlers,
  };
}
