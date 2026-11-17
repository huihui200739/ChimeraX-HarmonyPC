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
export interface ExtractReport {
  ok: boolean;
  files: number;
  skipped: number;
  error: string;
}
export const extractArchive: (archive: string, destination: string) => ExtractReport;
