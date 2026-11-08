export async function api(path: string, options: RequestInit = {}) {
  const response = await fetch('/api' + path, { ...options, headers: { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...options.headers } });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求未完成，请重试');
  return data;
}

export const post=(path:string,body:object={})=>api(path,{method:'POST',body:JSON.stringify(body)});
export type Span = { id: string; page: number; text: string; kind?: string; bbox?: number[]; level?: number; confidence?: number; formula_candidate?: boolean };
export type ComparedEvidence = Evidence & { quote?: string };
export type ComparisonCell = { field: string; value: string; status: string; evidence: ComparedEvidence[] };
export type Comparison = { fields: string[]; rows: { document_id: string; title: string; scope: string; cells: ComparisonCell[] }[]; warnings: string[]; mode: string; retrieval: string; limitation: string };
export type ResearchTask = { id: string; kind: string; intent: string; status: string; mode: string; fields: string[]; document_ids: string[]; steps: { tool: string; status: string; progress?: string; arguments: Record<string, any>; output: any; started: string; finished?: string }[]; result: { note_id?: string; comparison?: Comparison; checklist?: any[]; claims?: { text: string; citation: string; quote: string; source: Evidence }[]; note?: string; evidence?: Evidence[] }; error: string; created: string; updated: string };
export type Evidence = Span & { document_id: string; title: string; citation: string; score: number };
export type ModuleProps = {
  project: { id: string; question: string; documents: { id: string; title: string; pages: number; span_count?: number; ingestion?: { completed: number } }[] };
  busy: string;
  action: (key: string, task: () => Promise<unknown>, success?: string) => Promise<void>;
};

export type Run = { id: string; name: string; status: string; config: Record<string, any>; metrics: Record<string, number>; log: string; artifacts: string[]; created: string; finished?: string };
export type Repo = { id: string; name: string; url: string; revision: string; files: string[] };
export type Dataset = { id: string; name: string; filename: string; row_count: number; columns: string[]; profile: { source?: string; description?: string; sheet?: string; sheet_count?: number; encoding: string; source_run_name?: string; duplicates: number; preview: string[][]; fields: { name: string; kind: string; missing: number; numeric_count: number; invalid_numeric: number; min: number | null; max: number | null }[] } };
export type ExperimentSeries = { id: string; name: string; status: string; config: { factor: string; metric?: string; seeds: number[]; variants: { index: number; label: string; value: number | boolean }[]; note_id: string }; run_ids: string[]; created: string };
export type SeriesResult = ExperimentSeries & { runs: Run[]; completed: number; summary: { index: number; label: string; n: number; expected: number; mean: number | null; std: number | null; paired_n: number; paired_mean_delta: number | null; positive_pairs: number; negative_pairs: number; ties: number }[]; paired: { variant: string; seed: number; control: number; value: number; delta: number; run_id: string }[]; notes: string[] };
export type ExperimentRecords = {
  runs: Run[];
  repositories: Repo[];
  datasets: Dataset[];
  experiment_series: ExperimentSeries[];
  research_notes: { id: string; title: string }[];
};
export type ExperimentProps = Omit<ModuleProps, 'project'> & { project: ModuleProps['project'] & ExperimentRecords };
