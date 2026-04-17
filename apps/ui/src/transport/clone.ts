export function cloneTransportValue<T>(value: T): T {
  return structuredClone(value);
}
