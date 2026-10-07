import type { AdaptedClient } from "../../transport/live_models";

/**
 * Settings > Sensors places sensors on a top-down car diagram: the owner
 * selects a sensor, then taps the spot where it is mounted.
 */

type Translate = (key: string, vars?: Record<string, unknown>) => string;

/** A tap target on the car diagram, front at the top, driver on the left. */
export interface Spot {
  code: string;
  /** Grid row (1 = the front bumper) and column (1 and 5 are the wheels). */
  row: number;
  col: number;
  span: number;
  wheel: boolean;
}

const wheel = (code: string, row: number, col: number): Spot => ({
  code,
  row,
  col,
  span: 1,
  wheel: true,
});
const zone = (code: string, row: number, col: number, span = 1): Spot => ({
  code,
  row,
  col,
  span,
  wheel: false,
});

/** Every location the server accepts, where it physically is. */
export const SPOTS: readonly Spot[] = [
  zone("engine_bay", 1, 2, 3),
  wheel("front_left_wheel", 2, 1),
  zone("front_subframe", 2, 2, 3),
  wheel("front_right_wheel", 2, 5),
  zone("transmission", 3, 2, 3),
  zone("driver_seat", 4, 2),
  zone("driveshaft_tunnel", 4, 3),
  zone("front_passenger_seat", 4, 4),
  zone("rear_left_seat", 5, 2),
  zone("rear_center_seat", 5, 3),
  zone("rear_right_seat", 5, 4),
  wheel("rear_left_wheel", 6, 1),
  zone("rear_subframe", 6, 2, 3),
  wheel("rear_right_wheel", 6, 5),
  zone("trunk", 7, 2, 3),
];

/** Single-column spots (wheels, seats, tunnel) are narrow: a short label. */
const SHORT_LABEL_CODES: ReadonlySet<string> = new Set(
  SPOTS.filter((spot) => spot.span === 1).map((spot) => spot.code),
);

/** The text inside a spot; its accessible name always uses the full label. */
export function spotLabel(code: string, t: Translate): string {
  return SHORT_LABEL_CODES.has(code)
    ? t(`settings.sensors.spot.${code}`)
    : t(`location.${code}`);
}

export interface PlacementSensor {
  id: string;
  name: string;
  mac: string;
  /** The last two bytes of the MAC: what tells two sensors apart at a glance. */
  shortId: string;
  connected: boolean;
  /** The assigned location code, or "" while unplaced. */
  code: string;
  firmwareVersion: string;
  firmwareStatus: AdaptedClient["firmware_status"];
}

/**
 * `undefined` follows the next sensor to place; `null` is "nothing selected"
 * (the owner closed the selection); a string is the sensor the owner picked.
 */
export type Choice = string | null | undefined;

export interface Placement {
  sensors: PlacementSensor[];
  unplaced: PlacementSensor[];
  byCode: ReadonlyMap<string, PlacementSensor>;
  selected: PlacementSensor | null;
  /** The owner picked `selected`; a default pick never displaces a sensor. */
  picked: boolean;
}

export function shortSensorId(mac: string): string {
  const hex = mac.replace(/[^0-9a-f]/gi, "").toLowerCase();
  if (hex.length < 4) {
    return mac;
  }
  return `${hex.slice(-4, -2)}:${hex.slice(-2)}`;
}

function toSensor(client: AdaptedClient, code: string): PlacementSensor {
  const mac = String(client.mac_address || client.id);
  return {
    id: client.id,
    name: String(client.name || client.id).trim(),
    mac,
    shortId: shortSensorId(mac),
    connected: Boolean(client.connected),
    code,
    firmwareVersion: client.firmware_version,
    firmwareStatus: client.firmware_status,
  };
}

/** Whether tapping a spot places the selected sensor there (else selects). */
export function placesOnTap(
  placement: Placement,
  occupant: PlacementSensor | undefined,
): boolean {
  const { selected, picked } = placement;
  return Boolean(
    selected && occupant?.id !== selected.id && (picked || !occupant),
  );
}

export function placementModel(
  clients: readonly AdaptedClient[],
  locationOf: (client: AdaptedClient) => string,
  choice: Choice,
): Placement {
  const sensors = clients.map((client) => toSensor(client, locationOf(client)));
  const byCode = new Map<string, PlacementSensor>();
  const unplaced: PlacementSensor[] = [];
  for (const sensor of sensors) {
    if (sensor.code && !byCode.has(sensor.code)) {
      byCode.set(sensor.code, sensor);
    } else {
      unplaced.push(sensor);
    }
  }
  // A picked sensor that has gone (removed) falls back to the next to place.
  const pickedSensor = sensors.find((sensor) => sensor.id === choice);
  const selected =
    choice === null
      ? null
      : (pickedSensor ??
        unplaced.find((sensor) => sensor.connected) ??
        unplaced[0] ??
        null);
  return { sensors, unplaced, byCode, selected, picked: Boolean(pickedSensor) };
}

/** The sensor's name, plus its short id unless the name is its id or MAC. */
export function sensorTitle(sensor: PlacementSensor): string {
  return sensor.name === sensor.id || sensor.name === sensor.mac
    ? sensor.name
    : `${sensor.name} · ${sensor.shortId}`;
}
