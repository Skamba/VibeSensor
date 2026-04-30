import { describe, expect, test } from "vitest";
import {
  createCarsFeatureWorkflow,
  type CarsFeatureFocusTarget,
  type CarsFeatureWorkflowViewPorts,
} from "../src/app/features/cars_feature_workflow";
import type { CarLibraryModel } from "../src/api/types";
import { createTestQueryClient } from "./query_client_test_support";

type WorkflowHarness = {
  focuses: CarsFeatureFocusTarget[];
};

type Deferred<T> = {
  promise: Promise<T>;
  reject(reason?: unknown): void;
  resolve(value: T): void;
};

function createHarness(): WorkflowHarness {
  return {
    focuses: [],
  };
}

function createViewPorts(
  harness: WorkflowHarness,
): CarsFeatureWorkflowViewPorts {
  return {
    focus(target): void {
      harness.focuses.push(target);
    },
  };
}

function createTranslator(): (key: string) => string {
  return (key) => key;
}

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

async function flushAsyncWork(rounds = 6): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise<void>((resolve) => {
      setImmediate(() => resolve());
    });
  }
}

function makeModel(model: string, carType: string): CarLibraryModel {
  return {
    brand: "BMW",
    gearboxes: [],
    model,
    rim_in: 21,
    tire_aspect_pct: 40,
    tire_options: [],
    tire_width_mm: 275,
    type: carType,
    variants: [],
  };
}

describe("createCarsFeatureWorkflow async lifecycle", () => {
  test("ignores brand load results after the wizard closes", async () => {
    const harness = createHarness();
    const brands = createDeferred<string[]>();
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async () => undefined,
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return brands.promise;
        },
      },
      view: createViewPorts(harness),
    });

    const opening = workflow.openWizard();
    await flushAsyncWork();
    workflow.closeWizard();
    brands.resolve(["BMW"]);
    await opening;

    expect(workflow.getRenderState().isOpen).toBe(false);
    expect(workflow.getRenderState().brandOptions.status).toBe("loading");
    expect(harness.focuses).toEqual(["close"]);
  });

  test("ignores stale type results after navigating back", async () => {
    const harness = createHarness();
    const types = createDeferred<string[]>();
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async () => undefined,
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return ["BMW"];
        },
        async loadTypes() {
          return types.promise;
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();
    const selectingBrand = workflow.selectBrand("BMW");
    await flushAsyncWork();
    await workflow.goBack();
    types.resolve(["SUV"]);
    await selectingBrand;

    expect(workflow.getRenderState().step).toBe(0);
    expect(workflow.getRenderState().typeOptions.status).toBe("loading");
    expect(harness.focuses).not.toContain("type-option");
  });

  test("keeps newer model options when an older model load resolves later", async () => {
    const harness = createHarness();
    const suvModels = createDeferred<CarLibraryModel[]>();
    const sedanModels = createDeferred<CarLibraryModel[]>();
    const workflow = createCarsFeatureWorkflow({
      addCarFromWizard: async () => undefined,
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      queryClient: createTestQueryClient(),
      t: createTranslator(),
      transport: {
        async loadBrands() {
          return ["BMW"];
        },
        async loadModels(_brand, carType) {
          return carType === "SUV" ? suvModels.promise : sedanModels.promise;
        },
        async loadTypes() {
          return ["SUV", "Sedan"];
        },
      },
      view: createViewPorts(harness),
    });

    await workflow.openWizard();
    await workflow.selectBrand("BMW");
    const selectingSuv = workflow.selectType("SUV");
    await flushAsyncWork();
    const selectingSedan = workflow.selectType("Sedan");
    await flushAsyncWork();
    sedanModels.resolve([makeModel("M3", "Sedan")]);
    await selectingSedan;
    suvModels.resolve([makeModel("X5", "SUV")]);
    await selectingSuv;

    expect(workflow.getRenderState().modelOptions).toMatchObject({
      status: "ready",
      options: [expect.objectContaining({ model: "M3" })],
    });
    expect(workflow.getRenderState().step).toBe(2);
  });
});
