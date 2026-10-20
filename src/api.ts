export type Span = { id: string; page: number; text: string };
export type MatrixField = { text: string; span_id: string | null };
export type Doc = { id: string; title: string; filename: string; pages: number; spans: Span[]; matrix: Record<string, any>; has_original?: boolean };
export type ReadingEntry = { id: string; section: string; title: string; body: string; grade: string; span_ids: string[]; rationale: string; diagnostic: string; cost: string; note_id?: string };
export type ReadingAnnotation = { id: string; span_id: string; quote: string; kind: string; note: string; created: string };
export type PaperReading = { document_id: string; goal: string; entries: ReadingEntry[]; annotations: ReadingAnnotation[]; coverage: { mode: string; start_page?: number; end_page?: number; feedback_count?: number }; updated: string | null; warnings?: string[] };
export type Run = { id: string; name: string; status: string; config: Record<string, any>; metrics: Record<string, number>; log: string; artifacts: string[]; created: string; finished?: string };
export type Repo = { id: string; name: string; url: string; revision: string; files: string[] };
export type Dataset = { id: string; name: string; filename: string; row_count: number; columns: string[]; profile: { source?: string; description?: string; sheet?: string; sheet_count?: number; encoding: string; source_run_name?: string; duplicates: number; preview: string[][]; fields: { name: string; kind: string; missing: number; numeric_count: number; invalid_numeric: number; min: number | null; max: number | null }[] } };
export type Binding = { alias: string; run_id: string; metric: string; precision: number; display: 'number' | 'percent' };
export type ReportForm = { title: string; template: string; bindings: Binding[]; chart_run_ids: string[]; chart_metrics: string[] };
export type Report = ReportForm & { id: string; preview: string; sync_status: string; errors: string[]; changes: { alias: string; before: string; after: string; source_changed: boolean }[]; generated: { id?: string; version?: number; created?: string; files?: string[] } };
export type NoteForm = { title: string; hypothesis: string; prediction: string; outcome: string; decision: string; source_refs: { document_id: string; span_id: string }[]; run_ids: string[] };
export type ResearchNote = NoteForm & { id: string; created: string; updated: string; sources?: { document_id: string; span_id: string; title: string; page: number; text: string }[]; runs?: Run[]; linked_reports?: Report[]; gaps?: string[] };
export type ExperimentSeries = { id: string; name: string; status: string; config: { factor: string; seeds: number[]; variants: { index: number; label: string; value: number | boolean }[]; note_id: string }; run_ids: string[]; created: string };
export type SeriesResult = ExperimentSeries & { runs: Run[]; completed: number; summary: { index: number; label: string; n: number; expected: number; mean: number | null; std: number | null; paired_n: number; paired_mean_delta: number | null; positive_pairs: number; negative_pairs: number; ties: number }[]; paired: { variant: string; seed: number; control: number; value: number; delta: number; run_id: string }[]; notes: string[] };
export type Project = { id: string; name: string; question: string; documents: Doc[]; runs: Run[]; repositories: Repo[]; datasets?: Dataset[]; reports?: Report[]; research_notes?: ResearchNote[]; experiment_series?: ExperimentSeries[] };
export type Evidence = Span & { document_id: string; title: string; citation: string; score: number };
export type Answer = { mode: string; answer: string; evidence: Evidence[]; claims: { text: string; citations: string[] }[] };
export type ModuleProps = { project: Project; busy: string; action: (key: string, work: () => Promise<any>, success?: string) => Promise<void> };

export async function api(path: string, options: RequestInit = {}) {
  const response = await fetch('/api' + path, { ...options, headers: { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...options.headers } });
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(typeof data.detail === 'string' ? data.detail : '操作未完成，请检查输入后重试'); }
  return response.json();
}
export const post = (path: string, body: unknown = {}) => api(path, { method: 'POST', body: JSON.stringify(body) });
