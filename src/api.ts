export async function api(path: string, options: RequestInit = {}) {
  const response = await fetch('/api' + path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
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
  project: { id: string; question: string; documents: { id: string; title: string; pages: number; ingestion?: { completed: number } }[] };
  busy: string;
  action: (key: string, task: () => Promise<unknown>, success?: string) => Promise<void>;
};
