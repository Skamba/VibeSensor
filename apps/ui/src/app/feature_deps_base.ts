/**
 * Shared base interface for UI feature dependency injection.
 *
 * All feature Deps interfaces extend this base to avoid duplicating
 * the common fields (DOM elements, i18n translation, HTML escaping)
 * across every feature module.
 */
import type { UiDomElements } from "./dom/ui_dom_registry";

export interface FeatureDepsBase {
  els: UiDomElements;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
}
