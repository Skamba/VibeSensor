export type RenderChild =
  | Node
  | string
  | number
  | false
  | null
  | undefined
  | readonly RenderChild[];

export interface RenderElementOptions {
  className?: string;
  classes?: readonly (string | false | null | undefined)[];
  attrs?: Record<string, string | number | boolean | null | undefined>;
  data?: Record<string, string | number | boolean | null | undefined>;
  text?: string | number | null | undefined;
  children?: readonly RenderChild[];
}

function camelToKebab(value: string): string {
  return value.replace(/[A-Z]/g, (char) => `-${char.toLowerCase()}`);
}

function appendRenderChild(parent: Node, child: RenderChild): void {
  if (child === null || child === undefined || child === false) {
    return;
  }
  if (Array.isArray(child)) {
    for (const nested of child) {
      appendRenderChild(parent, nested);
    }
    return;
  }
  if (child instanceof Node) {
    parent.appendChild(child);
    return;
  }
  parent.appendChild(document.createTextNode(String(child)));
}

export function createFragment(...children: readonly RenderChild[]): DocumentFragment {
  const fragment = document.createDocumentFragment();
  for (const child of children) {
    appendRenderChild(fragment, child);
  }
  return fragment;
}

export function createElementNode<K extends keyof HTMLElementTagNameMap>(
  tagName: K,
  options: RenderElementOptions = {},
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tagName);
  if (options.className) {
    element.className = options.className;
  }
  if (options.classes) {
    const classTokens = options.classes.filter((token): token is string => Boolean(token));
    if (classTokens.length) {
      element.classList.add(...classTokens);
    }
  }
  for (const [name, value] of Object.entries(options.attrs ?? {})) {
    if (value === null || value === undefined || value === false) {
      continue;
    }
    element.setAttribute(name, value === true ? "" : String(value));
  }
  for (const [name, value] of Object.entries(options.data ?? {})) {
    if (value === null || value === undefined || value === false) {
      continue;
    }
    element.setAttribute(`data-${camelToKebab(name)}`, value === true ? "" : String(value));
  }
  if (options.text !== null && options.text !== undefined) {
    element.textContent = String(options.text);
  }
  if (options.children) {
    for (const child of options.children) {
      appendRenderChild(element, child);
    }
  }
  return element;
}

export function renderChildren(
  container: ParentNode & Node,
  ...children: readonly RenderChild[]
): void {
  container.replaceChildren(createFragment(...children));
}

export function setClassStates(
  element: Element,
  states: Record<string, boolean>,
): void {
  for (const [className, enabled] of Object.entries(states)) {
    element.classList.toggle(className, enabled);
  }
}

export function setNodeText(
  node: Node,
  value: string | number | null | undefined,
): void {
  node.textContent = value === null || value === undefined ? "" : String(value);
}
