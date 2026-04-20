import { expect, test } from "vitest";
import { mountUiApp } from "../src/app/ui_app_mount";
import type { AppState } from "../src/app/ui_app_state";
import type { UiAppRuntime } from "../src/app/ui_app_runtime";

function createHostStub() {
  const attributes = new Map<string, string>();
  return {
    getAttribute(name: string) {
      return attributes.get(name) ?? null;
    },
    removeAttribute(name: string) {
      attributes.delete(name);
    },
    setAttribute(name: string, value: string) {
      attributes.set(name, value);
    },
  } as unknown as HTMLElement;
}

test("startUiApp returns a disposable mounted app handle", () => {
  const host = createHostStub();
  const originalDocument = globalThis.document;
  let runtimeCreations = 0;
  const renderCalls: Array<{ host: Element | DocumentFragment; vnode: unknown }> = [];
  let startCalls = 0;
  let disposeCalls = 0;

  (globalThis as { document?: Document }).document = {
    getElementById(id: string) {
      return id === "appShellChromeRoot" ? host : null;
    },
  } as unknown as Document;

  try {
    const fakeRuntimeFactory = (): UiAppRuntime => {
      runtimeCreations += 1;
      return {
        attachSettingsPanels() {},
        dispose() {
          disposeCalls += 1;
        },
        panels: {} as UiAppRuntime["panels"],
        shellChrome: {} as UiAppRuntime["shellChrome"],
        spectrumPanel: {} as UiAppRuntime["spectrumPanel"],
        start() {
          startCalls += 1;
        },
      };
    };

    const app = mountUiApp({
      createRuntime: () => fakeRuntimeFactory(),
      createState: () => ({}) as AppState,
      renderRoot: () => null,
      renderApp: ((vnode: unknown, target: Element | DocumentFragment) => {
        renderCalls.push({ host: target, vnode });
      }) as typeof import("preact").render,
    });

    const second = mountUiApp({
      createRuntime: () => fakeRuntimeFactory(),
      createState: () => ({}) as AppState,
      renderRoot: () => null,
      renderApp: ((vnode: unknown, target: Element | DocumentFragment) => {
        renderCalls.push({ host: target, vnode });
      }) as typeof import("preact").render,
    });

    expect(second).toBe(app);
    expect(runtimeCreations).toBe(1);
    expect(startCalls).toBe(1);
    expect(host.getAttribute("data-ui-app-mounted")).toBe("true");
    expect(renderCalls).toHaveLength(1);

    app.dispose();

    expect(disposeCalls).toBe(1);
    expect(host.getAttribute("data-ui-app-mounted")).toBeNull();
    expect(renderCalls).toHaveLength(2);
    expect(renderCalls[1]).toEqual({ host, vnode: null });
  } finally {
    (globalThis as { document?: Document }).document = originalDocument;
  }
});
