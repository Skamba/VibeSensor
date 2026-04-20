import { expect, test } from "vitest";
import { createUiConfirmationModule } from "../src/app/runtime/ui_confirmation_module";

test("ui confirmation module queues requests and resolves them from dialog actions", async () => {
  const module = createUiConfirmationModule({
    t: (key) => {
      switch (key) {
        case "actions.cancel":
          return "Cancel";
        case "actions.confirm":
          return "Confirm";
        case "actions.confirm_title":
          return "Please confirm";
        default:
          return key;
      }
    },
  });

  const firstRequest = module.requestConfirmation("Delete run-42?");
  const secondRequest = module.requestConfirmation("Delete all runs?");

  expect(module.dialogModel.value).toMatchObject({
    titleText: "Please confirm",
    messageText: "Delete run-42?",
    confirmButtonText: "Confirm",
    cancelButtonText: "Cancel",
  });

  module.confirm();
  expect(await firstRequest).toBe(true);
  expect(module.dialogModel.value?.messageText).toBe("Delete all runs?");

  module.cancel();
  expect(await secondRequest).toBe(false);
  expect(module.dialogModel.value).toBeNull();
});
