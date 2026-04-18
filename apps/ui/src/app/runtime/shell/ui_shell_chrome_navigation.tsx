import { type JSX } from "preact";
import { useRef } from "preact/hooks";

import {
  handleTabListKeyboardNavigation,
  normalizeTabListIndex,
} from "../../dom/tab_list_keyboard_navigation";
import {
  useComputed,
  useSignalProperties,
  type ReadonlySignal,
} from "../../ui_signals";
import {
  SHELL_NAVIGATION_MODEL_KEYS,
  type UiShellChromeActions,
  type UiShellChromeNavItemModel,
  type UiShellChromeNavigationModel,
} from "./ui_shell_chrome_shared";

export function ShellNavigation(props: {
  actions: ReadonlySignal<UiShellChromeActions>;
  navigationModel: ReadonlySignal<UiShellChromeNavigationModel>;
}) {
  const { actions, navigationModel } = props;
  const { activeViewId, navItems } = useSignalProperties(
    navigationModel,
    SHELL_NAVIGATION_MODEL_KEYS,
  );
  const menuButtonRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function activateView(viewId: string): void {
    actions.value.activateView(viewId);
  }

  function focusMenuButton(nextIndex: number): void {
    menuButtonRefs.current[normalizeTabListIndex(nextIndex, navItems.value.length)]?.focus();
  }

  function handleMenuKeyDown(
    index: number,
    event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  ): void {
    handleTabListKeyboardNavigation({
      count: navItems.value.length,
      event,
      focusTabAt: focusMenuButton,
      getTabIdAt: (nextIndex) => navItems.value[nextIndex].viewId,
      index,
      onActivateTab: activateView,
    });
  }

  return (
    <div class="site-header__nav">
      <h1 class="title" aria-label="VibeSensor">
        <picture class="brandmark">
          <source
            srcSet="/branding/vibesensor-logo-header-dark.svg"
            media="(prefers-color-scheme: dark)"
          />
          <img
            src="/branding/vibesensor-logo-header-light.svg"
            alt="VibeSensor"
            width="222"
            height="46"
          />
        </picture>
      </h1>
      <nav class="menu" aria-label="Primary" role="tablist">
        {navItems.value.map((item, index) => (
          <ShellNavigationTabButton
            key={item.viewId}
            activeViewId={activeViewId}
            index={index}
            item={item}
            onActivateView={activateView}
            onKeyDown={handleMenuKeyDown}
            onRef={(element) => {
              menuButtonRefs.current[index] = element;
            }}
          />
        ))}
      </nav>
    </div>
  );
}

function ShellNavigationTabButton(props: {
  activeViewId: ReadonlySignal<string>;
  index: number;
  item: UiShellChromeNavItemModel;
  onActivateView(viewId: string): void;
  onKeyDown(index: number, event: JSX.TargetedKeyboardEvent<HTMLButtonElement>): void;
  onRef(element: HTMLButtonElement | null): void;
}) {
  const { index, item, onActivateView } = props;
  const isActive = useComputed(() => item.viewId === props.activeViewId.value);
  const ariaSelected = useComputed(() => isActive.value ? "true" : "false");
  const tabIndex = useComputed(() => isActive.value ? 0 : -1);

  return (
    <button
      ref={props.onRef}
      type="button"
      class="menu-btn"
      data-view={item.viewId}
      id={item.tabId}
      role="tab"
      aria-controls={item.viewId}
      aria-selected={ariaSelected}
      tabIndex={tabIndex}
      onClick={() => onActivateView(item.viewId)}
      onKeyDown={(event) => props.onKeyDown(index, event)}
    >
      <span>{item.labelText}</span>
    </button>
  );
}
