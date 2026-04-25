import type { CarLibraryTireOption } from "../../api/types";

type FormatNumber = (value: number, digits?: number) => string;

interface TireDimensions {
  width_mm: number;
  aspect_pct: number;
  rim_in: number;
}

type AspectsRecord = Record<string, number | string | null | undefined>;

function isPositiveNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function formatRim(rimIn: number, fmt: FormatNumber): string {
  return fmt(rimIn, Number.isInteger(rimIn) ? 0 : 1);
}

export function tireOptionFront(option: CarLibraryTireOption): TireDimensions | null {
  if (option.front) {
    return option.front;
  }
  if (
    isPositiveNumber(option.tire_width_mm)
    && isPositiveNumber(option.tire_aspect_pct)
    && isPositiveNumber(option.rim_in)
  ) {
    return {
      width_mm: option.tire_width_mm,
      aspect_pct: option.tire_aspect_pct,
      rim_in: option.rim_in,
    };
  }
  return null;
}

export function tireOptionRear(option: CarLibraryTireOption): TireDimensions | null {
  return option.rear ?? tireOptionFront(option);
}

export function tireOptionIsStaggered(option: CarLibraryTireOption): boolean {
  const front = tireOptionFront(option);
  const rear = tireOptionRear(option);
  if (!front || !rear) {
    return false;
  }
  return front.width_mm !== rear.width_mm
    || front.aspect_pct !== rear.aspect_pct
    || front.rim_in !== rear.rim_in;
}

function formatTireSize(size: TireDimensions, fmt: FormatNumber): string {
  return `${fmt(size.width_mm, 0)}/${fmt(size.aspect_pct, 0)}R${formatRim(size.rim_in, fmt)}`;
}

export function formatCarLibraryTireOption(
  option: CarLibraryTireOption,
  fmt: FormatNumber,
): string | null {
  const front = tireOptionFront(option);
  const rear = tireOptionRear(option);
  if (!front || !rear) {
    return null;
  }
  if (!tireOptionIsStaggered(option)) {
    return formatTireSize(front, fmt);
  }
  return `Front ${formatTireSize(front, fmt)} · Rear ${formatTireSize(rear, fmt)}`;
}

function tireFromAspects(
  aspects: AspectsRecord,
  prefix: "" | "front_" | "rear_",
): TireDimensions | null {
  const width = aspects[`${prefix}tire_width_mm`];
  const aspect = aspects[`${prefix}tire_aspect_pct`];
  const rim = aspects[`${prefix}rim_in`];
  if (!isPositiveNumber(width) || !isPositiveNumber(aspect) || !isPositiveNumber(rim)) {
    return null;
  }
  return {
    width_mm: width,
    aspect_pct: aspect,
    rim_in: rim,
  };
}

export function formatSavedCarTireSummary(
  aspects: AspectsRecord | null | undefined,
  fmt: FormatNumber,
  missingText: string,
): string {
  if (!aspects) {
    return missingText;
  }
  const front = tireFromAspects(aspects, "front_") ?? tireFromAspects(aspects, "");
  const rear = tireFromAspects(aspects, "rear_") ?? front;
  if (!front || !rear) {
    return missingText;
  }
  if (
    front.width_mm === rear.width_mm
    && front.aspect_pct === rear.aspect_pct
    && front.rim_in === rear.rim_in
  ) {
    return formatTireSize(front, fmt);
  }
  return `Front ${formatTireSize(front, fmt)} · Rear ${formatTireSize(rear, fmt)}`;
}

export function tireSetupAspectsFromOption(
  option: CarLibraryTireOption,
): Record<string, number | string> {
  const front = tireOptionFront(option);
  const rear = tireOptionRear(option);
  if (!front || !rear) {
    return {};
  }
  const payload: Record<string, number | string> = {
    rim_in: option.rim_in,
    tire_aspect_pct: option.tire_aspect_pct,
    tire_width_mm: option.tire_width_mm,
  };
  if (tireOptionIsStaggered(option) || option.default_axle_for_speed !== "rear") {
    payload.front_tire_width_mm = front.width_mm;
    payload.front_tire_aspect_pct = front.aspect_pct;
    payload.front_rim_in = front.rim_in;
    payload.rear_tire_width_mm = rear.width_mm;
    payload.rear_tire_aspect_pct = rear.aspect_pct;
    payload.rear_rim_in = rear.rim_in;
    payload.default_axle_for_speed = option.default_axle_for_speed;
  }
  return payload;
}
