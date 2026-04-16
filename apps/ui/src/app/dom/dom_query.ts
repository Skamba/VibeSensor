function missingElement(owner: string, target: string): never {
  throw new Error(`${owner} requires ${target}`);
}

function getById<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

export function requiredById<T extends HTMLElement>(id: string, owner: string): T {
  return getById<T>(id) ?? missingElement(owner, `#${id}`);
}

export function queryOne<T extends Element>(selector: string): T | null {
  return document.querySelector<T>(selector);
}
