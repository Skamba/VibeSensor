declare module "node:assert/strict" {
  const assert: {
    deepEqual(actual: unknown, expected: unknown, message?: string): void;
    equal(actual: unknown, expected: unknown, message?: string): void;
    fail(message?: string): never;
    doesNotMatch(actual: string, regexp: RegExp, message?: string): void;
    notEqual(actual: unknown, expected: unknown, message?: string): void;
    match(actual: string, regexp: RegExp, message?: string): void;
    ok(value: unknown, message?: string): asserts value;
  };
  export default assert;
}

declare function setImmediate(
  callback: (...args: unknown[]) => void,
  ...args: unknown[]
): number;
