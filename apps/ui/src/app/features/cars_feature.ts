import type { FeatureDepsBase } from "../feature_deps_base";
import {
  getCarLibraryBrands,
  getCarLibraryModels,
  getCarLibraryTypes,
} from "../../api";
import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarLibraryVariant,
} from "../../api";
import {
  renderWizardBrandOptions,
  renderWizardGearboxOptions,
  renderWizardMessage,
  renderWizardModelOptions,
  renderWizardTireOptions,
  renderWizardTypeOptions,
  renderWizardVariantOptions,
  syncCarWizardStepState,
  writeCarWizardTireInputs,
} from "../views/car_wizard_view";

export interface CarsFeatureDeps extends FeatureDepsBase {
  fmt: (n: number, digits?: number) => string;
  addCarFromWizard: (
    name: string,
    carType: string,
    aspects: Record<string, number>,
    variant?: string,
  ) => Promise<void>;
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
  selectedVariant: CarLibraryVariant | null;
  selectedGearbox: CarLibraryGearbox | null;
  selectedTire: CarLibraryTireOption | null;
}

/** Resolve effective gearboxes for the selected variant (or base model fallback). */
function resolveGearboxes(
  model: CarLibraryModel | null,
  variant: CarLibraryVariant | null,
): CarLibraryGearbox[] {
  if (variant?.gearboxes && variant.gearboxes.length > 0) return variant.gearboxes;
  return model?.gearboxes || [];
}

/** Resolve effective tire options for the selected variant (or base model fallback). */
function resolveTireOptions(
  model: CarLibraryModel | null,
  variant: CarLibraryVariant | null,
): CarLibraryTireOption[] {
  if (variant?.tire_options && variant.tire_options.length > 0) return variant.tire_options;
  return model?.tire_options || [];
}

export function createCarsFeature(ctx: CarsFeatureDeps): CarsFeature {
  const { els, escapeHtml, t } = ctx;
  const wizState: WizardState = {
    step: 0,
    brand: "",
    carType: "",
    model: "",
    selectedModel: null,
    selectedVariant: null,
    selectedGearbox: null,
    selectedTire: null,
  };

  function bindWizardOptionButtons(
    container: HTMLElement,
    onSelect: (button: HTMLButtonElement) => void,
  ): void {
    container.querySelectorAll<HTMLButtonElement>(".wiz-opt").forEach((button) => {
      button.addEventListener("click", () => {
        onSelect(button);
      });
    });
  }

  function resetWizardState(): void {
    wizState.step = 0;
    wizState.brand = "";
    wizState.carType = "";
    wizState.model = "";
    wizState.selectedModel = null;
    wizState.selectedVariant = null;
    wizState.selectedGearbox = null;
    wizState.selectedTire = null;
  }

  function openWizard(): void {
    resetWizardState();
    if (els.addCarWizard) els.addCarWizard.hidden = false;
    loadWizardStep();
  }

  function closeWizard(): void {
    if (els.addCarWizard) els.addCarWizard.hidden = true;
  }

  function buildWizardCarName(
    brand: string,
    model: string,
    variant: CarLibraryVariant | null,
  ): string {
    const variantSuffix = variant ? ` ${variant.name}` : "";
    if (brand) return `${brand} ${model || "Custom"}${variantSuffix}`;
    return (model || "Custom Car") + variantSuffix;
  }

  function loadWizardStep(): void {
    syncCarWizardStepState(els, wizState.step);
    if (wizState.step === 0) void loadBrandStep();
    else if (wizState.step === 1) void loadTypeStep();
    else if (wizState.step === 2) void loadModelStep();
    else if (wizState.step === 3) loadVariantStep();
    else if (wizState.step === 4) loadGearboxStep();
  }

  async function loadBrandStep(): Promise<void> {
    const container = els.wizardBrandList;
    if (!container) return;
    container.innerHTML = renderWizardMessage(t("settings.wizard.loading"), escapeHtml);
    try {
      const data = await getCarLibraryBrands();
      container.innerHTML = renderWizardBrandOptions(data.brands || [], escapeHtml);
      bindWizardOptionButtons(container, (button) => {
        const value = button.dataset.value || "";
        if (!value) return;
        wizState.brand = value;
        wizState.step = 1;
        loadWizardStep();
      });
    } catch {
      container.innerHTML = renderWizardMessage(t("settings.wizard.load_failed_brands"), escapeHtml);
    }
  }

  async function loadTypeStep(): Promise<void> {
    const container = els.wizardTypeList;
    if (!container) return;
    container.innerHTML = renderWizardMessage(t("settings.wizard.loading"), escapeHtml);
    try {
      const data = await getCarLibraryTypes(wizState.brand);
      container.innerHTML = renderWizardTypeOptions(data.types || [], escapeHtml);
      bindWizardOptionButtons(container, (button) => {
        const value = button.dataset.value || "";
        if (!value) return;
        wizState.carType = value;
        wizState.step = 2;
        loadWizardStep();
      });
    } catch {
      container.innerHTML = renderWizardMessage(t("settings.wizard.load_failed_types"), escapeHtml);
    }
  }

  async function loadModelStep(): Promise<void> {
    const container = els.wizardModelList;
    if (!container) return;
    container.innerHTML = renderWizardMessage(t("settings.wizard.loading"), escapeHtml);
    try {
      const data = await getCarLibraryModels(wizState.brand, wizState.carType);
      const models: CarLibraryModel[] = data.models || [];
      container.innerHTML = renderWizardModelOptions(models, escapeHtml);
      bindWizardOptionButtons(container, (button) => {
        const idx = Number(button.dataset.idx);
        wizState.selectedModel = models[idx] || null;
        wizState.model = wizState.selectedModel?.model || "";
        wizState.selectedVariant = null;
        wizState.selectedTire = null;
        wizState.step = 3;
        loadWizardStep();
      });
    } catch {
      container.innerHTML = renderWizardMessage(t("settings.wizard.load_failed_models"), escapeHtml);
    }
  }

  function loadVariantStep(): void {
    const container = els.wizardVariantList;
    if (!container) return;
    const variants: CarLibraryVariant[] = wizState.selectedModel?.variants || [];
    if (!variants.length) {
      wizState.step = 4;
      loadWizardStep();
      return;
    }
    container.innerHTML = renderWizardVariantOptions(variants, escapeHtml);
    bindWizardOptionButtons(container, (button) => {
      const idx = Number(button.dataset.idx);
      wizState.selectedVariant = variants[idx] || null;
      wizState.selectedTire = null;
      wizState.step = 4;
      loadWizardStep();
    });
  }

  function loadGearboxStep(): void {
    const tireContainer = els.wizardTireList;
    if (tireContainer) {
      const tireOptions = resolveTireOptions(wizState.selectedModel, wizState.selectedVariant);
      if (tireOptions.length > 0) {
        tireContainer.innerHTML = renderWizardTireOptions(tireOptions, escapeHtml);
        const defaultTire = tireOptions[0];
        wizState.selectedTire = defaultTire;
        writeCarWizardTireInputs(els, defaultTire);
        bindWizardOptionButtons(tireContainer, (button) => {
          const idx = Number(button.dataset.tireIdx);
          wizState.selectedTire = tireOptions[idx] || defaultTire;
          writeCarWizardTireInputs(els, wizState.selectedTire);
          tireContainer.querySelectorAll(".wiz-opt").forEach((candidate) => {
            candidate.classList.remove("selected");
          });
          button.classList.add("selected");
        });
      } else {
        tireContainer.innerHTML = "";
      }
    }

    const container = els.wizardGearboxList;
    if (!container) return;
    const gearboxes = resolveGearboxes(wizState.selectedModel, wizState.selectedVariant);
    if (!gearboxes.length) {
      container.innerHTML = renderWizardMessage(t("settings.wizard.no_gearboxes"), escapeHtml);
      return;
    }
    container.innerHTML = renderWizardGearboxOptions(gearboxes, {
      escapeHtml,
      fmt: ctx.fmt,
    });
    bindWizardOptionButtons(container, (button) => {
      void (async () => {
        const idx = Number(button.dataset.idx);
        const gearbox = gearboxes[idx];
        if (!gearbox) return;
        const tire = wizState.selectedTire || wizState.selectedModel;
        if (!tire) return;
        wizState.selectedGearbox = gearbox;
        const carName = buildWizardCarName(
          wizState.brand,
          wizState.model,
          wizState.selectedVariant,
        );
        const variantName = wizState.selectedVariant?.name;
        await ctx.addCarFromWizard(
          carName,
          wizState.carType,
          {
            tire_width_mm: tire.tire_width_mm,
            tire_aspect_pct: tire.tire_aspect_pct,
            rim_in: tire.rim_in,
            final_drive_ratio: gearbox.final_drive_ratio,
            current_gear_ratio: gearbox.top_gear_ratio,
          },
          variantName,
        );
        closeWizard();
      })();
    });
  }

  function bindWizardHandlers(): void {
    if (els.addCarBtn) els.addCarBtn.addEventListener("click", openWizard);
    if (els.wizardCloseBtn) els.wizardCloseBtn.addEventListener("click", closeWizard);
    if (els.wizardBackBtn) {
      els.wizardBackBtn.addEventListener("click", () => {
        if (wizState.step > 0) {
          wizState.step -= 1;
          if (
            wizState.step === 3
            && (!wizState.selectedModel || !(wizState.selectedModel.variants?.length))
          ) {
            wizState.step = 2;
          }
          loadWizardStep();
        }
      });
    }
    els.wizardCustomBrandBtn?.addEventListener("click", () => {
      const value = els.wizardCustomBrandInput?.value?.trim();
      if (!value) return;
      wizState.brand = value;
      wizState.step = 1;
      loadWizardStep();
    });
    els.wizardCustomTypeBtn?.addEventListener("click", () => {
      const value = els.wizardCustomTypeInput?.value?.trim();
      if (!value) return;
      wizState.carType = value;
      wizState.step = 2;
      loadWizardStep();
    });
    els.wizardCustomModelBtn?.addEventListener("click", () => {
      const value = els.wizardCustomModelInput?.value?.trim();
      if (!value) return;
      wizState.model = value;
      wizState.selectedModel = null;
      wizState.selectedVariant = null;
      wizState.step = 4;
      loadWizardStep();
    });
    els.wizardManualAddBtn?.addEventListener("click", async () => {
      const tw = Number(els.wizTireWidthInput?.value);
      const ta = Number(els.wizTireAspectInput?.value);
      const ri = Number(els.wizRimInput?.value);
      const fd = Number(els.wizFinalDriveInput?.value);
      const gr = Number(els.wizGearRatioInput?.value);
      if (!(tw > 0 && ta > 0 && ri > 0 && fd > 0 && gr > 0)) return;
      const name = buildWizardCarName(
        wizState.brand,
        wizState.model,
        wizState.selectedVariant,
      );
      const variantName = wizState.selectedVariant?.name;
      await ctx.addCarFromWizard(
        name,
        wizState.carType || "Custom",
        {
          tire_width_mm: tw,
          tire_aspect_pct: ta,
          rim_in: ri,
          final_drive_ratio: fd,
          current_gear_ratio: gr,
        },
        variantName,
      );
      closeWizard();
    });
  }

  return { bindWizardHandlers };
}
