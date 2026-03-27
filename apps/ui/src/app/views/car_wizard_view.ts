import type {
  CarLibraryGearbox,
  CarLibraryModel,
  CarLibraryTireOption,
  CarLibraryVariant,
} from "../../api/types";
import type { UiDomElements } from "../ui_dom_registry";

type EscapeHtml = (value: unknown) => string;
type FormatNumber = (value: number, digits?: number) => string;
type Translate = (key: string, vars?: Record<string, unknown>) => string;

interface WizardOptionSpec {
  dataAttribute: string;
  value: string;
  label: string;
  detail?: string;
  selected?: boolean;
}

export interface WizardSummaryData {
  profileName: string | null;
  brand: string | null;
  carType: string | null;
  model: string | null;
  variant: string | null;
  tire: string | null;
  gearbox: string | null;
}

function renderWizardOptions(
  options: WizardOptionSpec[],
  escapeHtml: EscapeHtml,
): string {
  return options
    .map((option) => {
      const detail = option.detail
        ? `<span class="wiz-opt-detail">${escapeHtml(option.detail)}</span>`
        : "";
      return `<button type="button" class="wiz-opt${option.selected ? " selected" : ""}" data-${option.dataAttribute}="${escapeHtml(option.value)}"><span>${escapeHtml(option.label)}</span>${detail}</button>`;
    })
    .join("");
}

export function renderWizardMessage(
  message: string,
  escapeHtml: EscapeHtml,
): string {
  return `<em>${escapeHtml(message)}</em>`;
}

export function renderWizardBrandOptions(
  brands: string[],
  escapeHtml: EscapeHtml,
): string {
  return renderWizardOptions(
    brands.map((brand) => ({
      dataAttribute: "value",
      value: brand,
      label: brand,
    })),
    escapeHtml,
  );
}

export function renderWizardTypeOptions(
  types: string[],
  escapeHtml: EscapeHtml,
): string {
  return renderWizardOptions(
    types.map((carType) => ({
      dataAttribute: "value",
      value: carType,
      label: carType,
    })),
    escapeHtml,
  );
}

export function renderWizardModelOptions(
  models: CarLibraryModel[],
  escapeHtml: EscapeHtml,
): string {
  return renderWizardOptions(
    models.map((model, index) => ({
      dataAttribute: "idx",
      value: String(index),
      label: model.model,
      detail: `${model.tire_width_mm}/${model.tire_aspect_pct}R${model.rim_in}`,
    })),
    escapeHtml,
  );
}

export function renderWizardVariantOptions(
  variants: CarLibraryVariant[],
  escapeHtml: EscapeHtml,
): string {
  return renderWizardOptions(
    variants.map((variant, index) => ({
      dataAttribute: "idx",
      value: String(index),
      label: variant.name,
      detail: [variant.drivetrain, variant.engine].filter(Boolean).join(" · "),
    })),
    escapeHtml,
  );
}

export function renderWizardTireOptions(
  tireOptions: CarLibraryTireOption[],
  escapeHtml: EscapeHtml,
): string {
  return renderWizardOptions(
    tireOptions.map((tireOption, index) => ({
      dataAttribute: "tire-idx",
      value: String(index),
      label: tireOption.name,
      detail: `${tireOption.tire_width_mm}/${tireOption.tire_aspect_pct}R${tireOption.rim_in}`,
      selected: index === 0,
    })),
    escapeHtml,
  );
}

export function renderWizardGearboxOptions(
  gearboxes: CarLibraryGearbox[],
  deps: { escapeHtml: EscapeHtml; fmt: FormatNumber },
): string {
  const { escapeHtml, fmt } = deps;
  return renderWizardOptions(
    gearboxes.map((gearbox, index) => ({
      dataAttribute: "idx",
      value: String(index),
      label: gearbox.name,
      detail: `FD: ${fmt(gearbox.final_drive_ratio, 2)} · Top Gear: ${fmt(gearbox.top_gear_ratio, 2)}`,
    })),
    escapeHtml,
  );
}

export function renderWizardSummary(
  summary: WizardSummaryData,
  deps: { t: Translate; escapeHtml: EscapeHtml },
): string {
  const { t, escapeHtml } = deps;
  const pending = t("settings.car.wizard_summary_pending");
  const rows: Array<[string, string | null]> = [
    [t("settings.car.wizard_summary_brand"), summary.brand],
    [t("settings.car.wizard_summary_type"), summary.carType],
    [t("settings.car.wizard_summary_model"), summary.model],
    [t("settings.car.wizard_summary_variant"), summary.variant],
    [t("settings.car.wizard_summary_tire"), summary.tire],
    [t("settings.car.wizard_summary_gearbox"), summary.gearbox],
  ];
  return `
    <div class="wizard-summary-preview">
      <div class="wizard-summary-preview__label">${escapeHtml(t("settings.car.wizard_summary_name"))}</div>
      <div class="wizard-summary-preview__value">${escapeHtml(summary.profileName || pending)}</div>
    </div>
    <dl class="wizard-summary-list">
      ${rows.map(([label, value]) => `
        <div class="wizard-summary-item">
          <dt>${escapeHtml(label)}</dt>
          <dd>${escapeHtml(value || pending)}</dd>
        </div>
      `).join("")}
    </dl>
  `;
}

export function syncCarWizardStepState(
  els: Pick<UiDomElements, "wizardSteps" | "wizardStepDots" | "wizardBackBtn">,
  step: number,
): void {
  els.wizardSteps.forEach((stepEl, index) => {
    if (!stepEl) return;
    stepEl.classList.toggle("active", index === step);
  });
  els.wizardStepDots.forEach((dot) => {
    const dotStep = Number(dot.getAttribute("data-step"));
    dot.classList.toggle("active", dotStep === step);
    dot.classList.toggle("done", dotStep < step);
    if (dotStep === step) {
      dot.setAttribute("aria-current", "step");
    } else {
      dot.removeAttribute("aria-current");
    }
  });
  if (els.wizardBackBtn) {
    els.wizardBackBtn.style.display = step > 0 ? "" : "none";
  }
}

export function writeCarWizardTireInputs(
  els: Pick<UiDomElements, "wizTireWidthInput" | "wizTireAspectInput" | "wizRimInput">,
  tire: CarLibraryTireOption,
): void {
  if (els.wizTireWidthInput) els.wizTireWidthInput.value = String(tire.tire_width_mm);
  if (els.wizTireAspectInput) els.wizTireAspectInput.value = String(tire.tire_aspect_pct);
  if (els.wizRimInput) els.wizRimInput.value = String(tire.rim_in);
}
