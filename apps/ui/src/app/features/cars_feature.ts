import type { UiDomElements } from "../dom/ui_dom_registry";
import { getCarLibraryBrands, getCarLibraryModels, getCarLibraryTypes } from "../../api";
import type { CarLibraryModel, CarLibraryGearbox, CarLibraryTireOption } from "../../api";

export interface CarsFeatureDeps {
  els: UiDomElements;
  escapeHtml: (value: unknown) => string;
  fmt: (n: number, digits?: number) => string;
  addCarFromWizard: (name: string, carType: string, aspects: Record<string, number>) => Promise<void>;
}

export interface CarsFeature {
  bindWizardHandlers(): void;
}

interface WizardState {
  step: number;
  brand: string;
  carType: string;
  model: string;
  selectedModel: CarLibraryModel | null;
  selectedGearbox: CarLibraryGearbox | null;
  selectedTire: CarLibraryTireOption | null;
}

export function createCarsFeature(ctx: CarsFeatureDeps): CarsFeature {
  const { els, escapeHtml } = ctx;
  const wizState: WizardState = {
    step: 0,
    brand: "",
    carType: "",
    model: "",
    selectedModel: null,
    selectedGearbox: null,
    selectedTire: null,
  };
  const WIZARD_STEP_COUNT = 4;

  function openWizard(): void {
    wizState.step = 0;
    wizState.brand = "";
    wizState.carType = "";
    wizState.model = "";
    wizState.selectedModel = null;
    wizState.selectedGearbox = null;
    wizState.selectedTire = null;
    if (els.addCarWizard) els.addCarWizard.hidden = false;
    loadWizardStep();
  }

  function closeWizard(): void {
    if (els.addCarWizard) els.addCarWizard.hidden = true;
  }

  function buildWizardCarName(brand: string, model: string): string {
    if (brand) return `${brand} ${model || "Custom"}`;
    return model || "Custom Car";
  }

  function loadWizardStep(): void {
    for (let i = 0; i < WIZARD_STEP_COUNT; i++) {
      const stepEl = document.getElementById(`wizardStep${i}`);
      if (stepEl) stepEl.classList.toggle("active", i === wizState.step);
    }
    document.querySelectorAll(".wizard-step-dot").forEach((dot) => {
      const s = Number(dot.getAttribute("data-step"));
      dot.classList.toggle("active", s === wizState.step);
      dot.classList.toggle("done", s < wizState.step);
    });
    if (els.wizardBackBtn) els.wizardBackBtn.style.display = wizState.step > 0 ? "" : "none";
    if (wizState.step === 0) void loadBrandStep();
    else if (wizState.step === 1) void loadTypeStep();
    else if (wizState.step === 2) void loadModelStep();
    else if (wizState.step === 3) loadGearboxStep();
  }

  async function loadBrandStep(): Promise<void> {
    const container = document.getElementById("wizardBrandList");
    if (!container) return;
    container.innerHTML = "<em>Loading...</em>";
    try {
      const data = await getCarLibraryBrands() as Record<string, any>;
      container.innerHTML = (data.brands || []).map((b: string) => `<button type="button" class="wiz-opt" data-value="${escapeHtml(b)}">${escapeHtml(b)}</button>`).join("");
      container.querySelectorAll(".wiz-opt").forEach((btn) => {
        btn.addEventListener("click", () => {
          wizState.brand = btn.getAttribute("data-value") || "";
          wizState.step = 1;
          loadWizardStep();
        });
      });
    } catch (_err) {
      container.innerHTML = "<em>Could not load brands</em>";
    }
  }

  async function loadTypeStep(): Promise<void> {
    const container = document.getElementById("wizardTypeList");
    if (!container) return;
    container.innerHTML = "<em>Loading...</em>";
    try {
      const data = await getCarLibraryTypes(wizState.brand) as Record<string, any>;
      container.innerHTML = (data.types || []).map((t2: string) => `<button type="button" class="wiz-opt" data-value="${escapeHtml(t2)}">${escapeHtml(t2)}</button>`).join("");
      container.querySelectorAll(".wiz-opt").forEach((btn) => {
        btn.addEventListener("click", () => {
          wizState.carType = btn.getAttribute("data-value") || "";
          wizState.step = 2;
          loadWizardStep();
        });
      });
    } catch (_err) {
      container.innerHTML = "<em>Could not load types</em>";
    }
  }

  async function loadModelStep(): Promise<void> {
    const container = document.getElementById("wizardModelList");
    if (!container) return;
    container.innerHTML = "<em>Loading...</em>";
    try {
      const data = await getCarLibraryModels(wizState.brand, wizState.carType) as Record<string, any>;
      const models: CarLibraryModel[] = data.models || [];
      container.innerHTML = models.map((m, idx) => {
        const tireStr = `${m.tire_width_mm}/${m.tire_aspect_pct}R${m.rim_in}`;
        return `<button type="button" class="wiz-opt" data-idx="${idx}"><span>${escapeHtml(m.model)}</span><span class="wiz-opt-detail">${escapeHtml(tireStr)}</span></button>`;
      }).join("");
      container.querySelectorAll(".wiz-opt").forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = Number(btn.getAttribute("data-idx"));
          wizState.selectedModel = models[idx] || null;
          wizState.model = wizState.selectedModel?.model || "";
          wizState.selectedTire = null;
          wizState.step = 3;
          loadWizardStep();
        });
      });
    } catch (_err) {
      container.innerHTML = "<em>Could not load models</em>";
    }
  }

  function loadGearboxStep(): void {
    const tireContainer = document.getElementById("wizardTireList");
    if (tireContainer) {
      const tireOptions: CarLibraryTireOption[] = wizState.selectedModel?.tire_options || [];
      if (tireOptions.length > 0) {
        tireContainer.innerHTML = tireOptions.map((to, idx) => `<button type="button" class="wiz-opt${idx === 0 ? " selected" : ""}" data-tire-idx="${idx}"><span>${escapeHtml(to.name)}</span><span class="wiz-opt-detail">${to.tire_width_mm}/${to.tire_aspect_pct}R${to.rim_in}</span></button>`).join("");
        const defaultTire = tireOptions[0];
        wizState.selectedTire = defaultTire;
        updateWizTireInputs(defaultTire);
        tireContainer.querySelectorAll(".wiz-opt").forEach((btn) => {
          btn.addEventListener("click", () => {
            const idx = Number(btn.getAttribute("data-tire-idx"));
            wizState.selectedTire = tireOptions[idx] || defaultTire;
            updateWizTireInputs(wizState.selectedTire);
            tireContainer.querySelectorAll(".wiz-opt").forEach((b) => b.classList.remove("selected"));
            btn.classList.add("selected");
          });
        });
      } else tireContainer.innerHTML = "";
    }

    const container = document.getElementById("wizardGearboxList");
    if (!container) return;
    const gearboxes: CarLibraryGearbox[] = wizState.selectedModel?.gearboxes || [];
    if (!gearboxes.length) {
      container.innerHTML = "<em>No pre-defined gearboxes. Enter specs manually below.</em>";
      return;
    }
    container.innerHTML = gearboxes.map((gb, idx) => `<button type="button" class="wiz-opt" data-idx="${idx}"><span>${escapeHtml(gb.name)}</span><span class="wiz-opt-detail">FD: ${ctx.fmt(gb.final_drive_ratio, 2)} · Top Gear: ${ctx.fmt(gb.top_gear_ratio, 2)}</span></button>`).join("");
    container.querySelectorAll(".wiz-opt").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const idx = Number(btn.getAttribute("data-idx"));
        const gb = gearboxes[idx];
        if (!gb) return;
        const tire = wizState.selectedTire || wizState.selectedModel;
        if (!tire) return;
        const carName = `${wizState.brand} ${wizState.model}`;
        await ctx.addCarFromWizard(carName, wizState.carType, {
          tire_width_mm: tire.tire_width_mm,
          tire_aspect_pct: tire.tire_aspect_pct,
          rim_in: tire.rim_in,
          final_drive_ratio: gb.final_drive_ratio,
          current_gear_ratio: gb.top_gear_ratio,
        });
        closeWizard();
      });
    });
  }

  function updateWizTireInputs(tire: CarLibraryTireOption): void {
    const tw = document.getElementById("wizTireWidth") as HTMLInputElement | null;
    const ta = document.getElementById("wizTireAspect") as HTMLInputElement | null;
    const ri = document.getElementById("wizRim") as HTMLInputElement | null;
    if (tw && tire) tw.value = String(tire.tire_width_mm);
    if (ta && tire) ta.value = String(tire.tire_aspect_pct);
    if (ri && tire) ri.value = String(tire.rim_in);
  }

  function bindWizardHandlers(): void {
    if (els.addCarBtn) els.addCarBtn.addEventListener("click", openWizard);
    if (els.wizardCloseBtn) els.wizardCloseBtn.addEventListener("click", closeWizard);
    if (els.wizardBackBtn) {
      els.wizardBackBtn.addEventListener("click", () => {
        if (wizState.step > 0) {
          wizState.step -= 1;
          loadWizardStep();
        }
      });
    }
    document.getElementById("wizardCustomBrandBtn")?.addEventListener("click", () => {
      const input = document.getElementById("wizardCustomBrand") as HTMLInputElement | null;
      const val = input?.value?.trim();
      if (!val) return;
      wizState.brand = val;
      wizState.step = 1;
      loadWizardStep();
    });
    document.getElementById("wizardCustomTypeBtn")?.addEventListener("click", () => {
      const input = document.getElementById("wizardCustomType") as HTMLInputElement | null;
      const val = input?.value?.trim();
      if (!val) return;
      wizState.carType = val;
      wizState.step = 2;
      loadWizardStep();
    });
    document.getElementById("wizardCustomModelBtn")?.addEventListener("click", () => {
      const input = document.getElementById("wizardCustomModel") as HTMLInputElement | null;
      const val = input?.value?.trim();
      if (!val) return;
      wizState.model = val;
      wizState.selectedModel = null;
      wizState.step = 3;
      loadWizardStep();
    });
    document.getElementById("wizardManualAddBtn")?.addEventListener("click", async () => {
      const tw = Number((document.getElementById("wizTireWidth") as HTMLInputElement | null)?.value);
      const ta = Number((document.getElementById("wizTireAspect") as HTMLInputElement | null)?.value);
      const ri = Number((document.getElementById("wizRim") as HTMLInputElement | null)?.value);
      const fd = Number((document.getElementById("wizFinalDrive") as HTMLInputElement | null)?.value);
      const gr = Number((document.getElementById("wizGearRatio") as HTMLInputElement | null)?.value);
      if (!(tw > 0 && ta > 0 && ri > 0 && fd > 0 && gr > 0)) return;
      const name = buildWizardCarName(wizState.brand, wizState.model);
      await ctx.addCarFromWizard(name, wizState.carType || "Custom", {
        tire_width_mm: tw,
        tire_aspect_pct: ta,
        rim_in: ri,
        final_drive_ratio: fd,
        current_gear_ratio: gr,
      });
      closeWizard();
    });
  }

  return { bindWizardHandlers };
}
