import { releaseProxy, wrap } from "comlink";

import type {
  SpectrumFramePreparer,
  SpectrumPreparedFrameData,
  SpectrumFramePreparationInput,
} from "./spectrum_frame_preparer";

interface SpectrumFramePreparerWorkerApi {
  prepare(input: SpectrumFramePreparationInput): Promise<SpectrumPreparedFrameData>;
  [releaseProxy]?: () => void;
}

export function createWorkerSpectrumFramePreparer(): SpectrumFramePreparer {
  const worker = new Worker(
    new URL("./spectrum_frame_preparer_worker.ts", import.meta.url),
    { type: "module" },
  );
  const proxy = wrap<SpectrumFramePreparerWorkerApi>(worker);

  return {
    dispose(): void {
      proxy[releaseProxy]?.();
      worker.terminate();
    },
    prepare(input): Promise<SpectrumPreparedFrameData> {
      return proxy.prepare(input);
    },
  };
}
