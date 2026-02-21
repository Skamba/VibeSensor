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
