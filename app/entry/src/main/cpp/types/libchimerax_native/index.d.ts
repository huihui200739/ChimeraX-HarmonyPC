export interface RuntimeReport {
  initialized: boolean;
  version: string;
  prefix: string;
  home: string;
  error: string;
}
export interface ExpressionReport {
  ok: boolean;
  value: string;
  error: string;
}
export const initializeRuntime: (home: string) => RuntimeReport;
export const runExpression: (expression: string) => ExpressionReport;
export const finalizeRuntime: () => { finalized: boolean };
