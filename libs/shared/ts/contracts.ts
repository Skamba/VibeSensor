export const METRIC_FIELDS = {
  vibration_strength_db: "vibration_strength_db",
  strength_bucket: "strength_bucket",
} as const;

export const REPORT_FIELDS = {
  run_id: "run_id",
  timestamp_utc: "timestamp_utc",
  client_id: "client_id",
  client_name: "client_name",
  speed_kmh: "speed_kmh",
  dominant_freq_hz: "dominant_freq_hz",
  vibration_strength_db: "vibration_strength_db",
  strength_bucket: "strength_bucket",
  top_peaks: "top_peaks",
} as const;

export const NETWORK_PORTS = {
  server_udp_data: 9000,
  server_udp_control: 9001,
  firmware_control_port_base: 9010,
} as const;

export const LOCATION_CODES = [
  "front_left_wheel",
  "front_right_wheel",
  "rear_left_wheel",
  "rear_right_wheel",
  "transmission",
  "driveshaft_tunnel",
  "engine_bay",
  "front_subframe",
  "rear_subframe",
  "driver_seat",
  "front_passenger_seat",
  "rear_left_seat",
  "rear_center_seat",
  "rear_right_seat",
  "trunk",
] as const;
