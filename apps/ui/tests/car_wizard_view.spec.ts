import { expect, test } from "@playwright/test";

import {
  renderWizardGearboxOptions,
  renderWizardModelOptions,
  renderWizardTireOptions,
  syncCarWizardStepState,
  writeCarWizardTireInputs,
} from "../src/app/views/car_wizard_view";

type ClassListStub = {
  add(name: string): void;
  remove(name: string): void;
  toggle(name: string, force?: boolean): void;
  contains(name: string): boolean;
};

type ElementStub = HTMLElement & {
  classList: ClassListStub;
  getAttribute(name: string): string | null;
};

function createClassList(initial: string[] = []): ClassListStub {
  const active = new Set(initial);
  return {
    add(name: string): void {
      active.add(name);
    },
    remove(name: string): void {
      active.delete(name);
    },
    toggle(name: string, force?: boolean): void {
      if (typeof force === "boolean") {
        if (force) active.add(name);
        else active.delete(name);
        return;
      }
      if (active.has(name)) active.delete(name);
      else active.add(name);
    },
    contains(name: string): boolean {
      return active.has(name);
    },
  };
}

function createElement(attributes: Record<string, string> = {}): ElementStub {
  return {
    classList: createClassList(),
    getAttribute(name: string): string | null {
      return attributes[name] ?? null;
    },
  } as unknown as ElementStub;
}

function createInput(): HTMLInputElement {
  return {
    value: "",
  } as unknown as HTMLInputElement;
}

test.describe("car wizard view helpers", () => {
  test("syncCarWizardStepState updates step, dot, and back-button state", () => {
    const wizardSteps = Array.from({ length: 5 }, () => createElement());
    const wizardStepDots = Array.from({ length: 5 }, (_, index) =>
      createElement({ "data-step": String(index) }));
    const wizardBackBtn = {
      style: { display: "" },
    } as unknown as HTMLButtonElement;

    syncCarWizardStepState({ wizardSteps, wizardStepDots, wizardBackBtn }, 3);

    expect(wizardSteps[3].classList.contains("active")).toBe(true);
    expect(wizardSteps[2].classList.contains("active")).toBe(false);
    expect(wizardStepDots[3].classList.contains("active")).toBe(true);
    expect(wizardStepDots[2].classList.contains("done")).toBe(true);
    expect(wizardBackBtn.style.display).toBe("");

    syncCarWizardStepState({ wizardSteps, wizardStepDots, wizardBackBtn }, 0);
    expect(wizardSteps[0].classList.contains("active")).toBe(true);
    expect(wizardStepDots[0].classList.contains("active")).toBe(true);
    expect(wizardStepDots[1].classList.contains("done")).toBe(false);
    expect(wizardBackBtn.style.display).toBe("none");
  });

  test("render helpers produce the expected wizard option markup", () => {
    const escapeHtml = (value: unknown) => String(value ?? "");
    const fmt = (value: number, digits = 0) => Number(value).toFixed(digits);
    const models: Parameters<typeof renderWizardModelOptions>[0] = [{
      model: "Roadster",
      tire_width_mm: 245,
      tire_aspect_pct: 40,
      rim_in: 18,
      variants: [],
      gearboxes: [],
      tire_options: [],
    }];
    const tireOptions: Parameters<typeof renderWizardTireOptions>[0] = [{
      name: "Sport",
      tire_width_mm: 245,
      tire_aspect_pct: 40,
      rim_in: 18,
    }];
    const gearboxes: Parameters<typeof renderWizardGearboxOptions>[0] = [{
      name: "6-speed",
      final_drive_ratio: 3.91,
      top_gear_ratio: 0.82,
    }];

    expect(renderWizardModelOptions(models, escapeHtml)).toContain('data-idx="0"');
    expect(renderWizardModelOptions(models, escapeHtml)).toContain("245/40R18");
    expect(renderWizardTireOptions(tireOptions, escapeHtml)).toContain("selected");
    expect(renderWizardGearboxOptions(gearboxes, { escapeHtml, fmt })).toContain("FD: 3.91");
    expect(renderWizardGearboxOptions(gearboxes, { escapeHtml, fmt })).toContain("Top Gear: 0.82");
  });

  test("writeCarWizardTireInputs syncs the selected tire dimensions into manual inputs", () => {
    const els: Parameters<typeof writeCarWizardTireInputs>[0] = {
      wizTireWidthInput: createInput(),
      wizTireAspectInput: createInput(),
      wizRimInput: createInput(),
    };
    const tire: Parameters<typeof writeCarWizardTireInputs>[1] = {
      name: "Touring",
      tire_width_mm: 225,
      tire_aspect_pct: 50,
      rim_in: 17,
    };

    writeCarWizardTireInputs(els, tire);

    expect(els.wizTireWidthInput?.value).toBe("225");
    expect(els.wizTireAspectInput?.value).toBe("50");
    expect(els.wizRimInput?.value).toBe("17");
  });
});
