import { expect, test } from "@playwright/test";

import {
  createSpectrumTweenDerivedState,
  type SpectrumHeavyFrame,
} from "../src/app/spectrum_animation";
import { signal } from "../src/app/ui_signals";

const baseFrame: SpectrumHeavyFrame = {
  seriesIds: ["sensor-1", "sensor-2"],
  freq: [10, 20, 30],
  values: [[1, 2, 3], [4, 5, 6]],
};

test.describe("spectrum tween derived state", () => {
  test("tracks compatibility and interpolated frame from signal inputs", () => {
    const previous = signal<SpectrumHeavyFrame | null>(baseFrame);
    const next = signal<SpectrumHeavyFrame | null>({
      seriesIds: ["sensor-1", "sensor-2"],
      freq: [10, 20, 30],
      values: [[3, 5, 7], [7, 9, 11]],
    });
    const alpha = signal(0.5);
    const tween = createSpectrumTweenDerivedState(previous, next, alpha);

    expect(tween.canTween.value).toBe(true);
    expect(tween.frame.value?.values).toEqual([[2, 3.5, 5], [5.5, 7, 8.5]]);

    next.value = {
      seriesIds: ["sensor-2", "sensor-1"],
      freq: [10, 20, 30],
      values: [[3, 5, 7], [7, 9, 11]],
    };

    expect(tween.canTween.value).toBe(false);
    expect(tween.frame.value).toBe(next.value);
  });
});
