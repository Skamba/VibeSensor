export type CarRecord = {
  id: string;
  name: string;
  type: string;
  aspects: Record<string, number>;
  [key: string]: unknown;
};

export type CarsPayload = {
  cars: CarRecord[];
  activeCarId: string | null;
};

export type SpeedSourcePayload = {
  speedSource: string;
  manualSpeedKph: number | null;
  staleTimeoutS: number;
  fallbackMode: string;
};

export type SpeedSourceStatusPayload = {
  gps_enabled: boolean;
  connection_state: "disabled" | "disconnected" | "connected" | "stale";
  device: string | null;
  last_update_age_s: number | null;
  raw_speed_kmh: number | null;
  effective_speed_kmh: number | null;
  last_error: string | null;
  reconnect_delay_s: number | null;
  fallback_active: boolean;
  stale_timeout_s: number;
  fallback_mode: string;
};

export type HistoryEntry = {
  run_id: string;
  status: string;
  start_time_utc: string;
  end_time_utc?: string;
  sample_count: number;
};

export type CarLibraryModel = {
  model: string;
  brand: string;
  type: string;
  tire_width_mm: number;
  tire_aspect_pct: number;
  rim_in: number;
  gearboxes: CarLibraryGearbox[];
  tire_options: CarLibraryTireOption[];
  [key: string]: unknown;
};

export type CarLibraryGearbox = {
  name: string;
  final_drive_ratio: number;
  top_gear_ratio: number;
};

export type CarLibraryTireOption = {
  name: string;
  tire_width_mm: number;
  tire_aspect_pct: number;
  rim_in: number;
};

export type UpdateIssue = {
  phase: string;
  message: string;
  detail: string;
};

export type UpdateStatusPayload = {
  state: "idle" | "running" | "success" | "failed";
  phase: string;
  started_at: number | null;
  finished_at: number | null;
  last_success_at: number | null;
  ssid: string;
  issues: UpdateIssue[];
  log_tail: string[];
  exit_code: number | null;
};
