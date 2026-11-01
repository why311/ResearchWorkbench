"""Bounded, page-at-a-time PDF extraction. Emits JSON lines, never imports the API."""
import json
from pathlib import Path
import re
import statistics
import sys

import pdfplumber


def heading_level(text, size, median):
    text = text.strip()
    if len(text) > 160:
        return 0
    numbered = re.match(r'^(\d+(?:\.\d+){0,2})[.\s]+\S', text)
    if numbered:
        return min(3, numbered[1].count('.') + 1)
    if re.match(r'^(?:abstract|references|bibliography|appendix|conclusions?|introduction|摘要|参考文献|附录|结论)\b', text, re.I):
        return 1
    if size >= median * 1.2:
        return 1 if size >= median * 1.5 else 2
    return 0


def order_ocr(blocks, width):
    """Read a detected two-column band downwards, preserving full-width lines."""
    center = width / 2
    wide = [b for b in blocks if b['bbox'][0] < center-12 and b['bbox'][2] > center+12]
    narrow = [b for b in blocks if b not in wide]
    left = [b for b in narrow if (b['bbox'][0]+b['bbox'][2])/2 < center]
    right = [b for b in narrow if b not in left]
    shared = {round(b['bbox'][1]/10) for b in left} & {round(b['bbox'][1]/10) for b in right}
    if min(len(left), len(right)) < 6 or len(shared) < 4 or len(wide) > len(blocks)*.3:
        return sorted(blocks, key=lambda b: (b['bbox'][1], b['bbox'][0])), False
    ordered = []
    for divider in sorted(wide, key=lambda b: b['bbox'][1]):
        for column in (left, right):
            before = [b for b in column if b['bbox'][1] < divider['bbox'][1]]
            ordered.extend(sorted(before, key=lambda b: b['bbox'][1]))
            column[:] = [b for b in column if b not in before]
        ordered.append(divider)
    ordered.extend(sorted(left, key=lambda b: b['bbox'][1]))
    ordered.extend(sorted(right, key=lambda b: b['bbox'][1]))
    return ordered, True


def text_blocks(page):
    # Find a genuine empty central gutter. Full-width titles stay above the columns.
    words = page.extract_words(x_tolerance_ratio=.12)
    center = float(page.width) / 2
    interior = [w for w in words if float(page.height) * .15 < w['top'] < float(page.height) * .9]
    left = [w for w in interior if w['x1'] < center - 8]
    right = [w for w in interior if w['x0'] > center + 8]
    crossing = [w for w in interior if w['x0'] < center < w['x1']]
    left_lines = {round(w['top'] / 4) for w in left}
    right_lines = {round(w['top'] / 4) for w in right}
    columns = len(left) > 35 and len(right) > 35 and len(left_lines & right_lines) >= 8 and len(crossing) < 3
    regions = [page]
    if columns:
        top = min(w['top'] for w in interior if w['x0'] > center + 8)
        # Include full-width headings preceding the body, then read left to right.
        regions = ([page.crop((0, 0, page.width, top - 1))] if top > 10 else []) + [
            page.crop((0, max(0, top - 1), center, page.height)),
            page.crop((center, max(0, top - 1), page.width, page.height))]
    sizes = [c['size'] for c in page.chars if c.get('text', '').strip()]
    median = statistics.median(sizes) if sizes else 10
    blocks = []
    for region in regions:
        lines = region.extract_text_lines(return_chars=True, x_tolerance_ratio=.12)
        pending = []
        def flush():
            if not pending:
                return
            text = '\n'.join(x['text'] for x in pending)
            box = [min(x['x0'] for x in pending), min(x['top'] for x in pending), max(x['x1'] for x in pending), max(x['bottom'] for x in pending)]
            for offset in range(0, len(text), 1500):
                blocks.append({'text': text[offset:offset + 1500], 'kind': 'paragraph', 'bbox': box, 'level': 0,
                               'font_size': round(statistics.median(c['size'] for line in pending for c in line.get('chars', []) if c.get('text','').strip()),2)})
            pending.clear()
        for line in lines:
            text = line['text'].strip()
            if not text:
                continue
            size = max((c['size'] for c in line.get('chars', [])), default=median)
            level = heading_level(text, size, median)
            gap = line['top'] - pending[-1]['bottom'] if pending else 0
            if level or gap > median * .9 or sum(len(x['text']) for x in pending) > 1100:
                flush()
            if level:
                blocks.append({'text': text, 'kind': 'heading', 'bbox': [line['x0'], line['top'], line['x1'], line['bottom']], 'level': level, 'font_size': round(size,2)})
            else:
                pending.append(line)
        flush()
    return blocks, columns


def extract(path, start=1, ocr=True):
    engine = None
    with pdfplumber.open(path) as pdf:
        yield {'type': 'metadata', 'pages': len(pdf.pages), 'metadata': {k: str(v)[:500] for k, v in pdf.metadata.items() if k in {'Title', 'Author', 'Subject'}}}
        for index, page in enumerate(pdf.pages, 1):
            if index < start:
                page.close()
                continue
            if len(page.chars) > 100000:
                raise ValueError(f'第{index}页字符过多，超过单页解析预算')
            blocks, columns = text_blocks(page)
            method = 'native'
            # OCR is local; text-only pages do not load an OCR model.
            if sum(len(b['text'].strip()) for b in blocks) < 15 and page.images and ocr:
                if engine is None:
                    from rapidocr_onnxruntime import RapidOCR
                    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
                image = page.to_image(resolution=min(144, 1800 * 72 / max(page.width, page.height))).original
                import numpy as np
                results, _ = engine(np.asarray(image))
                sx, sy = float(page.width) / image.width, float(page.height) / image.height
                image.close()
                blocks = []
                for points, text, confidence in results or []:
                    box = [min(p[0] for p in points) * sx, min(p[1] for p in points) * sy, max(p[0] for p in points) * sx, max(p[1] for p in points) * sy]
                    level = heading_level(text, 10, 10)
                    blocks.append({'text': text, 'kind': 'heading' if level else 'paragraph', 'bbox': box, 'level': level, 'confidence': round(float(confidence), 3), 'font_size': round((box[3]-box[1])*.75,2)})
                method = 'ocr'
                blocks, columns = order_ocr(blocks, float(page.width))
            tables = []
            if method == 'native' and (page.lines or page.rects):
                for table in page.find_tables()[:30]:
                    rows = table.extract()
                    if len(rows) >= 2 and len(rows[0]) >= 2:
                        tables.append({'bbox': list(table.bbox), 'rows': rows, 'method': 'vector-lines'})
            # Borderless academic tables: only attempt on pages with a table caption.
            if method == 'native' and not tables and any(re.search(r'\bTable\s+\d|表\s*\d', b['text']) for b in blocks):
                for table in page.find_tables({'vertical_strategy': 'text', 'horizontal_strategy': 'text', 'min_words_vertical': 4})[:3]:
                    rows = [r for r in table.extract() if sum(bool(c and c.strip()) for c in r) >= 2]
                    numeric = sum(bool(re.search(r'\d', str(c))) for r in rows for c in r)
                    if 2 <= len(rows) <= 100 and 2 <= len(rows[0]) <= 15 and numeric >= 4:
                        tables.append({'bbox': list(table.bbox), 'rows': rows, 'method': 'text-alignment-candidate', 'uncertain': True})
            figures = [{'bbox': [im['x0'], im['top'], im['x1'], im['bottom']]} for im in page.images[:50]]
            for n, block in enumerate(blocks, 1):
                block['id'] = f'p{index}-s{n}'
                block['page'] = index
                block['bbox'] = [round(float(x), 2) for x in block['bbox']]
                block['formula_candidate'] = bool(re.search(r'[=∑∫∂√]|[α-ωΑ-Ω]', block['text']))
            yield {'type': 'page', 'page': index, 'width': float(page.width), 'height': float(page.height), 'method': method,
                   'columns': 2 if columns else 1, 'blocks': blocks, 'tables': tables, 'figures': figures}
            page.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    for item in extract(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3] == 'true'):
        print(json.dumps(item, ensure_ascii=False), flush=True)
