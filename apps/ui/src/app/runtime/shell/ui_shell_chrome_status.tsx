import type { ComponentChildren } from "preact";

import {
  useSignalProperties,
  type ReadonlySignal,
} from "../../ui_signals";
import {
  SHELL_ACTIVE_VIEW_KEY,
  SHELL_STATUS_MODEL_KEYS,
  type UiShellBadgeModel,
  type UiShellChromeNavigationModel,
  type UiShellChromeStatusModel,
} from "./ui_shell_chrome_shared";

export function ShellChromeFrame(props: {
  children: ComponentChildren;
  statusModel: ReadonlySignal<UiShellChromeStatusModel>;
}) {
  const { children, statusModel } = props;
  const connectionState = statusModel.value.connectionState;

  return (
    <div class="wrap" data-connection-state={connectionState}>
      {children}
    </div>
  );
}

export function ShellStatus(props: {
  navigationModel: ReadonlySignal<UiShellChromeNavigationModel>;
  statusModel: ReadonlySignal<UiShellChromeStatusModel>;
}) {
  const { navigationModel, statusModel } = props;
  const { activeViewId } = useSignalProperties(navigationModel, SHELL_ACTIVE_VIEW_KEY);
  const { shellLiveStatus, wsLinkState } = useSignalProperties(statusModel, SHELL_STATUS_MODEL_KEYS);
  const statusHidden = activeViewId.value === "dashboardView";

  return (
    <div class="site-header__status" hidden={statusHidden}>
      <div class="site-header__status-pills">
        <ShellStatusPill id="linkState" model={wsLinkState} />
        <ShellStatusPill id="shellLiveStatus" model={shellLiveStatus} />
      </div>
    </div>
  );
}

function ShellStatusPill(props: {
  id: string;
  model: ReadonlySignal<UiShellBadgeModel>;
}) {
  const model = props.model.value;

  return (
    <div
      id={props.id}
      class="pill"
      data-variant={model.variant}
      aria-live="polite"
    >
      {model.text}
    </div>
  );
}
