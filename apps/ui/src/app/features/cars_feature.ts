import type { FeatureDepsBase } from "../feature_deps_base";
import {
  getCarLibraryBrands,
  getCarLibraryModels,
  getCarLibraryTypes,
} from "../../api";
import type {
  CarLibraryModel,
  CarLibraryVariant,
} from "../../api";
import type { UiCarsDom } from "../dom/cars_dom";
import {
  renderWizardBrandOptions,
  renderWizardGearboxOptions,
  renderWizardMessage,
  renderWizardModelOptions,
  renderWizardSummary,
  renderWizardTireOptions,
  renderWizardTypeOptions,
  renderWizardVariantOptions,
  syncCarWizardStepState,
  type WizardSummaryData,
  writeCarWizardTireInputs,
} from "../views/car_wizard_view";
import {
  buildWizardCarName,
  buildWizardSummaryData,
  canFinishWizard,
  createInitialWizardState,
  getResolvedWizardSpecBranch,
  getWizardActionHint,
  readWizardManualGearboxValues,
  readWizardManualTireValues,
  resetWizardState,
  resolveGearboxes,
  resolveTireOptions,
  type WizardState,
} from "./cars_wizard_state";

export interface CarsFeatureDeps extends FeatureDepsBase {
  dom: UiCarsDom;
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

const WIZARD_STEP_LABEL_KEYS = [
  "settings.car.step_brand_short",
  "settings.car.step_type_short",
  "settings.car.step_model_short",
  "settings.car.step_variant_short",
  "settings.car.step_specs_short",
] as const;

export function createCarsFeature(ctx: CarsFeatureDeps): CarsFeature {
  const { dom: els, escapeHtml, fmt, t } = ctx;
  const wizState: WizardState = createInitialWizardState();
  let handlersBound = false;
  let lastWizardFocusTarget: HTMLElement | null = null;

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

  function focusWizardElement(target: HTMLElement | null): void {
    target?.focus();
  }

  function focusFirstWizardOption(
    container: ParentNode | null,
    fallback: HTMLElement | null,
  ): void {
    const firstOption = container?.querySelector<HTMLButtonElement>(".wiz-opt");
    focusWizardElement(firstOption ?? fallback);
  }

  function readManualTireValues(): {
    width: number;
    aspect: number;
    rim: number;
  } | null {
    return readWizardManualTireValues(wizState.step, {
      width: els.wizTireWidthInput?.value,
      aspect: els.wizTireAspectInput?.value,
      rim: els.wizRimInput?.value,
    });
  }

  function readManualGearboxValues(): {
    finalDrive: number;
    topGear: number;
  } | null {
    return readWizardManualGearboxValues(wizState.step, {
      finalDrive: els.wizFinalDriveInput?.value,
      topGear: els.wizGearRatioInput?.value,
    });
  }

  function currentManualWizardValues(): {
    manualTire: ReturnType<typeof readManualTireValues>;
    manualGearbox: ReturnType<typeof readManualGearboxValues>;
  } {
    return {
      manualTire: readManualTireValues(),
      manualGearbox: readManualGearboxValues(),
    };
  }

  function setWizardVisibility(isOpen: boolean): void {
    if (els.wizardBackdrop) {
      els.wizardBackdrop.hidden = !isOpen;
    }
    if (els.addCarWizard) {
      els.addCarWizard.hidden = !isOpen;
      if (isOpen) {
        els.addCarWizard.scrollTop = 0;
      }
    }
    document.body.classList.toggle("wizard-open", isOpen);
  }

  function syncWizardFinishAction(): void {
    const { manualGearbox, manualTire } = currentManualWizardValues();
    const actionButton = els.wizardManualAddBtn;
    if (els.addCarWizard) {
      if (wizState.step === 4) {
        els.addCarWizard.dataset.specBranch = getResolvedWizardSpecBranch(wizState) ?? "pending";
      } else {
        delete els.addCarWizard.dataset.specBranch;
      }
    }
    if (els.wizardActionHint) {
      els.wizardActionHint.textContent = wizState.step === 4
        ? getWizardActionHint(wizState, { manualGearbox, manualTire, fmt, t })
        : "";
    }
    if (!actionButton) {
      return;
    }
    actionButton.hidden = wizState.step !== 4;
    actionButton.disabled = wizState.step !== 4 || !canFinishWizard(wizState, manualTire, manualGearbox);
  }

  function refreshWizardChrome(): void {
    const { manualGearbox, manualTire } = currentManualWizardValues();
    syncCarWizardStepState(els, wizState.step);
    if (els.wizardProgressText) {
      els.wizardProgressText.textContent = t("settings.car.wizard_progress", {
        current: wizState.step + 1,
        total: WIZARD_STEP_LABEL_KEYS.length,
        step: t(WIZARD_STEP_LABEL_KEYS[wizState.step] ?? WIZARD_STEP_LABEL_KEYS[0]),
      });
    }
    if (els.wizardSummaryPanel) {
      const summaryData: WizardSummaryData = buildWizardSummaryData(wizState, {
        manualGearbox,
        manualTire,
        fmt,
        t,
      });
      els.wizardSummaryPanel.innerHTML = renderWizardSummary(summaryData, {
        t,
        escapeHtml,
      });
    }
    syncWizardFinishAction();
  }

  function openWizard(): void {
    lastWizardFocusTarget = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : els.addCarBtn;
    resetWizardState(wizState);
    setWizardVisibility(true);
    refreshWizardChrome();
    focusWizardElement(els.wizardCloseBtn);
    loadWizardStep();
  }

  function closeWizard(): void {
    setWizardVisibility(false);
    const focusTarget = lastWizardFocusTarget && document.contains(lastWizardFocusTarget)
      ? lastWizardFocusTarget
      : els.addCarBtn;
    lastWizardFocusTarget = null;
    focusWizardElement(focusTarget);
  }

  function loadWizardStep(): void {
    refreshWizardChrome();
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
      focusFirstWizardOption(container, els.wizardCustomBrandInput);
    } catch {
      container.innerHTML = renderWizardMessage(t("settings.wizard.load_failed_brands"), escapeHtml);
      focusWizardElement(els.wizardCustomBrandInput);
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
      focusFirstWizardOption(container, els.wizardCustomTypeInput);
    } catch {
      container.innerHTML = renderWizardMessage(t("settings.wizard.load_failed_types"), escapeHtml);
      focusWizardElement(els.wizardCustomTypeInput);
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
        wizState.selectedGearbox = null;
        wizState.selectedTire = null;
        wizState.specBranch = null;
        wizState.step = 3;
        loadWizardStep();
      });
      focusFirstWizardOption(container, els.wizardCustomModelInput);
    } catch {
      container.innerHTML = renderWizardMessage(t("settings.wizard.load_failed_models"), escapeHtml);
      focusWizardElement(els.wizardCustomModelInput);
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
      wizState.selectedGearbox = null;
      wizState.selectedTire = null;
      wizState.specBranch = null;
      wizState.step = 4;
      loadWizardStep();
    });
    focusFirstWizardOption(container, null);
  }

  function loadGearboxStep(): void {
    const tireContainer = els.wizardTireList;
    if (tireContainer) {
      const tireOptions = resolveTireOptions(wizState.selectedModel, wizState.selectedVariant);
      if (tireOptions.length > 0) {
        const selectedTire = wizState.selectedTire && tireOptions.includes(wizState.selectedTire)
          ? wizState.selectedTire
          : tireOptions[0];
        const selectedTireIndex = Math.max(0, tireOptions.indexOf(selectedTire));
        tireContainer.innerHTML = renderWizardTireOptions(
          tireOptions,
          escapeHtml,
          selectedTireIndex,
        );
        wizState.selectedTire = selectedTire;
        writeCarWizardTireInputs(els, selectedTire);
        bindWizardOptionButtons(tireContainer, (button) => {
          const idx = Number(button.dataset.tireIdx);
          wizState.selectedTire = tireOptions[idx] || selectedTire;
          writeCarWizardTireInputs(els, wizState.selectedTire);
          tireContainer.querySelectorAll(".wiz-opt").forEach((candidate) => {
            candidate.classList.remove("selected");
          });
          button.classList.add("selected");
          refreshWizardChrome();
        });
        refreshWizardChrome();
      } else {
        wizState.selectedTire = null;
        tireContainer.innerHTML = "";
        wizState.specBranch = "manual";
      }
    }

    const container = els.wizardGearboxList;
    if (!container) return;
    const gearboxes = resolveGearboxes(wizState.selectedModel, wizState.selectedVariant);
    if (!gearboxes.length) {
      wizState.selectedGearbox = null;
      wizState.specBranch = "manual";
      container.innerHTML = renderWizardMessage(t("settings.wizard.no_gearboxes"), escapeHtml);
      refreshWizardChrome();
      focusWizardElement(els.wizTireWidthInput);
      return;
    }
    container.innerHTML = renderWizardGearboxOptions(gearboxes, {
      escapeHtml,
      fmt: ctx.fmt,
    }, wizState.selectedGearbox ? gearboxes.indexOf(wizState.selectedGearbox) : -1);
    bindWizardOptionButtons(container, (button) => {
      const idx = Number(button.dataset.idx);
      const gearbox = gearboxes[idx];
      if (!gearbox) return;
      wizState.selectedGearbox = gearbox;
      wizState.specBranch = "library";
      container.querySelectorAll(".wiz-opt").forEach((candidate) => {
        candidate.classList.remove("selected");
      });
      button.classList.add("selected");
      refreshWizardChrome();
      focusWizardElement(els.wizardManualAddBtn);
    });
    focusWizardElement(
      tireContainer?.querySelector<HTMLButtonElement>(".wiz-opt")
      ?? container.querySelector<HTMLButtonElement>(".wiz-opt")
      ?? els.wizTireWidthInput,
    );
  }

  function bindWizardHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    if (els.addCarBtn) els.addCarBtn.addEventListener("click", openWizard);
    if (els.wizardCloseBtn) els.wizardCloseBtn.addEventListener("click", closeWizard);
    if (els.wizardBackdrop) {
      els.wizardBackdrop.addEventListener("click", closeWizard);
    }
    if (els.wizardBackBtn) {
      els.wizardBackBtn.addEventListener("click", () => {
        if (wizState.step > 0) {
          wizState.step -= 1;
          if (
            wizState.step === 3
            && !(wizState.selectedModel?.variants?.length)
          ) {
            wizState.step = 2;
          }
          loadWizardStep();
        }
      });
    }
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && els.addCarWizard && !els.addCarWizard.hidden) {
        event.preventDefault();
        closeWizard();
      }
    });
    els.wizardCustomBrandBtn?.addEventListener("click", () => {
      const value = els.wizardCustomBrandInput?.value?.trim();
      if (!value) {
        els.wizardCustomBrandInput?.focus();
        return;
      }
      wizState.brand = value;
      wizState.step = 1;
      loadWizardStep();
    });
    els.wizardCustomTypeBtn?.addEventListener("click", () => {
      const value = els.wizardCustomTypeInput?.value?.trim();
      if (!value) {
        els.wizardCustomTypeInput?.focus();
        return;
      }
      wizState.carType = value;
      wizState.step = 2;
      loadWizardStep();
    });
    els.wizardCustomModelBtn?.addEventListener("click", () => {
      const value = els.wizardCustomModelInput?.value?.trim();
      if (!value) {
        els.wizardCustomModelInput?.focus();
        return;
      }
      wizState.model = value;
      wizState.selectedModel = null;
      wizState.selectedVariant = null;
      wizState.selectedGearbox = null;
      wizState.selectedTire = null;
      wizState.specBranch = "manual";
      wizState.step = 4;
      loadWizardStep();
    });

    async function finishWizardWithLibrarySpecs(): Promise<void> {
      const tire = wizState.selectedTire;
      const gearbox = wizState.selectedGearbox;
      if (!tire) {
        focusWizardElement(els.wizardTireList?.querySelector<HTMLButtonElement>(".wiz-opt") ?? null);
        return;
      }
      if (!gearbox) {
        focusWizardElement(els.wizardGearboxList?.querySelector<HTMLButtonElement>(".wiz-opt") ?? null);
        return;
      }
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
          tire_width_mm: tire.tire_width_mm,
          tire_aspect_pct: tire.tire_aspect_pct,
          rim_in: tire.rim_in,
          final_drive_ratio: gearbox.final_drive_ratio,
          current_gear_ratio: gearbox.top_gear_ratio,
        },
        variantName,
      );
      closeWizard();
    }

    async function finishWizardWithManualSpecs(): Promise<void> {
      const tw = Number(els.wizTireWidthInput?.value);
      const ta = Number(els.wizTireAspectInput?.value);
      const ri = Number(els.wizRimInput?.value);
      const fd = Number(els.wizFinalDriveInput?.value);
      const gr = Number(els.wizGearRatioInput?.value);
      if (!(tw > 0)) {
        els.wizTireWidthInput?.focus();
        return;
      }
      if (!(ta > 0)) {
        els.wizTireAspectInput?.focus();
        return;
      }
      if (!(ri > 0)) {
        els.wizRimInput?.focus();
        return;
      }
      if (!(fd > 0)) {
        els.wizFinalDriveInput?.focus();
        return;
      }
      if (!(gr > 0)) {
        els.wizGearRatioInput?.focus();
        return;
      }
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
    }

    els.wizardManualAddBtn?.addEventListener("click", async () => {
      if (getResolvedWizardSpecBranch(wizState) === "library") {
        await finishWizardWithLibrarySpecs();
        return;
      }
      await finishWizardWithManualSpecs();
    });
    [
      els.wizTireWidthInput,
      els.wizTireAspectInput,
      els.wizRimInput,
      els.wizFinalDriveInput,
      els.wizGearRatioInput,
    ].forEach((input) => {
      input?.addEventListener("input", () => {
        if (!els.addCarWizard?.hidden && wizState.step === 4) {
          wizState.specBranch = "manual";
          refreshWizardChrome();
        }
      });
    });
  }

  return { bindWizardHandlers };
}
