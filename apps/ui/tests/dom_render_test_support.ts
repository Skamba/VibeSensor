import { parseHTML } from "linkedom";

import { flushSignalUpdates } from "./async_test_helpers";

export type MountedSignalView<TView> = {
  cleanup(): void;
  flush(rounds?: number): Promise<void>;
  host: HTMLElement;
  view: TView;
};

type MountedViewGlobals = {
  CustomEvent?: typeof CustomEvent;
  DocumentFragment?: typeof DocumentFragment;
  Element?: typeof Element;
  Event?: typeof Event;
  HTMLElement?: typeof HTMLElement;
  HTMLButtonElement?: typeof HTMLButtonElement;
  HTMLInputElement?: typeof HTMLInputElement;
  KeyboardEvent?: typeof KeyboardEvent;
  MouseEvent?: typeof MouseEvent;
  Node?: typeof Node;
  cancelAnimationFrame?: typeof cancelAnimationFrame;
  document?: Document;
  getComputedStyle?: typeof getComputedStyle;
  requestAnimationFrame?: typeof requestAnimationFrame;
  window?: Window & typeof globalThis;
};

export async function mountSignalView<TView>(
  loadMount: () => Promise<(host: HTMLElement) => TView> | ((host: HTMLElement) => TView),
): Promise<MountedSignalView<TView>>;
export async function mountSignalView<TView>(
  loadMount: () =>
    Promise<(host: HTMLElement, view: TView) => void> | ((host: HTMLElement, view: TView) => void),
  createView: () => TView,
): Promise<MountedSignalView<TView>>;
export async function mountSignalView<TView>(
  loadMount: () =>
    | Promise<((host: HTMLElement) => TView) | ((host: HTMLElement, view: TView) => void)>
    | ((host: HTMLElement) => TView)
    | ((host: HTMLElement, view: TView) => void),
  createView?: () => TView,
): Promise<MountedSignalView<TView>> {
  const restoreDom = installMountedDomGlobals();
  const host = globalThis.document.createElement("div");
  globalThis.document.body.appendChild(host);
  let cleanedUp = false;

  try {
    const { render } = await import("preact");
    const mount = await loadMount();
    const view = createView ? createView() : undefined;
    const mountedView = createView
      ? (mount as (host: HTMLElement, view: TView) => void)(host, view)
      : (mount as (host: HTMLElement) => TView)(host);
    return {
      cleanup(): void {
        if (cleanedUp) {
          return;
        }
        cleanedUp = true;
        render(null, host);
        host.remove();
        restoreDom();
      },
      flush(rounds = 12): Promise<void> {
        return flushSignalUpdates(rounds);
      },
      host,
      view: createView ? view : mountedView,
    };
  } catch (error) {
    host.remove();
    restoreDom();
    throw error;
  }
}

export function installMountedDomGlobals(): () => void {
  const { window } = parseHTML("<!doctype html><html><body></body></html>");
  const globalRef = globalThis as typeof globalThis & MountedViewGlobals;
  const requestAnimationFrameShim = ((callback: FrameRequestCallback) =>
    setTimeout(() => callback(Date.now()), 0) as unknown as number) as typeof requestAnimationFrame;
  const cancelAnimationFrameShim = ((handle: number) => {
    clearTimeout(handle);
  }) as typeof cancelAnimationFrame;
  const original: MountedViewGlobals = {
    CustomEvent: globalRef.CustomEvent,
    DocumentFragment: globalRef.DocumentFragment,
    Element: globalRef.Element,
    Event: globalRef.Event,
    HTMLElement: globalRef.HTMLElement,
    HTMLButtonElement: globalRef.HTMLButtonElement,
    HTMLInputElement: globalRef.HTMLInputElement,
    KeyboardEvent: globalRef.KeyboardEvent,
    MouseEvent: globalRef.MouseEvent,
    Node: globalRef.Node,
    cancelAnimationFrame: globalRef.cancelAnimationFrame,
    document: globalRef.document,
    getComputedStyle: globalRef.getComputedStyle,
    requestAnimationFrame: globalRef.requestAnimationFrame,
    window: globalRef.window,
  };

  globalRef.window = window as Window & typeof globalThis;
  globalRef.document = window.document as unknown as Document;
  globalRef.Node = window.Node as unknown as typeof Node;
  globalRef.Element = window.Element as unknown as typeof Element;
  globalRef.HTMLElement = window.HTMLElement as unknown as typeof HTMLElement;
  globalRef.HTMLButtonElement = window.HTMLButtonElement as unknown as typeof HTMLButtonElement;
  globalRef.HTMLInputElement = window.HTMLInputElement as unknown as typeof HTMLInputElement;
  globalRef.DocumentFragment = window.DocumentFragment as unknown as typeof DocumentFragment;
  globalRef.Event = window.Event as unknown as typeof Event;
  globalRef.CustomEvent = window.CustomEvent as unknown as typeof CustomEvent;
  globalRef.KeyboardEvent = window.KeyboardEvent as unknown as typeof KeyboardEvent;
  globalRef.MouseEvent = window.MouseEvent as unknown as typeof MouseEvent;
  globalRef.getComputedStyle = (window.getComputedStyle
    ? window.getComputedStyle.bind(window)
    : (() =>
      ({
        getPropertyValue: () => "",
      }) as CSSStyleDeclaration)) as typeof getComputedStyle;
  globalRef.requestAnimationFrame = requestAnimationFrameShim;
  globalRef.cancelAnimationFrame = cancelAnimationFrameShim;

  return () => {
    restoreMountedViewGlobal(globalRef, "window", original.window);
    restoreMountedViewGlobal(globalRef, "document", original.document);
    restoreMountedViewGlobal(globalRef, "Node", original.Node);
    restoreMountedViewGlobal(globalRef, "Element", original.Element);
    restoreMountedViewGlobal(globalRef, "HTMLElement", original.HTMLElement);
    restoreMountedViewGlobal(globalRef, "HTMLButtonElement", original.HTMLButtonElement);
    restoreMountedViewGlobal(globalRef, "HTMLInputElement", original.HTMLInputElement);
    restoreMountedViewGlobal(globalRef, "DocumentFragment", original.DocumentFragment);
    restoreMountedViewGlobal(globalRef, "Event", original.Event);
    restoreMountedViewGlobal(globalRef, "CustomEvent", original.CustomEvent);
    restoreMountedViewGlobal(globalRef, "KeyboardEvent", original.KeyboardEvent);
    restoreMountedViewGlobal(globalRef, "MouseEvent", original.MouseEvent);
    restoreMountedViewGlobal(globalRef, "getComputedStyle", original.getComputedStyle);
    restoreMountedViewGlobal(
      globalRef,
      "requestAnimationFrame",
      original.requestAnimationFrame ?? requestAnimationFrameShim,
    );
    restoreMountedViewGlobal(
      globalRef,
      "cancelAnimationFrame",
      original.cancelAnimationFrame ?? cancelAnimationFrameShim,
    );
  };
}

function restoreMountedViewGlobal<K extends keyof MountedViewGlobals>(
  globalRef: typeof globalThis & MountedViewGlobals,
  key: K,
  value: MountedViewGlobals[K],
): void {
  if (value) {
    globalRef[key] = value;
    return;
  }
  delete globalRef[key];
}
