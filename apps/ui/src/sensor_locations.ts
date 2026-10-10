import { defaultLocationCodes } from "./constants";
import type { AdaptedClient } from "./transport/live_models";

/** Pure helpers that map sensors onto install locations. */

type Translate = (key: string, vars?: Record<string, unknown>) => string;

const KNOWN_CODES: ReadonlySet<string> = new Set(defaultLocationCodes);

/**
 * A location as a run stores it (a code like "engine_bay" or the server's
 * English label "Engine Bay") in the UI language; unknown text passes through.
 */
export function locationLabel(location: string, t: Translate): string {
  const code = location
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
  return KNOWN_CODES.has(code) ? t(`location.${code}`) : location;
}

/**
 * The location the sensor is assigned to, or "" while it is unplaced. Only the
 * assignment counts: a sensor named "front-left" is not at a wheel until the
 * owner places it there, which is also how the server's readiness counts it.
 */
export function assignedLocation(
  client: AdaptedClient,
  codes: readonly string[],
): string {
  const code = String(client.location_code || "").trim();
  return codes.includes(code) ? code : "";
}

/**
 * How Live names a sensor: its location once placed, else its own name with
 * an "unplaced" marker, so a name like "front-left" never reads as a location.
 */
export function sensorLabel(
  client: AdaptedClient,
  code: string,
  t: Translate,
): string {
  if (code) {
    return t(`location.${code}`);
  }
  return t("sensors.unplaced_name", {
    name: String(client.name || client.id).trim(),
  });
}

/**
 * The sensors that hear a band's order, named, strongest first; null where
 * none does. The server judges it by the report's rule over the last few
 * seconds (`heard_at`); a sensor the page does not know is left out.
 */
export function heardAtText(
  heardAt: readonly string[] | undefined,
  sensorName: (clientId: string) => string | null,
): string | null {
  const names = (heardAt ?? [])
    .map(sensorName)
    .filter((name): name is string => Boolean(name));
  return names.length ? names.join(", ") : null;
}
