import type { CarLibraryTireOption } from "../../transport/http_models";
import {
  DEFAULT_CARS_WIZARD_MANUAL_INPUTS,
  readWizardManualGearboxValues,
  readWizardManualTireValues,
  type ManualGearboxValues,
  type ManualTireValues,
} from "./cars_wizard_state";
import {
  batch,
  computed,
  signal,
  type ReadonlySignal,
  type Signal,
} from "../ui_signals";

export interface CarsFeatureManualInputState {
  finalDrive: string;
  rim: string;
  tireAspect: string;
  tireWidth: string;
  topGear: string;
}

export interface CarsFeatureManualInputStore {
  readonly finalDrive: Signal<string>;
  readonly rim: Signal<string>;
  readonly tireAspect: Signal<string>;
  readonly tireWidth: Signal<string>;
  readonly topGear: Signal<string>;
  readonly manualGearbox: ReadonlySignal<ManualGearboxValues | null>;
  readonly manualTire: ReadonlySignal<ManualTireValues | null>;
  read(): CarsFeatureManualInputState;
  write(inputs: CarsFeatureManualInputState): void;
}

export function cloneManualInputs(inputs: CarsFeatureManualInputState): CarsFeatureManualInputState {
  return { ...inputs };
}

function parsePositiveValue(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function firstMissingManualInputField(
  inputs: CarsFeatureManualInputState,
): keyof CarsFeatureManualInputState | null {
  if (parsePositiveValue(inputs.tireWidth) == null) {
    return "tireWidth";
  }
  if (parsePositiveValue(inputs.tireAspect) == null) {
    return "tireAspect";
  }
  if (parsePositiveValue(inputs.rim) == null) {
    return "rim";
  }
  if (parsePositiveValue(inputs.finalDrive) == null) {
    return "finalDrive";
  }
  if (parsePositiveValue(inputs.topGear) == null) {
    return "topGear";
  }
  return null;
}

export function tireInputsFromOption(
  option: CarLibraryTireOption,
  current: CarsFeatureManualInputState,
): CarsFeatureManualInputState {
  return {
    ...current,
    rim: String(option.rim_in),
    tireAspect: String(option.tire_aspect_pct),
    tireWidth: String(option.tire_width_mm),
  };
}

export function createCarsManualInputStore(
  step: ReadonlySignal<number>,
): CarsFeatureManualInputStore {
  const finalDrive = signal<string>(DEFAULT_CARS_WIZARD_MANUAL_INPUTS.finalDrive);
  const rim = signal<string>(DEFAULT_CARS_WIZARD_MANUAL_INPUTS.rim);
  const tireAspect = signal<string>(DEFAULT_CARS_WIZARD_MANUAL_INPUTS.tireAspect);
  const tireWidth = signal<string>(DEFAULT_CARS_WIZARD_MANUAL_INPUTS.tireWidth);
  const topGear = signal<string>(DEFAULT_CARS_WIZARD_MANUAL_INPUTS.topGear);

  function read(): CarsFeatureManualInputState {
    return {
      finalDrive: finalDrive.value,
      rim: rim.value,
      tireAspect: tireAspect.value,
      tireWidth: tireWidth.value,
      topGear: topGear.value,
    };
  }

  function write(inputs: CarsFeatureManualInputState): void {
    batch(() => {
      finalDrive.value = inputs.finalDrive;
      rim.value = inputs.rim;
      tireAspect.value = inputs.tireAspect;
      tireWidth.value = inputs.tireWidth;
      topGear.value = inputs.topGear;
    });
  }

  return {
    finalDrive,
    rim,
    tireAspect,
    tireWidth,
    topGear,
    manualGearbox: computed(() =>
      readWizardManualGearboxValues(step.value, {
        finalDrive: finalDrive.value,
        topGear: topGear.value,
      })
    ),
    manualTire: computed(() =>
      readWizardManualTireValues(step.value, {
        aspect: tireAspect.value,
        rim: rim.value,
        width: tireWidth.value,
      })
    ),
    read,
    write,
  };
}
