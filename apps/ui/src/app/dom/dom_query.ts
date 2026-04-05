function missingElement(owner: string, target: string): never {
  throw new Error(`${owner} requires ${target}`);
}

export function getById<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

export function requiredById<T extends HTMLElement>(id: string, owner: string): T {
  return getById<T>(id) ?? missingElement(owner, `#${id}`);
}

export function queryOne<T extends Element>(selector: string): T | null {
  return document.querySelector<T>(selector);
}

export function queryRequired<T extends Element>(selector: string, owner: string): T {
  return queryOne<T>(selector) ?? missingElement(owner, selector);
}

export function queryAll<T extends Element>(selector: string): T[] {
  return Array.from(document.querySelectorAll<T>(selector));
}

export function queryRequiredAll<T extends Element>(selector: string, owner: string): T[] {
  const elements = queryAll<T>(selector);
  return elements.length ? elements : missingElement(owner, selector);
}
