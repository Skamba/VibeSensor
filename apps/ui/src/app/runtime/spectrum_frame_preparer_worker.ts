import { expose, transfer } from "comlink";

import {
  createSpectrumFramePreparerCore,
  type SpectrumPreparedFrameData,
  type SpectrumFramePreparationInput,
} from "./spectrum_frame_preparer";

interface SpectrumFramePreparerWorkerApi {
  prepare(input: SpectrumFramePreparationInput): Promise<SpectrumPreparedFrameData>;
}

const core = createSpectrumFramePreparerCore();

function collectTransferables(prepared: SpectrumPreparedFrameData): Transferable[] {
  const seen = new Set<ArrayBufferLike>();
  const transferables: Transferable[] = [];

  function addSeriesBuffer(series: Float64Array | readonly number[]): void {
    if (!(series instanceof Float64Array)) {
      return;
    }
    if (seen.has(series.buffer)) {
      return;
    }
    seen.add(series.buffer);
    transferables.push(series.buffer);
  }

  addSeriesBuffer(prepared.freqAxis);
  for (const entry of prepared.entries) {
    addSeriesBuffer(entry.values);
  }
  if (prepared.frame) {
    addSeriesBuffer(prepared.frame.freq);
    for (const values of prepared.frame.values) {
      addSeriesBuffer(values);
    }
  }
  return transferables;
}

function toTransferablePreparedFrame(prepared: SpectrumPreparedFrameData): SpectrumPreparedFrameData {
  if (!prepared.frame) {
    return prepared;
  }

  const freqAxis = Float64Array.from(prepared.frame.freq);
  const frameValues = prepared.frame.values.map((values) => Float64Array.from(values));
  return {
    entries: prepared.entries.map((entry, index) => ({
      ...entry,
      values: frameValues[index] ?? Float64Array.from(entry.values),
    })),
    freqAxis,
    frame: {
      ...prepared.frame,
      freq: freqAxis,
      values: frameValues,
    },
    hasData: prepared.hasData,
  };
}

const api: SpectrumFramePreparerWorkerApi = {
  async prepare(input): Promise<SpectrumPreparedFrameData> {
    const prepared = toTransferablePreparedFrame(core.prepare(input));
    return transfer(prepared, collectTransferables(prepared));
  },
};

expose(api);
