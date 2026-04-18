import type { ComponentChildren } from "preact";

import {
  type Signal,
  type ReadonlySignal,
} from "../ui_signals";
import {
  createDeferredModelSignal,
  useDeferredModel,
} from "../views/view_model_binding";
import { AppErrorBanner, ConfirmationDialogLayer } from "./shell/ui_shell_chrome_dialog";
import { ShellNavigation } from "./shell/ui_shell_chrome_navigation";
import { ShellPreferences } from "./shell/ui_shell_chrome_preferences";
import {
  DEFAULT_DIALOG_MODEL,
  DEFAULT_NAVIGATION_MODEL,
  DEFAULT_PREFERENCES_MODEL,
  DEFAULT_STATUS_MODEL,
  SHELL_CHROME_HOST_ID,
  SHELL_OWNER,
  type UiShellChromeActions,
  type UiShellChromeDialogModel,
  type UiShellChromeNavigationModel,
  type UiShellChromePreferencesModel,
  type UiShellChromeStatusModel,
  type UiShellChromeView,
} from "./shell/ui_shell_chrome_shared";
import { ShellChromeFrame, ShellStatus } from "./shell/ui_shell_chrome_status";

export {
  DEFAULT_UI_SHELL_CHROME_ACTIONS,
  SHELL_NAV_ITEMS,
  SPEED_UNIT_OPTIONS,
} from "./shell/ui_shell_chrome_shared";
export type {
  UiShellBadgeModel,
  UiShellChromeActions,
  UiShellChromeDialogModel,
  UiShellChromeNavigationModel,
  UiShellChromeNavItemModel,
  UiShellChromePreferencesModel,
  UiShellChromeStatusModel,
  UiShellChromeView,
  UiShellErrorBannerModel,
} from "./shell/ui_shell_chrome_shared";

type UiShellChromeProps = {
  actions: ReadonlySignal<UiShellChromeActions>;
  dialogModel: ReadonlySignal<ReadonlySignal<UiShellChromeDialogModel> | null>;
  navigationModel: ReadonlySignal<ReadonlySignal<UiShellChromeNavigationModel> | null>;
  preferencesModel: ReadonlySignal<ReadonlySignal<UiShellChromePreferencesModel> | null>;
  statusModel: ReadonlySignal<ReadonlySignal<UiShellChromeStatusModel> | null>;
  children?: ComponentChildren;
};

export interface UiShellChromeBindings {
  props: Omit<UiShellChromeProps, "children">;
  view: UiShellChromeView;
}

export function UiShellChrome(props: UiShellChromeProps) {
  const { actions } = props;
  const dialogModel = useDeferredModel(props.dialogModel, DEFAULT_DIALOG_MODEL);
  const navigationModel = useDeferredModel(props.navigationModel, DEFAULT_NAVIGATION_MODEL);
  const preferencesModel = useDeferredModel(props.preferencesModel, DEFAULT_PREFERENCES_MODEL);
  const statusModel = useDeferredModel(props.statusModel, DEFAULT_STATUS_MODEL);

  return (
    <ShellChromeFrame statusModel={statusModel}>
      <header class="site-header">
        <div class="site-header__main">
          <ShellNavigation actions={actions} navigationModel={navigationModel} />
          <ShellPreferences actions={actions} preferencesModel={preferencesModel} />
        </div>
        <ShellStatus navigationModel={navigationModel} statusModel={statusModel} />
      </header>

      <AppErrorBanner dialogModel={dialogModel} />
      {props.children}
      <ConfirmationDialogLayer actions={actions} dialogModel={dialogModel} />
    </ShellChromeFrame>
  );
}

export function getUiShellChromeHost(): HTMLElement {
  const host = globalThis.document?.getElementById(SHELL_CHROME_HOST_ID);
  if (host) {
    return host as HTMLElement;
  }
  throw new Error(`${SHELL_OWNER} requires #${SHELL_CHROME_HOST_ID}`);
}

export function createUiShellChromeBindings(
  actions: Signal<UiShellChromeActions>,
): UiShellChromeBindings {
  const dialogModel = createDeferredModelSignal<UiShellChromeDialogModel>();
  const navigationModel = createDeferredModelSignal<UiShellChromeNavigationModel>();
  const preferencesModel = createDeferredModelSignal<UiShellChromePreferencesModel>();
  const statusModel = createDeferredModelSignal<UiShellChromeStatusModel>();
  return {
    props: {
      actions,
      dialogModel,
      navigationModel,
      preferencesModel,
      statusModel,
    },
    view: {
      bindDialogModel(model) {
        dialogModel.value = model;
      },
      bindNavigationModel(model) {
        navigationModel.value = model;
      },
      bindPreferencesModel(model) {
        preferencesModel.value = model;
      },
      bindStatusModel(model) {
        statusModel.value = model;
      },
    },
  };
}
