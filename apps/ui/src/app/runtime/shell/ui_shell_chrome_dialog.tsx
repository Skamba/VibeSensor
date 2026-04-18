import { useRef } from "preact/hooks";

import {
  useComputed,
  useSignalEffect,
  useSignalProperties,
  type ReadonlySignal,
} from "../../ui_signals";
import {
  SHELL_DIALOG_MODEL_KEYS,
  type UiShellChromeActions,
  type UiShellChromeDialogModel,
} from "./ui_shell_chrome_shared";

export function AppErrorBanner(props: {
  dialogModel: ReadonlySignal<UiShellChromeDialogModel>;
}) {
  const { appErrorBanner } = useSignalProperties(props.dialogModel, SHELL_DIALOG_MODEL_KEYS);
  const appErrorHidden = useComputed(() => appErrorBanner.value.hidden);
  const appErrorVariant = useComputed(() => appErrorBanner.value.variant ?? undefined);
  const appErrorText = useComputed(() => appErrorBanner.value.text);

  return (
    <div
      id="appErrorBanner"
      class="connection-banner app-error-banner"
      hidden={appErrorHidden}
      data-variant={appErrorVariant}
      aria-live="assertive"
      role="alert"
    >
      {appErrorText}
    </div>
  );
}

export function ConfirmationDialogLayer(props: {
  actions: ReadonlySignal<UiShellChromeActions>;
  dialogModel: ReadonlySignal<UiShellChromeDialogModel>;
}) {
  const { actions, dialogModel } = props;
  const confirmationDialog = dialogModel.value.confirmationDialog;
  return confirmationDialog
    ? <ConfirmationDialog actions={actions} model={confirmationDialog} />
    : null;
}

function ConfirmationDialog(props: {
  actions: ReadonlySignal<UiShellChromeActions>;
  model: NonNullable<UiShellChromeDialogModel["confirmationDialog"]>;
}) {
  const { actions, model } = props;
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null);

  useSignalEffect(() => {
    if (model.messageText) {
      confirmButtonRef.current?.focus();
    }
  });

  return (
    <div class="app-modal-layer">
      <div
        class="app-modal-backdrop"
        aria-hidden="true"
        onClick={() => actions.value.cancelConfirmation()}
      />
      <div
        class="panel card confirmation-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirmationDialogTitle"
        aria-describedby="confirmationDialogMessage"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            actions.value.cancelConfirmation();
          }
        }}
      >
        <div class="confirmation-dialog__body">
          <strong id="confirmationDialogTitle" class="confirmation-dialog__title">
            {model.titleText}
          </strong>
          <p id="confirmationDialogMessage" class="confirmation-dialog__message">
            {model.messageText}
          </p>
        </div>
        <div class="confirmation-dialog__actions">
          <button
            type="button"
            class="btn"
            onClick={() => actions.value.cancelConfirmation()}
          >
            {model.cancelButtonText}
          </button>
          <button
            type="button"
            class="btn btn--danger"
            onClick={() => actions.value.confirmConfirmation()}
            ref={confirmButtonRef}
          >
            {model.confirmButtonText}
          </button>
        </div>
      </div>
    </div>
  );
}
