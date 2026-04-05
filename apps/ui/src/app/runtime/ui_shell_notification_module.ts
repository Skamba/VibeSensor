import type { UiShellDom } from "../dom/shell_dom";
import { setVariantState } from "../style_state";

const ERROR_BANNER_VISIBLE_MS = 8_000;

export interface UiShellNotificationModuleDeps {
  dom: UiShellDom;
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
    const banner = ctx.dom.appErrorBanner;
    if (!banner) return;
    banner.hidden = true;
    banner.textContent = "";
    banner.className = "connection-banner app-error-banner";
    setVariantState(banner, null);
  }

  function showError(message: string): void {
    clearPendingTimer();
    const banner = ctx.dom.appErrorBanner;
    if (!banner) {
      console.warn("UI error banner unavailable", message);
      return;
    }
    banner.hidden = false;
    banner.textContent = message;
    banner.className = "connection-banner app-error-banner";
    setVariantState(banner, "bad");
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
