import type { UiDomElements } from "../ui_dom_registry";

const ERROR_BANNER_VISIBLE_MS = 8_000;

export interface UiShellNotificationModuleDeps {
  els: UiDomElements;
}

export interface UiShellNotificationModule {
  showError(message: string): void;
  clearError(): void;
}

export function createUiShellNotificationModule(
  ctx: UiShellNotificationModuleDeps,
): UiShellNotificationModule {
  let clearTimer: ReturnType<typeof setTimeout> | null = null;

  function clearPendingTimer(): void {
    if (clearTimer === null) return;
    clearTimeout(clearTimer);
    clearTimer = null;
  }

  function clearError(): void {
    clearPendingTimer();
    const banner = ctx.els.appErrorBanner;
    if (!banner) return;
    banner.hidden = true;
    banner.textContent = "";
    banner.className = "connection-banner app-error-banner";
  }

  function showError(message: string): void {
    clearPendingTimer();
    const banner = ctx.els.appErrorBanner;
    if (!banner) {
      console.warn("UI error banner unavailable", message);
      return;
    }
    banner.hidden = false;
    banner.textContent = message;
    banner.className = "connection-banner connection-banner--bad app-error-banner";
    clearTimer = setTimeout(() => {
      clearTimer = null;
      clearError();
    }, ERROR_BANNER_VISIBLE_MS);
  }

  return {
    showError,
    clearError,
  };
}
