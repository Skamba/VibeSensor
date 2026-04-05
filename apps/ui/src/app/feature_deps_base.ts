/**
 * Shared base interface for UI feature dependency injection.
 *
 * All feature Deps interfaces extend this base to avoid duplicating
 * the common non-DOM fields (i18n translation, HTML escaping)
 * across every feature module.
 */
export interface FeatureDepsBase {
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  showError: (message: string) => void;
}
