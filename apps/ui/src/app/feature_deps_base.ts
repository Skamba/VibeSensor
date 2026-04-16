/**
 * Minimal shared utilities that feature factories still consume after the
 * signal-backed state migration removed most of the older constructor plumbing.
 */
export interface FeatureServices {
  t: (key: string, vars?: Record<string, unknown>) => string;
  showError: (message: string) => void;
  requestConfirmation: (message: string) => Promise<boolean>;
}

export interface FeatureFormatting {
  fmt: (n: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
}
