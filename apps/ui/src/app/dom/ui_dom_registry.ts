export type UiDomRegistry = {
  root: Document;
};

export function createUiDomRegistry(root: Document = document): UiDomRegistry {
  return { root };
}
