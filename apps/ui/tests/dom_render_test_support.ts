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

  appendChild<T extends FakeNode>(child: T): T {
    if (child instanceof FakeDocumentFragment) {
      const fragmentChildren = [...child.childNodes];
      child.childNodes = [];
      for (const fragmentChild of fragmentChildren) {
        this.appendChild(fragmentChild);
      }
      return child;
    }
    child.parentNode = this;
    this.childNodes.push(child);
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

  override get textContent(): string {
    return this.value;
  }

  override set textContent(value: string | null) {
    this.value = value ?? "";
  }
}

export class FakeDocumentFragment extends FakeNode {}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
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
  #rawInnerHTML: string | null = null;

  hidden = false;
  scrollTop = 0;
  scrollHeight = 0;

  constructor(readonly tagName: string) {
    super();
  }

  get className(): string {
    return this.classList.toString();
  }

  set className(value: string) {
    this.classList.setFromString(value);
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

  override replaceChildren(...children: Array<FakeNode | string>): void {
    this.#rawInnerHTML = null;
    super.replaceChildren(...children);
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
  }

  getAttribute(name: string): string | null {
    return this.#attributes.get(name) ?? null;
  }

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
  createElement(tagName: string): FakeHTMLElement {
    return new FakeHTMLElement(tagName.toUpperCase());
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

export function createPanel(): HTMLElement {
  return new FakeHTMLElement("DIV") as unknown as HTMLElement;
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
