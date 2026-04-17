import { parseHTML } from "linkedom";

import { flushSignalUpdates } from "./async_test_helpers";

type DomGlobals = {
  Node?: typeof Node;
  Element?: typeof Element;
  HTMLElement?: typeof HTMLElement;
  DocumentFragment?: typeof DocumentFragment;
  document?: Document;
};

export class FakeNode {
  parentNode: FakeNode | null = null;
  childNodes: FakeNode[] = [];

  get firstChild(): FakeNode | null {
    return this.childNodes[0] ?? null;
  }

  get nextSibling(): FakeNode | null {
    if (!this.parentNode) {
      return null;
    }
    const siblings = this.parentNode.childNodes;
    const index = siblings.indexOf(this);
    return index >= 0 ? siblings[index + 1] ?? null : null;
  }

  get nodeType(): number {
    return 0;
  }

  appendChild<T extends FakeNode>(child: T): T {
    return this.insertBefore(child, null);
  }

  insertBefore<T extends FakeNode>(child: T, before: FakeNode | null): T {
    if (child instanceof FakeDocumentFragment) {
      const fragmentChildren = [...child.childNodes];
      child.childNodes = [];
      for (const fragmentChild of fragmentChildren) {
        this.insertBefore(fragmentChild, before);
      }
      return child;
    }
    child.remove();
    child.parentNode = this;
    const index = before ? this.childNodes.indexOf(before) : -1;
    if (index >= 0) {
      this.childNodes.splice(index, 0, child);
    } else {
      this.childNodes.push(child);
    }
    return child;
  }

  replaceChildren(...children: Array<FakeNode | string>): void {
    this.childNodes = [];
    for (const child of children) {
      if (typeof child === "string") {
        this.appendChild(new FakeText(child));
        continue;
      }
      this.appendChild(child);
    }
  }

  removeChild<T extends FakeNode>(child: T): T {
    const index = this.childNodes.indexOf(child);
    if (index >= 0) {
      this.childNodes.splice(index, 1);
      child.parentNode = null;
    }
    return child;
  }

  remove(): void {
    this.parentNode?.removeChild(this);
  }

  get textContent(): string {
    return this.childNodes.map((child) => child.textContent).join("");
  }

  set textContent(value: string | null) {
    this.childNodes = [];
    if (value) {
      this.appendChild(new FakeText(value));
    }
  }
}

class FakeText extends FakeNode {
  constructor(private value: string) {
    super();
  }

  get data(): string {
    return this.value;
  }

  set data(value: string) {
    this.value = value;
  }

  override get nodeType(): number {
    return 3;
  }

  override get textContent(): string {
    return this.value;
  }

  override set textContent(value: string | null) {
    this.value = value ?? "";
  }
}

export class FakeDocumentFragment extends FakeNode {
  override get nodeType(): number {
    return 11;
  }
}

function escapeHtml(value: string): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function dataAttributeToDatasetKey(name: string): string {
  return name
    .slice(5)
    .split("-")
    .filter(Boolean)
    .map((part, index) => (index === 0 ? part : `${part[0]?.toUpperCase() ?? ""}${part.slice(1)}`))
    .join("");
}

function serializeNode(node: FakeNode): string {
  if (node instanceof FakeText) {
    return node.textContent;
  }
  if (node instanceof FakeDocumentFragment) {
    return node.childNodes.map((child) => serializeNode(child)).join("");
  }
  if (node instanceof FakeElement) {
    return node.toOuterHtml();
  }
  return node.textContent;
}

class FakeClassList {
  readonly #tokens = new Set<string>();

  add(...tokens: string[]): void {
    for (const token of tokens) {
      this.#tokens.add(token);
    }
  }

  remove(...tokens: string[]): void {
    for (const token of tokens) {
      this.#tokens.delete(token);
    }
  }

  toggle(token: string, force?: boolean): boolean {
    const next = force ?? !this.#tokens.has(token);
    if (next) {
      this.#tokens.add(token);
    } else {
      this.#tokens.delete(token);
    }
    return next;
  }

  contains(token: string): boolean {
    return this.#tokens.has(token);
  }

  toString(): string {
    return Array.from(this.#tokens).join(" ");
  }

  setFromString(value: string): void {
    this.#tokens.clear();
    for (const token of value.split(/\s+/).filter(Boolean)) {
      this.#tokens.add(token);
    }
  }
}

export class FakeElement extends FakeNode {
  readonly classList = new FakeClassList();
  readonly dataset: Record<string, string> = {};
  readonly #attributes = new Map<string, string>();
  readonly #listeners = new Map<string, Set<EventListenerOrEventListenerObject>>();
  readonly #styleValues = new Map<string, string>();
  #rawInnerHTML: string | null = null;

  hidden = false;
  scrollTop = 0;
  scrollHeight = 0;
  readonly namespaceURI = "http://www.w3.org/1999/xhtml";
  readonly style = {
    cssText: "",
    getPropertyValue: (name: string): string => this.#styleValues.get(name) ?? "",
    removeProperty: (name: string): string => {
      const currentValue = this.#styleValues.get(name) ?? "";
      this.#styleValues.delete(name);
      this.#syncStyleCssText();
      return currentValue;
    },
    setProperty: (name: string, value: string): void => {
      this.#styleValues.set(name, value);
      this.#syncStyleCssText();
    },
  } as unknown as CSSStyleDeclaration;

  constructor(readonly tagName: string) {
    super();
  }

  #syncStyleCssText(): void {
    this.style.cssText = Array.from(this.#styleValues.entries())
      .map(([name, value]) => `${name}: ${value};`)
      .join(" ");
  }

  get attributes(): Array<{ name: string; value: string }> {
    return Array.from(this.#attributes.entries(), ([name, value]) => ({ name, value }));
  }

  get className(): string {
    return this.classList.toString();
  }

  set className(value: string) {
    this.classList.setFromString(value);
  }

  get localName(): string {
    return this.tagName.toLowerCase();
  }

  override get nodeType(): number {
    return 1;
  }

  get ownerDocument(): Document | undefined {
    return globalThis.document;
  }

  get innerHTML(): string {
    return this.#rawInnerHTML ?? this.childNodes.map((child) => serializeNode(child)).join("");
  }

  set innerHTML(value: string) {
    this.#rawInnerHTML = value;
    super.textContent = value;
  }

  override appendChild<T extends FakeNode>(child: T): T {
    this.#rawInnerHTML = null;
    return super.appendChild(child);
  }

  override insertBefore<T extends FakeNode>(child: T, before: FakeNode | null): T {
    this.#rawInnerHTML = null;
    return super.insertBefore(child, before);
  }

  override replaceChildren(...children: Array<FakeNode | string>): void {
    this.#rawInnerHTML = null;
    super.replaceChildren(...children);
  }

  override removeChild<T extends FakeNode>(child: T): T {
    this.#rawInnerHTML = null;
    return super.removeChild(child);
  }

  override get textContent(): string {
    return super.textContent;
  }

  override set textContent(value: string | null) {
    this.#rawInnerHTML = null;
    super.textContent = value;
  }

  setAttribute(name: string, value: string): void {
    this.#attributes.set(name, value);
    if (name.startsWith("data-")) {
      this.dataset[dataAttributeToDatasetKey(name)] = value;
    }
  }

  getAttribute(name: string): string | null {
    return this.#attributes.get(name) ?? null;
  }

  removeAttribute(name: string): void {
    this.#attributes.delete(name);
    if (name.startsWith("data-")) {
      delete this.dataset[dataAttributeToDatasetKey(name)];
    }
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    let listeners = this.#listeners.get(type);
    if (!listeners) {
      listeners = new Set<EventListenerOrEventListenerObject>();
      this.#listeners.set(type, listeners);
    }
    listeners.add(listener);
  }

  removeEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    this.#listeners.get(type)?.delete(listener);
  }

  dispatchEvent(event: Event): boolean {
    const listeners = Array.from(this.#listeners.get(event.type) ?? []);
    for (const listener of listeners) {
      if (typeof listener === "function") {
        listener.call(this, event);
      } else {
        listener.handleEvent(event);
      }
    }
    return !event.defaultPrevented;
  }

  focus(): void {}

  toOuterHtml(): string {
    const attrs: string[] = [];
    if (this.className) {
      attrs.push(`class="${escapeHtml(this.className)}"`);
    }
    for (const [name, value] of this.#attributes) {
      attrs.push(`${name}="${escapeHtml(value)}"`);
    }
    const attrsHtml = attrs.length > 0 ? ` ${attrs.join(" ")}` : "";
    return `<${this.tagName.toLowerCase()}${attrsHtml}>${this.childNodes.map((child) => serializeNode(child)).join("")}</${this.tagName.toLowerCase()}>`;
  }
}

export class FakeHTMLElement extends FakeElement {}

class FakeDocument {
  readonly body = new FakeHTMLElement("BODY") as unknown as HTMLElement;
  readonly documentElement = new FakeHTMLElement("HTML") as unknown as HTMLElement;

  createElement(tagName: string): FakeHTMLElement {
    return new FakeHTMLElement(tagName.toUpperCase());
  }

  createElementNS(_namespaceURI: string, tagName: string): FakeHTMLElement {
    return this.createElement(tagName);
  }

  createTextNode(value: string): FakeText {
    return new FakeText(value);
  }

  createDocumentFragment(): FakeDocumentFragment {
    return new FakeDocumentFragment();
  }
}

export function installFakeDomGlobals(): () => void {
  const globalRef = globalThis as typeof globalThis & DomGlobals;
  const original: DomGlobals = {
    Node: globalRef.Node,
    Element: globalRef.Element,
    HTMLElement: globalRef.HTMLElement,
    DocumentFragment: globalRef.DocumentFragment,
    document: globalRef.document,
  };
  globalRef.Node = FakeNode as unknown as typeof Node;
  globalRef.Element = FakeElement as unknown as typeof Element;
  globalRef.HTMLElement = FakeHTMLElement as unknown as typeof HTMLElement;
  globalRef.DocumentFragment = FakeDocumentFragment as unknown as typeof DocumentFragment;
  globalRef.document = new FakeDocument() as unknown as Document;
  return () => {
    restoreGlobal(globalRef, "Node", original.Node);
    restoreGlobal(globalRef, "Element", original.Element);
    restoreGlobal(globalRef, "HTMLElement", original.HTMLElement);
    restoreGlobal(globalRef, "DocumentFragment", original.DocumentFragment);
    restoreGlobal(globalRef, "document", original.document);
  };
}

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

function restoreGlobal<K extends keyof DomGlobals>(
  globalRef: typeof globalThis & DomGlobals,
  key: K,
  value: DomGlobals[K],
): void {
  if (value) {
    globalRef[key] = value;
    return;
  }
  delete globalRef[key];
}

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
  const restoreDom = installMountedViewDomGlobals();
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
        restoreDom();
      },
      flush(rounds = 12): Promise<void> {
        return flushSignalUpdates(rounds);
      },
      host,
      view: createView ? view : mountedView,
    };
  } catch (error) {
    restoreDom();
    throw error;
  }
}

// Legacy escape hatch for bridge-style feature fixtures. New signal-backed
// island tests should prefer mountSignalView().
export function createPanel(): HTMLElement {
  return new FakeHTMLElement("DIV") as unknown as HTMLElement;
}

function installMountedViewDomGlobals(): () => void {
  const { window } = parseHTML("<!doctype html><html><body></body></html>");
  const globalRef = globalThis as typeof globalThis & MountedViewGlobals;
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
  globalRef.requestAnimationFrame = ((callback: FrameRequestCallback) =>
    setTimeout(() => callback(Date.now()), 16) as unknown as number) as typeof requestAnimationFrame;
  globalRef.cancelAnimationFrame = ((handle: number) => {
    clearTimeout(handle);
  }) as typeof cancelAnimationFrame;

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
    restoreMountedViewGlobal(globalRef, "requestAnimationFrame", original.requestAnimationFrame);
    restoreMountedViewGlobal(globalRef, "cancelAnimationFrame", original.cancelAnimationFrame);
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

export function elementChildren(node: FakeNode): FakeElement[] {
  return node.childNodes.filter((child): child is FakeElement => child instanceof FakeElement);
}

export function findByClass(node: FakeNode, className: string): FakeElement[] {
  const matches: FakeElement[] = [];
  for (const child of node.childNodes) {
    if (child instanceof FakeElement) {
      if (child.classList.contains(className)) {
        matches.push(child);
      }
      matches.push(...findByClass(child, className));
    }
  }
  return matches;
}

export function findByAttribute(
  node: FakeNode,
  attributeName: string,
  expectedValue?: string,
): FakeElement[] {
  const matches: FakeElement[] = [];
  for (const child of node.childNodes) {
    if (child instanceof FakeElement) {
      const actualValue = child.getAttribute(attributeName);
      if (
        actualValue !== null
        && (expectedValue === undefined || actualValue === expectedValue)
      ) {
        matches.push(child);
      }
      matches.push(...findByAttribute(child, attributeName, expectedValue));
    }
  }
  return matches;
}
