import assert from "node:assert/strict";

import { computed, signal, useSignalProperties } from "../src/app/ui_signals";

const MODEL_KEYS = ["hidden", "text"] as const;

function createModelSignals() {
  const hidden = signal(true);
  const text = signal("Idle");
  const model = computed(() => ({
    hidden: hidden.value,
    text: text.value,
  }));
  return { hidden, model, text };
}

async function runUseSignalPropertiesSignalCacheTest(): Promise<void> {
  const first = createModelSignals();
  const second = createModelSignals();

  const firstProperties = useSignalProperties(first.model, MODEL_KEYS);
  const firstPropertiesAgain = useSignalProperties(first.model, MODEL_KEYS);
  const secondProperties = useSignalProperties(second.model, MODEL_KEYS);

  assert.equal(firstProperties, firstPropertiesAgain);
  assert.equal(firstProperties.hidden, firstPropertiesAgain.hidden);
  assert.equal(firstProperties.text, firstPropertiesAgain.text);
  assert.notEqual(firstProperties, secondProperties);

  assert.equal(firstProperties.hidden.value, true);
  assert.equal(firstProperties.text.value, "Idle");

  first.hidden.value = false;
  first.text.value = "Running";

  assert.equal(firstProperties.hidden.value, false);
  assert.equal(firstProperties.text.value, "Running");
  assert.equal(secondProperties.hidden.value, true);
  assert.equal(secondProperties.text.value, "Idle");
}

await runUseSignalPropertiesSignalCacheTest();
console.log("PASS useSignalProperties caches signal projections without hooks");
