import { t } from "../i18n";
import { useComputed, type ReadonlySignal } from "./ui_signals";

// Pre-rewrite views still pass English fallbacks; pages call i18n.t directly.

export function getUiText(
  key: string,
  fallback: string,
  vars?: Record<string, unknown>,
): string {
  return t(key, vars) || fallback;
}

export function useUiText(
  key: string,
  fallback: string,
  vars?: Record<string, unknown>,
): ReadonlySignal<string> {
  return useComputed(() => t(key, vars) || fallback);
}
