"""Render saved report values and source excerpts consistently across exports."""
import re

CITATION = r'\[\[cite:([A-Za-z][A-Za-z0-9_]{0,39})\]\]'


def body_markdown(state):
    values = {b['alias']: b['formatted'] for b in state['bindings']}
    text = re.sub(r'\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}', lambda m: values.get(m[1], '(引用失效)'), state['template'])
    numbers = {c['alias']: c['number'] for c in state.get('citations', [])}
    return re.sub(CITATION, lambda m: f'[{numbers[m[1]]}]' if m[1] in numbers else '(文献引用失效)', text)


def evidence_markdown(citations):
    if not citations:
        return ''
    text = '\n\n## 文献原文依据\n\n以下为作者选择的原文片段，保留来源以便核对；引用本身不表示原文支持作者的全部推断。\n'
    for c in citations:
        title = re.sub(r'([\\`*{}\[\]<>!#|_$])', r'\\\1', c['title']).replace('\n', ' ')
        text += f'\n### [{c["number"]}] {title} · 第{c["page"]}页\n\n'
        text += '\n'.join('> ' + re.sub(r'([\\`*{}\[\]<>!#|_$])', r'\\\1', line) for line in c['text'].splitlines())
        text += f'\n\n文献编号：{c["document_id"]}；原文片段：{c["span_id"]}\n'
    return text
