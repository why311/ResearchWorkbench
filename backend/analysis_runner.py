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


def chart_sources(output, name, kind, labels, series, xlabel, numeric_x=None):
    """Write editable plots from the same processed values used in the PNG."""
    if not series or not labels:
        return
    escape = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '$': r'\$', '&': r'\&',
              '#': r'\#', '_': r'\_', '%': r'\%', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    def tex(value):
        return ''.join(escape.get(c, c) for c in ' '.join(str(value).split()))
    def mermaid_label(value):
        clean = ' '.join(str(value).split())
        return '"' + ''.join(c if c.isalnum() or c in ' .-_' else f'#{ord(c)};' for c in clean) + '"'
    def fmt(value):
        return format(value, '.15g')

    x = list(range(1, len(labels) + 1)) if numeric_x is None else numeric_x
    lines = [r'% In the preamble: \usepackage{pgfplots} \pgfplotsset{compat=1.18}',
             r'% Use XeLaTeX with xeCJK for Chinese labels.',
             r'\begin{tikzpicture}', r'\begin{axis}[unbounded coords=jump, xlabel={' + tex(xlabel) + '}']
    if kind == 'bar':
        lines[-1] += ', ybar, enlarge x limits=0.12'
    if numeric_x is None and len(labels) <= 60:
        lines[-1] += ', xtick={' + ','.join(map(str, x)) + '}, xticklabels={' + ','.join('{' + tex(v) + '}' for v in labels) + '}'
    lines[-1] += ']'
    for label, values in series:
        coordinates = ' '.join(f'({fmt(pos)},{fmt(value) if value is not None else "nan"})' for pos, value in zip(x, values))
        lines.extend([r'\addplot coordinates {' + coordinates + '};', r'\addlegendentry{' + tex(label) + '}'])
    lines.extend([r'\end{axis}', r'\end{tikzpicture}'])
    (output / (name + '.tex')).write_text('\n'.join(lines) + '\n', encoding='utf-8')

    # Mermaid's categorical XY chart needs one finite y per tick.
    # For irregular numeric x, missing values or long series, the TikZ file retains the full plot.
    complete = [(label, values) for label, values in series if all(value is not None for value in values)]
    intervals = {round(b - a, 9) for a, b in zip(x, x[1:])}
    if not complete or len(labels) > 60 or (numeric_x is not None and (len(intervals) > 1 or len(set(x)) != len(x))):
        return
    lines = ['xychart-beta', '    title ' + mermaid_label(name), '    x-axis ' + mermaid_label(xlabel) +
             ' [' + ', '.join(mermaid_label(v) for v in labels) + ']']
    for index, (label, values) in enumerate(complete, 1):
        lines.append(f'    %% {index}. ' + mermaid_label(label))
        lines.append('    ' + kind + ' [' + ', '.join(fmt(value) for value in values) + ']')
    (output / (name + '.mmd')).write_text('\n'.join(lines) + '\n', encoding='utf-8')


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
    if group_by and any(m in plan['methods'] for m in ('groups', 'radar', 'radar3d')):
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
    chart_sources(output, 'summary-count', 'bar', columns, [('Valid observations', [s['count'] for s in summaries])], 'Field')
    configure_plot()
    captions = {'distribution.png': f'清洗后共{len(rows)}行；各字段直方图仅包含有效数值，缺失不补零。' + ' '.join(f'{s["column"]}：n={s["count"]}，均值={s["mean"]}，范围[{s["min"]}, {s["max"]}]。' for s in summaries)}
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
        by_key = {(item['group'], item['column']): item['mean'] for item in grouped}
        for index, column in enumerate(columns, 1):
            chart_sources(output, f'group-means-{index}', 'bar', labels,
                          [(column, [by_key.get((label, column)) for label in labels])], group_by)
        captions['groups.png'] = f'按{group_by}分组后的有效样本均值；图示前{len(labels)}组，完整分组及样本数见groups.csv；未进行显著性检验。'
        for column in columns:
            values = [(label, by_key[label, column]) for label in labels if by_key.get((label, column)) is not None]
            if len(values) >= 2:
                low, high = min(values, key=lambda item: item[1]), max(values, key=lambda item: item[1])
                if low[1] != high[1]:
                    captions['groups.png'] += f'{column}的最低组均值为{low[0]}（{low[1]:.4g}），最高为{high[0]}（{high[1]:.4g}）。'
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
        captions['correlation.png'] = '按成对有效数值计算Pearson相关系数；常量与不足两对的组合留空，不代表因果。'
    if 'line' in plan['methods']:
        if len(rows) > 10000:
            raise ValueError('折线图超过10000行，请先筛选数据；未静默抽样。')
        x_column = plan.get('x_column', '')
        ordered = sorted((r for r in rows if r[x_column] is not None), key=lambda r: r[x_column]) if x_column else rows
        x = [r[x_column] for r in ordered] if x_column else list(range(1, len(ordered) + 1))
        fig, axes = plt.subplots(len(columns), 1, figsize=(8, max(3, 2.7 * len(columns))), squeeze=False)
        for axis, column in zip(axes[:, 0], columns):
            axis.plot(x, [np.nan if r[column] is None else r[column] for r in ordered], color='#4265bc', linewidth=1.2)
            axis.set_ylabel(column); axis.set_xlabel(x_column or '清洗后行号（原始顺序）')
        fig.tight_layout(); fig.savefig(output / 'line.png'); plt.close(fig)
        chart_sources(output, 'line', 'line', [str(value) for value in x],
                      [(column, [row[column] for row in ordered]) for column in columns],
                      x_column or 'Row', numeric_x=x)
        captions['line.png'] = f'横轴为{x_column or "清洗后原始行号"}，' + ('按横轴数值升序连接；' if x_column else '按数据原始顺序连接；') + f'共{len(ordered)}行，缺失数值使折线断开；连线不代表插值或时间因果。'
        for column in columns:
            values = [(pos, row[column]) for pos, row in zip(x, ordered) if row[column] is not None]
            if len(values) >= 2:
                first, last = values[0], values[-1]
                captions['line.png'] += (f'{column}由首个有效点（{first[0]:.4g}, {first[1]:.4g}）'
                                         f'到末个有效点（{last[0]:.4g}, {last[1]:.4g}）；'
                                         f'观测范围[{min(v for _, v in values):.4g}, {max(v for _, v in values):.4g}]。')
    if any(m in plan['methods'] for m in ('radar', 'radar3d')):
        if len(columns) < 3:
            raise ValueError('雷达图至少需要三个数值字段。')
        profiles = []
        labels = list(dict.fromkeys(s['group'] for s in grouped))[:8] if grouped else ['全部样本']
        for label in labels:
            statistics_for_group = {s['column']: s for s in grouped if s['group'] == label} if grouped else {s['column']: s for s in summaries}
            values = []
            for s in summaries:
                value = statistics_for_group.get(s['column'], {}).get('mean')
                values.append(np.nan if value is None else .5 if s['max'] == s['min'] else (value-s['min'])/(s['max']-s['min']))
            profiles.append((label, values))
        angles = np.linspace(0, 2*np.pi, len(columns), endpoint=False)
        closed = np.r_[angles, angles[0]]
        if 'radar' in plan['methods']:
            fig, axis = plt.subplots(figsize=(8, 6), subplot_kw={'projection': 'polar'})
            for label, values in profiles:
                axis.plot(closed, values + values[:1], label=label)
            axis.set_xticks(angles, columns); axis.set_ylim(0, 1); axis.legend(loc='upper right', bbox_to_anchor=(1.35, 1.15))
            fig.tight_layout(); fig.savefig(output / 'radar.png'); plt.close(fig)
        if 'radar3d' in plan['methods']:
            fig = plt.figure(figsize=(9, 7)); axis = fig.add_subplot(projection='3d')
            for level, (label, values) in enumerate(profiles):
                radius = np.asarray(values + values[:1])
                axis.plot(radius*np.cos(closed), radius*np.sin(closed), zs=level, label=label)
                for angle, column in zip(angles, columns):
                    axis.plot([0, np.cos(angle)], [0, np.sin(angle)], [level, level], color='#abb4c7', alpha=.45)
                    if level == 0: axis.text(1.12*np.cos(angle), 1.12*np.sin(angle), level, column, fontsize=9)
            axis.set_zlabel('分组层序（非数值指标）'); axis.set_zticks(range(len(labels)), labels); axis.set_xlim(-1.3,1.3); axis.set_ylim(-1.3,1.3)
            fig.tight_layout(); fig.savefig(output / 'radar3d.png'); plt.close(fig)
        caption = f'展示{len(labels)}组的字段均值，各字段按全部清洗后有效数值的最小值和最大值归一化；常量列置0.5，缺失不补零。半径不是优劣评分；3D高度仅区分分组，非第三项测量值。完整原始统计见summary.csv和groups.csv（如有）。'
        captions.update({name: caption for name, method in [('radar.png','radar'),('radar3d.png','radar3d')] if method in plan['methods']})
    result['captions'] = captions
    (output / 'captions.json').write_text(json.dumps(captions, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'environment.json').write_text(json.dumps({'python': platform.python_version(),
        'packages': {p: importlib.metadata.version(p) for p in ['numpy', 'matplotlib']}}, indent=2), encoding='utf-8')
    report = '# 数据分析记录\n\n## 实际处理\n\n' + '\n'.join(f'- {k}：{v}' for k, v in audit.items())
    report += '\n\n## 描述统计\n\n' + '\n'.join(f'- {r["column"]}：有效n={r["count"]}，均值={r["mean"]}，样本标准差={r["std"]}' for r in summaries)
    report += '\n\n## 解释范围\n\n' + '\n'.join('- ' + note for note in result['notes'])
    report += '\n\n## 图注\n\n' + '\n\n'.join(name + '：' + caption for name, caption in captions.items())
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
