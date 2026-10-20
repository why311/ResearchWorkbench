"""Trusted tabular analysis runner. Exported copies also run independently."""
import argparse
import csv
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

MISSING = {'', 'na', 'n/a', 'null', 'none', 'nan'}


def number(value):
    if value is None or str(value).strip().lower() in MISSING:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return '' if value is None else value


def write_csv(path, headers, rows):
    with Path(path).open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow([safe_cell(h) for h in headers])
        for row in rows:
            writer.writerow([safe_cell(v) for v in row])


def configure_plot():
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({'axes.unicode_minus': False, 'axes.spines.top': False,
                         'axes.spines.right': False, 'font.size': 10, 'savefig.dpi': 160})


def summary(values, column, total):
    numeric = np.asarray([v for v in values if v is not None], dtype=float)
    count = len(numeric)
    result = {'column': column, 'count': count, 'missing': total - count,
              'mean': None, 'median': None, 'std': None, 'min': None, 'max': None}
    if count:
        result.update(mean=float(np.mean(numeric)), median=float(np.median(numeric)),
                      std=float(np.std(numeric, ddof=1)) if count > 1 else None,
                      min=float(np.min(numeric)), max=float(np.max(numeric)))
    if any(isinstance(v, float) and not math.isfinite(v) for v in result.values()):
        raise ValueError('数值量级导致统计溢出，请检查数据或换算系数。')
    return result


def analyze(input_path, plan, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with Path(input_path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames
        rows = list(reader)
    columns = plan['columns']
    group_by = plan.get('group_by', '')
    if not columns or len(set(columns)) != len(columns) or any(c not in headers for c in columns):
        raise ValueError('分析字段为空、重复或不存在。')
    if group_by and group_by not in headers:
        raise ValueError('分组字段不存在。')
    audit = {'input_rows': len(rows), 'duplicates_removed': 0, 'filtered_rows': 0,
             'missing_rows_removed': 0, 'invalid_cells': 0, 'imputed_cells': 0, 'output_rows': 0}
    if plan.get('deduplicate'):
        seen, unique = set(), []
        for row in rows:
            key = tuple(row[h] for h in headers)
            if key not in seen:
                seen.add(key)
                unique.append(row)
        audit['duplicates_removed'] = len(rows) - len(unique)
        rows = unique
    for row in rows:
        for column in columns:
            raw = row[column]
            value = number(raw)
            if value is None and str(raw).strip().lower() not in MISSING:
                audit['invalid_cells'] += 1
            if value is not None:
                value *= plan.get('scales', {}).get(column, 1)
                if not math.isfinite(value):
                    raise ValueError('换算结果超出有效数值范围。')
            row[column] = value
    for condition in plan.get('filters', []):
        column = condition['column']
        if column not in columns:
            raise ValueError('范围筛选字段必须是所选分析字段。')
        before = len(rows)
        rows = [r for r in rows if r[column] is not None
                and (condition.get('minimum') is None or r[column] >= condition['minimum'])
                and (condition.get('maximum') is None or r[column] <= condition['maximum'])]
        audit['filtered_rows'] += before - len(rows)
    if plan['missing'] == 'drop':
        before = len(rows)
        rows = [r for r in rows if all(r[c] is not None for c in columns)
                and (not group_by or str(r[group_by]).strip().lower() not in MISSING)]
        audit['missing_rows_removed'] = before - len(rows)
    elif plan['missing'] == 'median':
        for column in columns:
            valid = [r[column] for r in rows if r[column] is not None]
            if not valid:
                raise ValueError(f'字段“{column}”全部缺失，无法计算中位数用于填补。')
            median = float(np.median(valid))
            for row in rows:
                if row[column] is None:
                    row[column] = median
                    audit['imputed_cells'] += 1
    if not rows:
        raise ValueError('处理后没有剩余样本，请调整筛选或缺失值处理。')
    audit['output_rows'] = len(rows)
    print('实际处理计数：' + json.dumps(audit, ensure_ascii=False), flush=True)
    summaries = [summary([r[c] for r in rows], c, len(rows)) for c in columns]
    grouped, correlations = [], []
    if 'groups' in plan['methods']:
        groups = {}
        for row in rows:
            label = str(row[group_by]) if str(row[group_by]).strip().lower() not in MISSING else '(缺失)'
            groups.setdefault(label, []).append(row)
        for label, members in groups.items():
            for column in columns:
                grouped.append({'group': label, **summary([r[column] for r in members], column, len(members))})
    if 'correlation' in plan['methods']:
        for i, a in enumerate(columns):
            for b in columns[i + 1:]:
                pairs = [(r[a], r[b]) for r in rows if r[a] is not None and r[b] is not None]
                coefficient = None
                if len(pairs) >= 2:
                    values = np.asarray(pairs, dtype=float)
                    if np.std(values[:, 0]) > 0 and np.std(values[:, 1]) > 0:
                        coefficient = float(np.corrcoef(values, rowvar=False)[0, 1])
                correlations.append({'x': a, 'y': b, 'n': len(pairs), 'pearson_r': coefficient})
    result = {'audit': audit, 'summary': summaries, 'groups': grouped, 'correlations': correlations,
              'plan': plan, 'notes': ['标准差使用样本标准差（ddof=1）；少于2个有效值时不计算。',
              '相关系数按两字段的成对有效样本计算；常量列或不足2对时不计算。',
              '分析是描述性的，不自动给出因果或统计显著性结论。']}
    (output / 'analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    write_csv(output / 'cleaned.csv', headers, [[r[h] for h in headers] for r in rows])
    stat_headers = ['column', 'count', 'missing', 'mean', 'median', 'std', 'min', 'max']
    write_csv(output / 'summary.csv', stat_headers, [[r[h] for h in stat_headers] for r in summaries])
    if grouped:
        group_headers = ['group', *stat_headers]
        write_csv(output / 'groups.csv', group_headers, [[r[h] for h in group_headers] for r in grouped])
    if correlations:
        write_csv(output / 'correlations.csv', ['x', 'y', 'n', 'pearson_r'], [[r['x'], r['y'], r['n'], r['pearson_r']] for r in correlations])
    metrics = {'input_rows': audit['input_rows'], 'output_rows': len(rows), 'imputed_cells': audit['imputed_cells']}
    metrics.update({f'mean:{r["column"]}': r['mean'] for r in summaries if r['mean'] is not None})
    (output / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    configure_plot()
    fig, axes = plt.subplots(len(columns), 1, figsize=(7, max(3, 2.8 * len(columns))), squeeze=False)
    for axis, column in zip(axes[:, 0], columns):
        values = [r[column] for r in rows if r[column] is not None]
        if values:
            axis.hist(values, bins=min(20, max(3, int(np.sqrt(len(values))))), color='#4265bc', edgecolor='white')
        else:
            axis.text(.5, .5, 'No valid observations', ha='center', transform=axis.transAxes)
        axis.set_title(column)
        axis.set_ylabel('Count')
    fig.tight_layout()
    fig.savefig(output / 'distribution.png')
    plt.close(fig)
    if grouped:
        labels = list(dict.fromkeys(r['group'] for r in grouped))[:15]
        fig, axes = plt.subplots(len(columns), 1, figsize=(8, max(3, 3 * len(columns))), squeeze=False)
        for axis, column in zip(axes[:, 0], columns):
            subset = [r for r in grouped if r['column'] == column and r['group'] in labels and r['mean'] is not None]
            axis.bar([r['group'] for r in subset], [r['mean'] for r in subset], color='#4265bc')
            axis.set_title(f'{column} · group means (first 15 groups)')
            axis.tick_params(axis='x', rotation=25)
        fig.tight_layout()
        fig.savefig(output / 'groups.png')
        plt.close(fig)
    if correlations:
        matrix = np.full((len(columns), len(columns)), np.nan)
        for i, column in enumerate(columns):
            valid = [r[column] for r in rows if r[column] is not None]
            if len(valid) >= 2 and np.std(valid) > 0:
                matrix[i, i] = 1
        for r in correlations:
            if r['pearson_r'] is not None:
                i, j = columns.index(r['x']), columns.index(r['y'])
                matrix[i, j] = matrix[j, i] = r['pearson_r']
        fig, axis = plt.subplots(figsize=(max(5, len(columns)), max(4, len(columns))))
        image = axis.imshow(np.ma.masked_invalid(matrix), cmap='BrBG', vmin=-1, vmax=1)
        axis.set_xticks(range(len(columns)), columns, rotation=35, ha='right')
        axis.set_yticks(range(len(columns)), columns)
        fig.colorbar(image, ax=axis, label='Pearson r')
        fig.tight_layout()
        fig.savefig(output / 'correlation.png')
        plt.close(fig)
    (output / 'environment.json').write_text(json.dumps({'python': platform.python_version(),
        'packages': {p: importlib.metadata.version(p) for p in ['numpy', 'matplotlib']}}, indent=2), encoding='utf-8')
    report = '# 数据分析记录\n\n## 实际处理\n\n' + '\n'.join(f'- {k}：{v}' for k, v in audit.items())
    report += '\n\n## 描述统计\n\n' + '\n'.join(f'- {r["column"]}：有效n={r["count"]}，均值={r["mean"]}，样本标准差={r["std"]}' for r in summaries)
    report += '\n\n## 解释范围\n\n' + '\n'.join('- ' + note for note in result['notes'])
    (output / 'analysis.md').write_text(report + '\n', encoding='utf-8')
    print('已生成实际统计、图表和处理记录。', flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.plan).read_text(encoding='utf-8'))
    analyze(args.input, config.get('plan', config), args.output)
