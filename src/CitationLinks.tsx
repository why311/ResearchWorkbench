export type CitationRef = { number: number; span_id: string; page: number; text: string; backlinks: { span_id: string; page: number; text: string }[]; review_reasons?: string[] };
export function CitationText({ text, references, jump }: { text: string; references: CitationRef[]; jump: (sid: string) => void }) {
  return <>{text.split(/(\[\d{1,4}(?:\s*[,，;；–—-]\s*\d{1,4})*\])/g).map((part, i) => { const number = Number(part.match(/^\[(\d+)/)?.[1]), ref = references.find(r => r.number === number); return ref ? <button className="citation-inline" key={i} title={`跳至参考文献${number}`} onClick={() => jump(ref.span_id)}>{part}</button> : part; })}</>;
}
