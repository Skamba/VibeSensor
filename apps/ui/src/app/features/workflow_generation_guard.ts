export interface WorkflowGenerationGuard {
  begin(): number;
  invalidate(): void;
  isCurrent(generation: number): boolean;
  isLatest(generation: number): boolean;
}

export interface WorkflowGenerationGuardOptions {
  isActive?: () => boolean;
}

export function createWorkflowGenerationGuard(
  options: WorkflowGenerationGuardOptions = {},
): WorkflowGenerationGuard {
  const isActive = options.isActive ?? (() => true);
  let currentGeneration = 0;
  return {
    begin() {
      currentGeneration += 1;
      return currentGeneration;
    },
    invalidate() {
      currentGeneration += 1;
    },
    isCurrent(generation) {
      return isActive() && generation === currentGeneration;
    },
    isLatest(generation) {
      return generation === currentGeneration;
    },
  };
}
