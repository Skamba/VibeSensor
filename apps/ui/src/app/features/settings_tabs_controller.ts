import type { UiDomElements } from "../ui_dom_registry";

function setActiveSettingsTab(els: UiDomElements, tabId: string): void {
  els.settingsTabs.forEach((tab) => {
    const isActive = tab.getAttribute("data-settings-tab") === tabId;
    tab.classList.toggle("active", isActive);
    tab.setAttribute("aria-selected", isActive ? "true" : "false");
    tab.tabIndex = isActive ? 0 : -1;
  });
  els.settingsTabPanels.forEach((panel) => {
    const isActive = panel.id === tabId;
    panel.classList.toggle("active", isActive);
    panel.hidden = !isActive;
  });
}

function activateSettingsTabButton(els: UiDomElements, tab: HTMLElement): void {
  const tabId = tab.getAttribute("data-settings-tab");
  if (tabId) setActiveSettingsTab(els, tabId);
}

export function bindSettingsTabs(els: UiDomElements): void {
  const activateTabByIndex = (index: number): void => {
    if (!els.settingsTabs.length) return;
    const safeIndex = ((index % els.settingsTabs.length) + els.settingsTabs.length) % els.settingsTabs.length;
    const button = els.settingsTabs[safeIndex];
    activateSettingsTabButton(els, button);
    button.focus();
  };
  els.settingsTabs.forEach((tab, idx) => {
    tab.addEventListener("click", () => {
      activateSettingsTabButton(els, tab);
    });
    tab.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        tab.click();
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        activateTabByIndex(idx + 1);
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        activateTabByIndex(idx - 1);
        return;
      }
      if (event.key === "Home") {
        event.preventDefault();
        activateTabByIndex(0);
        return;
      }
      if (event.key === "End") {
        event.preventDefault();
        activateTabByIndex(els.settingsTabs.length - 1);
      }
    });
  });
}
