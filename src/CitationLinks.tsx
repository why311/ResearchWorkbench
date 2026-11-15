import { Fragment, useState } from 'react';

export type CitationRef = { id: string; number: number | null; label: string; span_id: string; page: number; text: string; backlinks: { span_id: string; page: number; text: string }[]; review_reasons?: string[] };
export type CitationMention = { start: number; end: number; label: string; span_id: string; reference_span_id: string; number: number | null };

export function CitationText({ text, mentions, jump }: { text: string; mentions: CitationMention[]; jump: (sid: string) => void }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  if (!mentions.length) return <>{text}</>;
  const characters = Array.from(text);
  const slice = (start: number, end?: number) => characters.slice(start, end).join('');
  const groups = new Map<number, CitationMention[]>();
  for (const mention of mentions) {
    const shared = groups.get(mention.start) ?? [];
    shared.push(mention);
    groups.set(mention.start, shared);
  }
  let position = 0;
  const pieces = [...groups].sort(([a], [b]) => a - b).map(([start, group]) => {
    const end = group[0].end;
    if (start < position || end > characters.length) return null;
    const preceding = slice(position, start);
    position = end;
    return <Fragment key={start}>{preceding}{group.length === 1
      ? <button className="citation-inline" title="跳至参考文献" onClick={() => jump(group[0].reference_span_id)}>{slice(start, end)}</button>
      : <><button className="citation-inline" aria-expanded={expanded === start} title="选择参考文献"
        onClick={() => setExpanded(expanded === start ? null : start)}>{slice(start, end)}</button>
        {expanded === start && group.map(m => <button key={m.number} className="citation-inline" title={`跳至参考文献 ${m.number}`}
          onClick={() => { setExpanded(null); jump(m.reference_span_id); }}>[{m.number}]</button>)}</>}</Fragment>;
  });
  return <>{pieces}{slice(position)}</>;
}
