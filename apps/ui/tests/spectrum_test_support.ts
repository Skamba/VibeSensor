type ElementState = {
  parent: ElementStub | null;
  children: ElementStub[];
  attributes: Record<string, string>;
  styles: Record<string, string>;
  listeners: Record<string, Array<() => void>>;
};

export type ElementStub = HTMLElement & {
  children: ElementStub[];
  className: string;
  textContent: string;
  hidden: boolean;
  disabled: boolean;
  title: string;
  type: string;
  style: CSSStyleDeclaration;
  append(...children: ElementStub[]): void;
  appendChild(child: ElementStub): ElementStub;
  insertBefore(child: ElementStub, before: ElementStub | null): ElementStub;
  remove(): void;
  addEventListener(type: string, handler: () => void): void;
  click(): void;
  getAttribute(name: string): string | null;
  setAttribute(name: string, value: string): void;
  innerHTML: string;
};

const childState = new WeakMap<ElementStub, ElementState>();

export function createElementStub(tagName = "div"): ElementStub {
  const state: ElementState = {
    parent: null,
    children: [],
    attributes: {},
    styles: {},
    listeners: {},
  };
  const element = {
    className: "",
    textContent: "",
    hidden: false,
    disabled: false,
    title: "",
    type: "",
    style: {
      setProperty(name: string, value: string): void {
        state.styles[name] = value;
      },
      getPropertyValue(name: string): string {
        return state.styles[name] ?? "";
      },
    } as unknown as CSSStyleDeclaration,
    get children(): ElementStub[] {
      return state.children;
    },
    append(this: ElementStub, ...children: ElementStub[]): void {
      for (const child of children) {
        this.insertBefore(child, null);
      }
    },
    appendChild(this: ElementStub, child: ElementStub): ElementStub {
      return this.insertBefore(child, null);
    },
    insertBefore(child: ElementStub, before: ElementStub | null): ElementStub {
      child.remove();
      const childRecord = childState.get(child);
      if (!childRecord) {
        throw new Error("child stub is not registered");
      }
      childRecord.parent = element;
      const index = before ? state.children.indexOf(before) : -1;
      if (index >= 0) {
        state.children.splice(index, 0, child);
      } else {
        state.children.push(child);
      }
      return child;
    },
    remove(): void {
      if (!state.parent) {
        return;
      }
      const parentRecord = childState.get(state.parent);
      if (!parentRecord) {
        state.parent = null;
        return;
      }
      const siblings = parentRecord.children;
      const index = siblings.indexOf(element);
      if (index >= 0) {
        siblings.splice(index, 1);
      }
      state.parent = null;
    },
    addEventListener(type: string, handler: () => void): void {
      state.listeners[type] ??= [];
      state.listeners[type].push(handler);
    },
    click(): void {
      for (const handler of state.listeners.click ?? []) {
        handler();
      }
    },
    getAttribute(name: string): string | null {
      return state.attributes[name] ?? null;
    },
    setAttribute(name: string, value: string): void {
      state.attributes[name] = value;
    },
    get innerHTML(): string {
      return "";
    },
    set innerHTML(value: string) {
      if (value !== "") {
        throw new Error("ElementStub only supports clearing innerHTML");
      }
      for (const child of [...state.children]) {
        child.remove();
      }
    },
  } as unknown as ElementStub;
  childState.set(element, state);
  void tagName;
  return element;
}

export function installDocumentStub(): () => void {
  const originalDocument = globalThis.document;
  const originalGetComputedStyle = globalThis.getComputedStyle;
  const originalDevicePixelRatio = (globalThis as { devicePixelRatio?: number })
    .devicePixelRatio;
  const originalMatchMedia = globalThis.matchMedia;
  const originalAddEventListener = globalThis.addEventListener;
  const originalRemoveEventListener = globalThis.removeEventListener;
  const originalDispatchEvent = globalThis.dispatchEvent;
  (globalThis as { document?: Document }).document = {
    documentElement: {} as HTMLElement,
    createElement(tagName: string) {
      return createElementStub(tagName);
    },
  } as Document;
  (globalThis as { devicePixelRatio?: number }).devicePixelRatio = 1;
  globalThis.matchMedia = ((query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }) as MediaQueryList) as typeof matchMedia;
  globalThis.addEventListener = (() => undefined) as typeof addEventListener;
  globalThis.removeEventListener = (() =>
    undefined) as typeof removeEventListener;
  globalThis.dispatchEvent = (() => false) as typeof dispatchEvent;
  globalThis.getComputedStyle = (() =>
    ({
      getPropertyValue: () => "",
    }) as unknown as CSSStyleDeclaration) as typeof getComputedStyle;
  return () => {
    (globalThis as { document?: Document }).document = originalDocument;
    (globalThis as { devicePixelRatio?: number }).devicePixelRatio =
      originalDevicePixelRatio;
    globalThis.matchMedia = originalMatchMedia;
    globalThis.addEventListener = originalAddEventListener;
    globalThis.removeEventListener = originalRemoveEventListener;
    globalThis.dispatchEvent = originalDispatchEvent;
    globalThis.getComputedStyle = originalGetComputedStyle;
  };
}
