"""Bounded, page-at-a-time PDF extraction. Emits JSON lines, never imports the API."""
import json
from collections import defaultdict
from itertools import chain, islice
from pathlib import Path
import re
import statistics
import sys

import pdfplumber


# Some CJK TeX builds map Latin T1 glyphs to a CJK code range. Limit
# the repair to the affected EC fonts and a font-wide shifted mapping.
SHIFTED_TEX = str.maketrans({
    **{0x6500 + c: chr(c) for c in range(32, 127)},
    0x6510: '“', 0x6511: '”', 0x6516: '–', 0x6517: '—',
    0x651B: 'ff', 0x651C: 'fi', 0x651D: 'fl', 0x651E: 'ffi', 0x651F: 'ffl',
})


def repair_tex_characters(chars):
    runs = defaultdict(list)
    for char in chars:
        if re.search(r'(?:^|\+)SF(?:RM|BX|TI|SL|SS|TT)\d+$', char['fontname']):
            runs[char['fontname']].append(char)
    for run in runs.values():
        shifted = [char for char in run if len(char['text']) == 1 and ord(char['text']) in SHIFTED_TEX]
        if len(shifted) < 4 or len(shifted) < .9 * len(run):
            continue
        for char in shifted:
            char['text'] = char['text'].translate(SHIFTED_TEX)


def heading_level(text, size, median, bold=False):
    text = text.strip()
    if len(text) > 160:
        return 0
    numbered = re.match(r'^(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+[^\W\d_]', text)
    if numbered and (bold or size >= median * 1.04):
        return min(3, numbered[1].count('.') + 1)
    if len(text) <= 100 and (bold or text.isupper()) and re.match(r'^[IVXLCDM]{1,5}\.\s+[^\W\d_]', text):
        return 1
    if re.fullmatch(r'(?:[IVXLCDM]+\.\s*)?(?:abstract|references|bibliography|conclusions?|introduction|摘要|参考文献|结论)|(?:[A-Z]\s+)?(?:appendix|附录)(?:\s+.{1,85})?', text, re.I):
        return 1
    if (bold or size >= median * 1.22) and len(text) <= 120 and not re.match(r'^(?:\[\d+\]|\d+\s|https?://)', text):
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
    sizes = [c['size'] for c in page.chars if c.get('text', '').strip()]
    median = statistics.median(sizes) if sizes else 10
    words = page.extract_words(x_tolerance_ratio=.12, return_chars=True)
    margins = defaultdict(list)
    for word in words:
        if (re.fullmatch(r'\d{1,4}', word['text']) and word['x1'] - word['x0'] < 21
                and max(c['size'] for c in word['chars']) <= median * .86
                and (word['x0'] < page.width * .17 or word['x1'] > page.width * .83)):
            side = word['x0'] < page.width / 2
            margins[side, round((word['x1'] if side else word['x0']) / 3)].append(word)
    removed = set()
    for group in margins.values():
        ordered = sorted(group, key=lambda w: w['top'])
        consecutive = sum(int(b['text']) - int(a['text']) == 1 for a, b in zip(ordered, ordered[1:]))
        if consecutive >= 5 and consecutive >= .65 * (len(ordered) - 1):
            removed.update((c['x0'], c['top'], c['text']) for word in ordered for c in word['chars'])
    layout = page.filter(lambda obj: obj['object_type'] != 'char' or
                         (obj['x0'], obj['top'], obj['text']) not in removed) if removed else page
    center = float(page.width) / 2
    lines = layout.extract_text_lines(return_chars=True, x_tolerance_ratio=.12)
    signals, broad = [], []
    for line in lines:
        chars = [c for c in line['chars'] if c['text'].strip()]
        left = [c for c in chars if c['x1'] <= center]
        right = [c for c in chars if c['x0'] >= center]
        if (len(left) > 4 and len(right) > 4 and len(chars) == len(left) + len(right)
                and min(c['x0'] for c in right) - max(c['x1'] for c in left) >= max(8, median * .9)):
            signals.append(line['top'])
            if line['x1'] - line['x0'] >= page.width * .6:
                broad.append(line['top'])
    band = next((broad[i:i + 4] for i in range(len(broad) - 3)
                 if broad[i + 3] - broad[i] < median * 13), None)
    regions = [layout]
    if band:
        start = max(0, min(t for t in signals if band[0] - median * 3 <= t <= band[0]) - 1)
        # Front matter is often full-width or three-column, while the body is two-column.
        if start > median * 4:
            abstract = [l['top'] for l in lines if re.match(r'^abstract\b', l['text'], re.I)
                        and 0 <= start - l['top'] <= median * 5]
            if abstract:
                start = abstract[-1] - 1
        x0, y0, x1, y1 = page.bbox
        regions = ([layout.crop((x0, y0, x1, start))] if start > y0 else []) + [
            layout.crop((x0, max(y0, start), center, y1)),
            layout.crop((center, max(y0, start), x1, y1))]
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
            chars = [c for c in line['chars'] if c['text'].strip()]
            bold = bool(chars and sum(bool(re.search(r'bold|cmbx|cmtib', c.get('fontname', ''), re.I))
                                      for c in chars) >= .8 * len(chars))
            level = heading_level(text, size, median, bold)
            gap = line['top'] - pending[-1]['bottom'] if pending else 0
            outdent = bool(pending and pending[-1]['x0'] - line['x0'] > median
                           and re.match(r'^(?:\[\d+\]|\d{1,3}\.\s|[^\W\d_])', text))
            if level or outdent or gap > median * .9 or sum(len(x['text']) for x in pending) > 1100:
                flush()
            if level:
                blocks.append({'text': text, 'kind': 'heading', 'bbox': [line['x0'], line['top'], line['x1'], line['bottom']], 'level': level, 'font_size': round(size,2)})
            else:
                pending.append(line)
        flush()
    return blocks, bool(band)


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
            # The CJK TeX fonts can simulate bold by slightly offsetting
            # identical glyphs. Preserve separately positioned characters.
            layout = (page.dedupe_chars(tolerance=.25)
                      if any(re.search(r'(?:^|\+)gbsn', c['fontname'], re.I) for c in page.chars) else page)
            repair_tex_characters(layout.chars)
            blocks, columns = text_blocks(layout)
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
                for table in layout.find_tables()[:30]:
                    rows = table.extract()
                    if len(rows) >= 2 and len(rows[0]) >= 2:
                        tables.append({'bbox': list(table.bbox), 'rows': rows, 'method': 'vector-lines'})
            # Borderless academic tables: only attempt on pages with a table caption.
            if method == 'native' and not tables and any(re.search(r'\bTable\s+\d|表\s*\d', b['text']) for b in blocks):
                for table in layout.find_tables({'vertical_strategy': 'text', 'horizontal_strategy': 'text', 'min_words_vertical': 4})[:3]:
                    rows = [r for r in table.extract() if sum(bool(c and c.strip()) for c in r) >= 2]
                    numeric = sum(bool(re.search(r'\d', str(c))) for r in rows for c in r)
                    if 2 <= len(rows) <= 100 and 2 <= len(rows[0]) <= 15 and numeric >= 4:
                        tables.append({'bbox': list(table.bbox), 'rows': rows, 'method': 'text-alignment-candidate', 'uncertain': True})
            figures = [{'bbox': [im['x0'], im['top'], im['x1'], im['bottom']], 'method': 'image'}
                       for im in page.images[:50]]
            if method == 'native':
                figures.extend(vector_figures(page, blocks, figures))
            for n, block in enumerate(blocks, 1):
                block['id'] = f'p{index}-s{n}'
                block['page'] = index
                block['bbox'] = [round(float(x), 2) for x in block['bbox']]
                block['formula_candidate'] = bool(re.search(r'[=∑∫∂√]|[α-ωΑ-Ω]', block['text']))
                latex = formula_latex(block['text'])
                if latex:
                    block['latex_candidate'] = latex
            yield {'type': 'page', 'page': index, 'width': float(page.width), 'height': float(page.height), 'method': method,
                   'columns': 2 if columns else 1, 'blocks': blocks, 'tables': tables, 'figures': figures}
            page.close()


def vector_figures(page, blocks, raster):
    figures = []
    captions = re.compile(r'(?:^|\n)\s*(?:fig(?:ure)?\.?\s*\d+[:.\s]|图\s*\d+[:：\s])', re.I)
    graphics = [g for g in islice(chain(page.curves, page.rects, page.lines), 6000)
                if g['x1'] - g['x0'] >= 4 or g['bottom'] - g['top'] >= 4]
    for caption in (b for b in blocks if captions.search(b['text'])):
        left, top, right, bottom = caption['bbox']
        center = page.width / 2
        x0, x1 = (0, center) if right < center else (center, page.width) if left > center else (0, page.width)
        near = [g for g in graphics if x0 <= g['x0'] <= g['x1'] <= x1 and
                max(0, top - 230) <= g['top'] <= g['bottom'] <= top + 2]
        if len(near) < 4 or any(f['bbox'][3] <= top and top - f['bbox'][3] < 35 and
                               x0 <= f['bbox'][0] <= f['bbox'][2] <= x1 for f in raster):
            continue
        box = [min(g['x0'] for g in near), min(g['top'] for g in near),
               max(g['x1'] for g in near), max(g['bottom'] for g in near)]
        if box[2] - box[0] >= 45 and box[3] - box[1] >= 25:
            title = captions.split(caption['text'], maxsplit=1)[-1].partition('\n')[0][:300]
            figures.append({'bbox': box, 'caption': title,
                            'method': 'vector-caption-candidate'})
        if len(figures) == 15:
            break
    return figures


def formula_latex(text):
    literal = re.fullmatch(r'\s*(?:\$\$(.+?)\$\$|\\\[(.+?)\\\])\s*', text, re.S)
    if literal:
        return next(value for value in literal.groups() if value)
    value = text.strip()
    if len(value) > 130 or '\n' in value or not re.search(r'[=≤≥∑∫√]', value):
        return None
    if re.search(r'\b[A-Za-z]{2,}\b|[\u4e00-\u9fff]', value) or not re.fullmatch(r'[\w\sα-ωΑ-Ω−±≤≥=+*/.^()∑∫√∂]+', value):
        return None
    glyphs = {'α': r'\alpha ', 'β': r'\beta ', 'γ': r'\gamma ', 'θ': r'\theta ', 'λ': r'\lambda ',
              'μ': r'\mu ', 'σ': r'\sigma ', 'π': r'\pi ', '−': '-', '±': r'\pm ',
              '≤': r'\le ', '≥': r'\ge ', '∑': r'\sum ', '∫': r'\int ', '∂': r'\partial '}
    if any(not c.isascii() and c not in glyphs for c in value):
        return None
    return ''.join(glyphs.get(c, c) for c in value)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    for item in extract(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3] == 'true'):
        print(json.dumps(item, ensure_ascii=False), flush=True)
