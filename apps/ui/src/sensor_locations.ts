import type { AdaptedClient } from "./transport/live_models";

/** Pure helpers that map sensors onto install locations. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;

const SHORTHAND_LOCATIONS: Record<string, string> = {
  "front left": "front_left_wheel",
  "front right": "front_right_wheel",
  "rear left": "rear_left_wheel",
  "rear right": "rear_right_wheel",
  driver: "driver_seat",
};

export interface LocationOption {
  code: string;
  label: string;
}

export function locationOptions(
  codes: readonly string[],
  t: Translate,
): LocationOption[] {
  return codes.map((code) => ({
    code,
    label: t(`location.${code}`, { code }),
  }));
}

/**
 * The sensor's location: its assigned code, else one inferred from its name
 * (shorthand like "front left", or a location label in any loaded language).
 */
export function locationCodeForClient(
  client: AdaptedClient,
  codes: readonly string[],
  options: readonly LocationOption[],
  labelsInAllLanguages: (code: string) => string[],
): string {
  const explicit = String(client.location_code || "").trim();
  if (explicit && codes.includes(explicit)) {
    return explicit;
  }
  const name = String(client.name || "").trim();
  if (!name) {
    return "";
  }
  const normalized = name
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  for (const [token, code] of Object.entries(SHORTHAND_LOCATIONS)) {
    if (normalized.includes(token) && codes.includes(code)) {
      return code;
    }
  }
  for (const code of codes) {
    if (labelsInAllLanguages(code).includes(name)) {
      return code;
    }
  }
  return options.find((option) => option.label === name)?.code ?? "";
}
