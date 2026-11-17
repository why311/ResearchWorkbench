"""Recover table cells from the coordinates of OCR text boxes."""
from bisect import bisect_right
import re
from statistics import median


CAPTION = re.compile(r'^\s*(?:table\s+|表\s*)(\d+(?:\.\d+)*)(?!\d|\.\d)', re.I)
NUMERIC_CELL = re.compile(r'^[+\-−]?\d+(?:[.,]\d+)?(?:\s*(?:%|[KkMmBb]|[·×]\s*10\^?[−-]?\d+))?$')
GROUP_CELL = re.compile(r'^\(?[A-Z]\)$')


def box_middle(block, axis):
    return (block['bbox'][axis] + block['bbox'][axis + 2]) / 2


def cell_text(block):
    text = block['text'].strip()
    return re.sub(r'(?<=\d)\s*[·×]\s*10\s*([−-]?\d{2,3})$', r' × 10^\1', text)


def scanned_tables(spans):
    boxes = sorted((s for s in spans if s.get('confidence') is not None and len(s.get('bbox', [])) == 4),
                   key=lambda s: box_middle(s, 1))
    tables = []
    captions = [i for i, block in enumerate(boxes) if CAPTION.match(block['text'])]
    for index, end in zip(captions, [*captions[1:], len(boxes)]):
        caption, following = boxes[index], boxes[index + 1:end]
        table = table_below(caption, following) or metric_table(caption, following)
        if table:
            tables.append(table)
    return tables


def table_below(caption, boxes):
    bottom = caption['bbox'][3]
    header_region = [s for s in boxes if bottom + 5 <= box_middle(s, 1) <= bottom + 55
                     and len(s['text'].split()) <= 5 and any(c.isalpha() for c in s['text'])]
    if not header_region:
        return None
    header_y = max((box_middle(s, 1) for s in header_region),
                   key=lambda y: sum(abs(box_middle(s, 1) - y) <= 3 for s in header_region))
    headers = [s for s in header_region if abs(box_middle(s, 1) - header_y) <= 3]
    if not 3 <= len(headers) <= 10:
        return None
    left = min(s['bbox'][0] for s in headers)
    lead = [s for s in header_region if 3 < header_y - box_middle(s, 1) <= 15 and s['bbox'][2] < left - 10]
    if lead:
        headers.append(min(lead, key=lambda s: abs(box_middle(s, 1) - header_y)))
    headers.sort(key=lambda s: box_middle(s, 0))
    centers = [box_middle(s, 0) for s in headers]
    gaps = [(a + b) / 2 for a, b in zip(centers, centers[1:])]
    if any(b - a < 16 for a, b in zip(centers, centers[1:])):
        return None
    fields = [s['text'].strip() for s in headers]
    for column in range(1, len(headers) - 1):
        boundary = gaps[column]
        parent = next((s for s in header_region if s not in headers and
                       6 <= header_y - box_middle(s, 1) <= 23 and
                       abs(box_middle(s, 0) - boundary) <= 9), None)
        if parent:
            for col in (column, column + 1):
                fields[col] = parent['text'].strip() + ' ' + fields[col]

    label_x = headers[0]['bbox'][0]
    height = median(s['bbox'][3] - s['bbox'][1] for s in headers)
    labels = []
    for s in boxes:
        y = box_middle(s, 1)
        if y <= header_y + 6 or abs(s['bbox'][0] - label_x) > 22 or not any(c.isalpha() for c in s['text']):
            continue
        if y - (box_middle(labels[-1], 1) if labels else header_y) > 2 * height:
            break
        labels.append(s)
        if len(labels) == 100:
            break
    if len(labels) < 3:
        return None
    y_values = [box_middle(s, 1) for s in labels]
    spacing = median(b - a for a, b in zip(y_values, y_values[1:]))
    if spacing < 5:
        return None
    rows = [fields] + [[cell_text(s)] + [None] * (len(fields) - 1) for s in labels]
    merges = []
    for s in boxes:
        x, y = box_middle(s, 0), box_middle(s, 1)
        if not gaps[0] + 4 <= x <= centers[-1] + 30 or s in headers or s in labels:
            continue
        row = min(range(len(labels)), key=lambda n: abs(y - y_values[n]))
        if abs(y - y_values[row]) >= spacing / 2:
            continue
        column = bisect_right(gaps, x)
        x0, _, x1, _ = s['bbox']
        boundary = next((n for n in range(1, len(gaps)) if x0 + 8 < gaps[n] < x1 - 8 and
                         abs(x - gaps[n]) <= 8), None)
        if boundary is not None:
            merges.append({'row': row + 1, 'first_column': boundary, 'last_column': boundary + 1,
                           'text': cell_text(s)})
        elif rows[row + 1][column] is None:
            rows[row + 1][column] = cell_text(s)
    shared_rows = {cell['row'] for cell in merges}
    if sum(sum(cell is not None for cell in row[1:]) + (i in shared_rows) >= 2
           for i, row in enumerate(rows[1:], 1)) < 3:
        return None
    return {'title': caption['text'], 'rows': rows, 'merged_cells': merges,
            'method': 'ocr-position', 'uncertain': True}


def aligned_tracks(boxes, axis, tolerance):
    tracks = []
    for block in sorted(boxes, key=lambda b: box_middle(b, axis)):
        center = box_middle(block, axis)
        if not tracks or center - median(box_middle(b, axis) for b in tracks[-1]) > tolerance:
            tracks.append([])
        tracks[-1].append(block)
    return tracks


def metric_table(caption, boxes):
    """Use stable numeric columns to recover rows without individual labels."""
    if not boxes:
        return None
    baselines = aligned_tracks(boxes, 1, 3.5)
    measured = []
    for line in baselines:
        numeric = [s for s in line if NUMERIC_CELL.fullmatch(s['text'].strip())]
        if not numeric or len(line) < 3:
            continue
        y = median(box_middle(s, 1) for s in line)
        if y - caption['bbox'][3] < 15:
            continue
        if not measured and y - caption['bbox'][3] > 105:
            return None
        if measured and y - measured[-1][0] > 22:
            break
        measured.append((y, line))
    if len(measured) < 4:
        return None
    first, last = measured[0][0], measured[-1][0]
    header_top = max(caption['bbox'][3] + 2, first - 36)
    headers = [s for s in boxes if header_top <= box_middle(s, 1) <= first - 8
               and s['bbox'][2] - s['bbox'][0] <= 120 and any(c.isalpha() for c in s['text'])]
    columns = aligned_tracks(headers, 0, 9)
    if not 3 <= len(columns) <= 18:
        return None
    centers = [median(box_middle(s, 0) for s in track) for track in columns]
    fields = [' '.join(cell_text(s) for s in sorted(track, key=lambda b: box_middle(b, 1))) for track in columns]
    data_left = min(box_middle(s, 0) for _, line in measured for s in line)
    if centers[0] - data_left > 16:
        centers.insert(0, data_left)
        fields.insert(0, '行组')
    bounds = [(a + b) / 2 for a, b in zip(centers, centers[1:])]
    rows = [fields]
    for _, line in measured:
        row = [None] * len(fields)
        for s in line:
            if GROUP_CELL.fullmatch(s['text'].strip()):
                continue
            x = box_middle(s, 0)
            col = bisect_right(bounds, x)
            value = cell_text(s)
            row[col] = f'{row[col]} {value}' if row[col] else value
        rows.append(row)
    if fields[0] != '行组' and all(row[0] is None for row in rows[1:]):
        for row in rows:
            row.pop(0)
    if sum(row[-1] is not None and NUMERIC_CELL.fullmatch(row[-1]) is not None for row in rows[1:]) < len(measured) * .75:
        return None

    merges = []
    if fields[0] == '行组':
        groups = [s for s in boxes if first < box_middle(s, 1) < last and box_middle(s, 0) < bounds[0]
                  and GROUP_CELL.fullmatch(s['text'].strip())]
        start = 1  # Zero-based first variant after the baseline row.
        for group in groups:
            y = box_middle(group, 1)
            if start >= len(measured) - 1 or measured[start][0] > y + 3.5:
                break
            end = min(range(start, len(measured) - 1), key=lambda i: abs((measured[start][0] + measured[i][0]) / 2 - y))
            if abs((measured[start][0] + measured[end][0]) / 2 - y) > 4:
                break
            merges.append({'row': start + 1, 'last_row': end + 1, 'first_column': 0, 'last_column': 0,
                           'text': cell_text(group)})
            start = end + 1
    return {'title': caption['text'], 'rows': rows, 'merged_cells': merges,
            'method': 'ocr-position', 'uncertain': True}
