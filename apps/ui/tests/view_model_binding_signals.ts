import assert from "node:assert/strict";

import { options } from "preact";

import {
  computed,
  signal,
  useComputed,
  type ReadonlySignal,
} from "../src/app/ui_signals";
import {
  createDeferredViewModel,
  useDeferredViewModel,
} from "../src/app/views/view_model_binding";
import { mountSignalView } from "./dom_render_test_support";

function requireElement<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  assert.ok(element, `Expected element matching ${selector}`);
  return element;
}

async function runDeferredViewModelSignalTest(): Promise<void> {
  const firstText = signal("Idle");
  const secondText = signal("Ready");
  const firstModel = computed(() => ({ text: firstText.value }));
  const secondModel = computed(() => ({ text: secondText.value }));
  const binding = createDeferredViewModel<{ text: string }>();
  const previousDiffed = options.diffed;
  let renderCount = 0;
  options.diffed = (vnode) => {
    if (typeof vnode.type === "function" && vnode.type.name === "DeferredViewModelProbe") {
      renderCount += 1;
    }
    previousDiffed?.(vnode);
  };

  const harness = await mountSignalView(async () => {
    const { h, render } = await import("preact");
    return (host) => {
      function DeferredViewModelProbe(props: {
        model: ReadonlySignal<ReadonlySignal<{ text: string }> | null>;
      }) {
        const model = useDeferredViewModel(props.model, { text: "Loading" });
        const text = useComputed(() => model.value.text);
        return h("span", { id: "bindingProbe" }, text);
      }

      render(h(DeferredViewModelProbe, { model: binding.model }), host);
      return {};
    };
  });

  try {
    await harness.flush();
    assert.equal(renderCount, 1);
    assert.equal(requireElement(harness.host, "#bindingProbe").textContent, "Loading");

    binding.bind(firstModel);
    await harness.flush();
    assert.equal(renderCount, 1);
    assert.equal(requireElement(harness.host, "#bindingProbe").textContent, "Idle");

    firstText.value = "Running";
    await harness.flush();
    assert.equal(renderCount, 1);
    assert.equal(requireElement(harness.host, "#bindingProbe").textContent, "Running");

    binding.bind(secondModel);
    await harness.flush();
    assert.equal(renderCount, 1);
    assert.equal(requireElement(harness.host, "#bindingProbe").textContent, "Ready");

    firstText.value = "Stale";
    await harness.flush();
    assert.equal(requireElement(harness.host, "#bindingProbe").textContent, "Ready");

    secondText.value = "Flashing";
    await harness.flush();
    assert.equal(renderCount, 1);
    assert.equal(requireElement(harness.host, "#bindingProbe").textContent, "Flashing");
  } finally {
    options.diffed = previousDiffed;
    harness.cleanup();
  }
}

await runDeferredViewModelSignalTest();
console.log("PASS deferred view model signals rebind without rerender");
