import { convertSpectrumAmplitudesToDbInPlace } from "../../spectrum";
import { chartSeriesPalette } from "../../theme";
import type { SpectrumClientData } from "../../transport/live_models";
import type { SpectrumHeavyFrame } from "../spectrum_animation";
import {
  freqGridsMatch,
  type SpectrumNumericSeries,
  type SpectrumSeriesEntry,
} from "./spectrum_shared";

const EMPTY_FREQ_AXIS: number[] = [];

export interface SpectrumFramePreparationClient {
  id: string;
  name: string;
  connected: boolean;
}

export interface SpectrumFramePreparationInput {
  clients: readonly SpectrumFramePreparationClient[];
  spectraByClient: Record<string, SpectrumClientData | undefined>;
}

export interface SpectrumPreparedFrameData {
  entries: SpectrumSeriesEntry[];
  freqAxis: SpectrumNumericSeries;
  frame: SpectrumHeavyFrame | null;
  hasData: boolean;
}

export interface SpectrumFramePreparer {
  dispose(): void;
  prepare(input: SpectrumFramePreparationInput): Promise<SpectrumPreparedFrameData>;
}

interface PreparedSpectrumCacheEntry {
  sourceCombined: readonly number[];
  sourceFreq: readonly number[];
  sourceLength: number;
  targetFreq: readonly number[];
  values: number[];
}

interface SpectrumFramePreparerCore {
  dispose(): void;
  prepare(input: SpectrumFramePreparationInput): SpectrumPreparedFrameData;
}

export function createInlineSpectrumFramePreparer(): SpectrumFramePreparer {
  const core = createSpectrumFramePreparerCore();
  return {
    dispose(): void {
      core.dispose();
    },
    async prepare(input): Promise<SpectrumPreparedFrameData> {
      return core.prepare(input);
    },
  };
}

export function createSpectrumFramePreparerCore(): SpectrumFramePreparerCore {
  const preparedSpectrumCache = new Map<string, PreparedSpectrumCacheEntry>();

  function dispose(): void {
    preparedSpectrumCache.clear();
  }

  function prepare(input: SpectrumFramePreparationInput): SpectrumPreparedFrameData {
    const entries: SpectrumSeriesEntry[] = [];
    let targetFreq: number[] = [];

    for (const [index, client] of input.clients.entries()) {
      if (!client?.connected) {
        continue;
      }
      const spectrum = input.spectraByClient[client.id];
      if (!spectrum || !Array.isArray(spectrum.combined)) {
        continue;
      }
      const clientFreq = Array.isArray(spectrum.freq) && spectrum.freq.length
        ? spectrum.freq
        : EMPTY_FREQ_AXIS;
      const length = Math.min(clientFreq.length, spectrum.combined.length);
      if (!length) {
        continue;
      }

      if (!targetFreq.length) {
        targetFreq = clientFreq.length === length ? clientFreq : clientFreq.slice(0, length);
      }

      const preparedValues = getPreparedSpectrumValues(
        client.id,
        spectrum.combined,
        clientFreq,
        length,
        targetFreq,
      );
      if (!preparedValues.length) {
        continue;
      }

      entries.push({
        id: client.id,
        label: client.name || client.id,
        color: colorForClient(index),
        values: preparedValues,
      });
    }

    if (!targetFreq.length || !entries.length) {
      return {
        entries: [],
        freqAxis: [],
        frame: null,
        hasData: false,
      };
    }

    let minLen = targetFreq.length;
    const seriesIds = new Array<string>(entries.length);
    const frameValues = new Array<SpectrumNumericSeries>(entries.length);
    for (let index = 0; index < entries.length; index += 1) {
      const entry = entries[index];
      seriesIds[index] = entry.id;
      frameValues[index] = entry.values;
      if (entry.values.length < minLen) {
        minLen = entry.values.length;
      }
    }
    if (minLen < targetFreq.length) {
      targetFreq = targetFreq.slice(0, minLen);
      for (let index = 0; index < frameValues.length; index += 1) {
        const frameValuesEntry = frameValues[index];
        const entry = entries[index];
        if (!frameValuesEntry || !entry || frameValuesEntry.length === minLen) {
          continue;
        }
        const trimmedValues = sliceSeries(frameValuesEntry, minLen);
        frameValues[index] = trimmedValues;
        entry.values = trimmedValues;
      }
    }
    const frame: SpectrumHeavyFrame = {
      seriesIds,
      freq: targetFreq,
      values: frameValues,
    };

    return {
      entries,
      freqAxis: frame.freq,
      frame,
      hasData: true,
    };
  }

  function getPreparedSpectrumValues(
    clientId: string,
    combined: readonly number[],
    clientFreq: readonly number[],
    sourceLength: number,
    targetFreq: readonly number[],
  ): number[] {
    const cached = preparedSpectrumCache.get(clientId);
    if (
      cached
      && cached.sourceCombined === combined
      && cached.sourceFreq === clientFreq
      && cached.sourceLength === sourceLength
      && cached.targetFreq.length === targetFreq.length
      && (
        cached.targetFreq === targetFreq
        || freqGridsMatch(cached.targetFreq, targetFreq, targetFreq.length)
      )
    ) {
      return cached.values;
    }

    const needsInterpolation = clientFreq.length !== targetFreq.length
      || !freqGridsMatch(clientFreq, targetFreq, sourceLength);
    const preparedValues = needsInterpolation
      ? interpolateToTarget(clientFreq, combined, targetFreq, sourceLength)
      : combined.slice(0, sourceLength);

    if (!preparedValues.length) {
      preparedSpectrumCache.delete(clientId);
      return preparedValues;
    }

    convertSpectrumAmplitudesToDbInPlace(preparedValues);
    preparedSpectrumCache.set(clientId, {
      sourceCombined: combined,
      sourceFreq: clientFreq,
      sourceLength,
      targetFreq,
      values: preparedValues,
    });
    return preparedValues;
  }

  return {
    dispose,
    prepare,
  };
}

function colorForClient(index: number): string {
  return chartSeriesPalette[index % chartSeriesPalette.length];
}

function sliceSeries(values: SpectrumNumericSeries, endExclusive: number): number[] {
  return Array.from(values.slice(0, endExclusive));
}

function interpolateToTarget(
  clientFreq: readonly number[],
  combined: readonly number[],
  targetFreq: readonly number[],
  sourceLength: number,
): number[] {
  const output = new Array<number>(targetFreq.length);
  let sourceIndex = 0;
  for (let targetIndex = 0; targetIndex < targetFreq.length; targetIndex += 1) {
    const targetHz = targetFreq[targetIndex];
    while (
      sourceIndex + 1 < sourceLength
      && clientFreq[sourceIndex + 1] !== undefined
      && clientFreq[sourceIndex + 1] < targetHz
    ) {
      sourceIndex += 1;
    }

    const lowerFreq = clientFreq[sourceIndex];
    const lowerValue = combined[sourceIndex];
    const upperIndex = Math.min(sourceIndex + 1, sourceLength - 1);
    const upperFreq = clientFreq[upperIndex];
    const upperValue = combined[upperIndex];
    if (
      lowerFreq === undefined
      || lowerValue === undefined
      || upperFreq === undefined
      || upperValue === undefined
    ) {
      output[targetIndex] = Number.NaN;
      continue;
    }
    if (upperFreq <= lowerFreq || upperIndex === sourceIndex) {
      output[targetIndex] = lowerValue;
      continue;
    }
    const alpha = Math.min(1, Math.max(0, (targetHz - lowerFreq) / (upperFreq - lowerFreq)));
    output[targetIndex] = lowerValue + ((upperValue - lowerValue) * alpha);
  }
  return output;
}
