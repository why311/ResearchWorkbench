"""Editable Word export from an already generated report's saved state."""
import io
import math
import re
from .report_text import body_markdown

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from latex2mathml.converter import convert as latex_to_mathml
from markdown_it import MarkdownIt
from mathml2omml import convert as mathml_to_omml


def math_rule(state, silent):
    position = state.pos
    marker = next((m for m in ('$$', r'\[', r'\(', '$') if state.src.startswith(m, position)), None)
    if not marker:
        return False
    closing = {r'\[': r'\]', r'\(': r'\)'}.get(marker, marker)
    end = state.src.find(closing, position + len(marker))
    if end < 0 or end == position + len(marker):
        return False
    if not silent:
        token = state.push('word_math', '', 0)
        token.content = state.src[position + len(marker):end]
        token.meta = {'display': marker in ('$$', r'\[')}
    state.pos = end + len(closing)
    return True


def add_math(paragraph, value):
    if len(value) > 4000:
        raise ValueError('单条公式超过4000字符，请简化后导出Word')
    try:
        mathml = latex_to_mathml(value)
        xml = mathml_to_omml(mathml)
        # mathml2omml 0.0.2 closes accent properties with the parent tag.
        xml = re.sub(r'(<m:groupChrPr>.*?)</m:groupChr>', r'\1</m:groupChrPr>', xml, flags=re.S)
        node = parse_xml(xml.replace('<m:oMath>', '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">', 1))
        for group in list(node.iter(qn('m:groupChr'))):
            character = group.find('m:groupChrPr/m:chr', group.nsmap)
            if character is not None and character.get(qn('m:val')) == '\u00af':
                # Keep a mean's overline attached to its operand in Word.
                group.tag = qn('m:bar')
                properties = group.find(qn('m:groupChrPr'))
                properties.tag = qn('m:barPr')
                properties.remove(character)
        if re.search(r'\\[A-Za-z]+', ''.join(node.itertext())):
            raise ValueError('存在不支持的LaTeX命令')
        paragraph._p.append(node)
    except Exception as exc:
        raise ValueError('有公式未能转换为Word公式，请检查LaTeX语法或改写为文字说明') from exc


def inline(paragraph, tokens):
    bold, italic = False, False
    link = ''
    for token in tokens or []:
        if token.type == 'strong_open':
            bold = True
        elif token.type == 'strong_close':
            bold = False
        elif token.type == 'em_open':
            italic = True
        elif token.type == 'em_close':
            italic = False
        elif token.type == 'link_open':
            link = token.attrGet('href') or ''
        elif token.type == 'link_close':
            if link:
                paragraph.add_run(' (' + link + ')')
            link = ''
        elif token.type == 'word_math':
            add_math(paragraph, token.content)
        elif token.type == 'image':
            paragraph.add_run('[未嵌入外部图片：' + (token.content or '无说明') + ']')
        elif token.type in {'softbreak', 'hardbreak'}:
            paragraph.add_run().add_break()
        elif token.type in {'text', 'code_inline', 'html_inline'}:
            run = paragraph.add_run(token.content)
            run.bold, run.italic = bold, italic
            if token.type == 'code_inline':
                run.font.name = 'Consolas'
                run.font.size = Pt(10)


def table(document, headings, rows, widths=None, school=False):
    if not 1 <= len(headings) <= 8:
        raise ValueError('Word表格需为1—8列，请拆分较宽的表格')
    result = document.add_table(rows=1, cols=len(headings))
    result.autofit = False
    section = document.sections[-1]
    available = (section.page_width-section.left_margin-section.right_margin)/914400
    widths = widths or [available / len(headings)] * len(headings)
    if sum(widths) > available:
        widths = [w * available/sum(widths) for w in widths]
    for column, width in zip(result.columns, widths):
        column.width = Inches(width)
    properties = result._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        border = OxmlElement('w:' + side)
        for name, value in [('val', 'single' if not school or side in {'top','bottom'} else 'nil'), ('sz', '12' if school else '4'), ('color', '000000' if school else 'D9D9D9')]:
            border.set(qn('w:' + name), value)
        borders.append(border)
    properties.append(borders)
    for index, values in enumerate([headings, *rows]):
        row = result.rows[0] if index == 0 else result.add_row()
        if index == 0:
            row._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
        for column, cell in enumerate(row.cells):
            cell.width = Inches(widths[column])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            margin = OxmlElement('w:tcMar')
            for name in ('top', 'left', 'bottom', 'right'):
                edge = OxmlElement('w:' + name)
                edge.set(qn('w:w'), '100'); edge.set(qn('w:type'), 'dxa'); margin.append(edge)
            cell._tc.get_or_add_tcPr().append(margin)
            if index == 0 and not school:
                fill = OxmlElement('w:shd'); fill.set(qn('w:fill'), 'E8EEF8'); cell._tc.get_or_add_tcPr().append(fill)
            if index == 0 and school:
                lines = OxmlElement('w:tcBorders'); line = OxmlElement('w:bottom'); line.set(qn('w:val'),'single'); line.set(qn('w:sz'),'8'); lines.append(line); cell._tc.get_or_add_tcPr().append(lines)
            paragraph = cell.paragraphs[0]
            if school:
                paragraph.paragraph_format.first_line_indent = Pt(0)
                paragraph.paragraph_format.left_indent = Pt(0)
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if index == 0 else WD_ALIGN_PARAGRAPH.LEFT
            paragraph.paragraph_format.space_after = Pt(3)
            paragraph.paragraph_format.space_before = Pt(3)
            value = values[column] if column < len(values) else ''
            if isinstance(value, list):
                inline(paragraph, value)
            else:
                paragraph.add_run(str(value))
            for run in paragraph.runs:
                run.font.size = Pt(10.5)
                if index == 0:
                    run.bold = True
    document.add_paragraph().paragraph_format.space_after = Pt(2)
    return result


def markdown(document, text, school=False):
    parser = MarkdownIt('commonmark', {'html': False}).enable('table')
    parser.inline.ruler.before('escape', 'word_math', math_rule)
    tokens = parser.parse(text)
    paragraph, lists, first, quote_depth = None, [], False, 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == 'table_open':
            rows, row = [], []
            while index + 1 < len(tokens):
                index += 1
                item = tokens[index]
                if item.type == 'tr_open':
                    row = []
                elif item.type == 'inline':
                    row.append(item.children or [])
                elif item.type == 'tr_close':
                    rows.append(row)
                elif item.type == 'table_close':
                    break
            if rows:
                table(document, rows[0], rows[1:], school=school)
        elif token.type == 'heading_open':
            paragraph = document.add_heading('', min(int(token.tag[1:]), 4))
        elif token.type in {'bullet_list_open', 'ordered_list_open'}:
            lists.append({'kind': token.type, 'number': int(token.attrGet('start') or 1)})
        elif token.type in {'bullet_list_close', 'ordered_list_close'}:
            lists.pop()
        elif token.type == 'list_item_open':
            first = True
        elif token.type == 'blockquote_open':
            quote_depth += 1
        elif token.type == 'blockquote_close':
            quote_depth -= 1
        elif token.type == 'paragraph_open':
            style = 'List Bullet' if lists and first and lists[-1]['kind'] == 'bullet_list_open' else None
            missing_bullet_style = style and style not in document.styles
            if missing_bullet_style:
                style = None
            paragraph = document.add_paragraph(style=style)
            if missing_bullet_style:
                paragraph.add_run('• ')
            if lists and first and lists[-1]['kind'] == 'ordered_list_open':
                paragraph.add_run(str(lists[-1]['number']) + '. ')
                lists[-1]['number'] += 1
            if lists or quote_depth:
                paragraph.paragraph_format.left_indent = Inches(.2 * (len(lists) + quote_depth))
            first = False
        elif token.type == 'inline' and paragraph is not None:
            inline(paragraph, token.children)
        elif token.type in {'fence', 'code_block'}:
            document.add_paragraph(token.content.rstrip(), 'Code Block')
        elif token.type == 'hr':
            document.add_paragraph()
        index += 1


def export_word(state, version, created, template_path=None):
    if template_path:
        from copy import deepcopy
        doc = Document(template_path)
        body_section = next((s for s in doc.sections if '绪论' in ''.join(p.text for p in s.header.paragraphs)), doc.sections[0])
        properties = deepcopy(body_section._sectPr)
        for child in list(doc._element.body):
            doc._element.body.remove(child)
        doc._element.body.append(properties)
        section = doc.sections[0]
        page_numbering = section._sectPr.find(qn('w:pgNumType'))
        if page_numbering is None:
            page_numbering = OxmlElement('w:pgNumType'); section._sectPr.append(page_numbering)
        page_numbering.set(qn('w:fmt'), 'decimal'); page_numbering.set(qn('w:start'), '1')
        normal = doc.styles['Normal']
        if 'Title' not in doc.styles:
            title = doc.styles.add_style('Title', 1)
            title.base_style = doc.styles['Heading 1']
            properties = title.element.get_or_add_pPr()
            numbering = OxmlElement('w:numPr'); number = OxmlElement('w:numId'); number.set(qn('w:val'), '0'); numbering.append(number); properties.append(numbering)
            level = OxmlElement('w:outlineLvl'); level.set(qn('w:val'), '9'); properties.append(level)
    else:
        doc = Document()
        section = doc.sections[0]
        section.page_width, section.page_height = Inches(8.5), Inches(11)
        section.left_margin = section.right_margin = Inches(.8)
        section.top_margin = section.bottom_margin = Inches(.75)
        normal = doc.styles['Normal']
        normal.font.name, normal.font.size = 'Calibri', Pt(11.5)
        normal._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
        normal.paragraph_format.line_spacing = 1.35
        normal.paragraph_format.space_after = Pt(7)
        title_properties = doc.styles['Title']._element.find(qn('w:pPr'))
        for border in list(title_properties.findall(qn('w:pBdr'))) if title_properties is not None else []:
            title_properties.remove(border)
        for name, size in [('Title', 24), ('Subtitle', 11), ('Heading 1', 17), ('Heading 2', 14), ('Heading 3', 12), ('Heading 4', 11.5)]:
            style = doc.styles[name]
            style.font.name, style.font.size = 'Calibri', Pt(size)
            style.font.color.rgb = RGBColor(0, 0, 0)
            style._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
            style.paragraph_format.keep_with_next = True
            style.paragraph_format.space_before = Pt(14)
            style.paragraph_format.space_after = Pt(7)
    code = doc.styles['Code Block'] if 'Code Block' in doc.styles else doc.styles.add_style('Code Block', 1)
    code.base_style = normal
    code.font.name, code.font.size = 'Consolas', Pt(9.5)
    code.paragraph_format.line_spacing = 1.15
    header = section.header.paragraphs[0]
    if template_path:
        header.text = state['title']
    else:
        header.add_run('研舟 · 科研成果记录').font.size = Pt(9)
    footer = section.footer.paragraphs[0]
    if template_path:
        footer.clear()
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if not template_path:
        footer.add_run(f'第{version}版 · ')
    field = OxmlElement('w:fldSimple'); field.set(qn('w:instr'), 'PAGE'); footer._p.append(field)
    doc.add_heading(state['title'], 0)
    if not template_path:
        doc.add_paragraph(f'成果版本：{version}  |  生成时间：{created}', 'Subtitle')
    rendered = body_markdown(state)
    if template_path:
        levels = [len(m[1]) for m in re.finditer(r'^(#{1,6})\s+', rendered, re.M)]
        depth = min(levels, default=1)-1
        rendered = re.sub(r'^(#{1,6})(\s+)', lambda m: '#' * max(1,len(m[1])-depth) + m[2], rendered, flags=re.M)
        settings = doc.settings.element
        refresh = OxmlElement('w:updateFields'); refresh.set(qn('w:val'), 'true'); settings.append(refresh)
    markdown(doc, rendered, school=bool(template_path))
    if state.get('citations'):
        doc.add_heading('文献原文依据', 1)
        doc.add_paragraph('以下为作者选择的原文片段，保留来源以便核对；引用本身不表示原文支持作者的全部推断。')
        for citation in state['citations']:
            doc.add_heading(f'[{citation["number"]}] {citation["title"]} · 第{citation["page"]}页', 2)
            for line in citation['text'].splitlines():
                paragraph = doc.add_paragraph(line)
                paragraph.paragraph_format.left_indent = Inches(.2)
            doc.add_paragraph(f'文献编号：{citation["document_id"]}；原文片段：{citation["span_id"]}')
    if state['chart'] and state['chart_metrics']:
        import matplotlib.pyplot as plt
        from .analysis_runner import configure_plot
        configure_plot()
        doc.add_heading('结果图表', 1)
        doc.add_paragraph('横轴序号对应下表中的运行。缺失指标不补为零。')
        table(doc, ['序号', '来源运行'], [[i + 1, r['name']] for i, r in enumerate(state['chart'])], [.6, 6.3], school=bool(template_path))
        for metric in state['chart_metrics']:
            data = [(i + 1, r['metrics'].get(metric)) for i, r in enumerate(state['chart']) if type(r['metrics'].get(metric)) in (int, float) and math.isfinite(r['metrics'][metric])]
            if not data:
                continue
            image = io.BytesIO()
            fig, axis = plt.subplots(figsize=(6.8, 2.8))
            try:
                axis.bar([str(n) for n, _ in data], [v for _, v in data], color='#4265bc')
                axis.set_title(metric); axis.set_xlabel('运行序号')
                fig.tight_layout(); fig.savefig(image, format='png', dpi=160)
            finally:
                plt.close(fig)
            caption = doc.add_paragraph('图：' + metric)
            caption.paragraph_format.keep_with_next = True
            image.seek(0); doc.add_picture(image, width=Inches(min(6.8,(section.page_width-section.left_margin-section.right_margin)/914400)))
    doc.add_heading('指标与来源说明', 1)
    doc.add_paragraph('以下数据属于本成果生成时保存的版本。后续草稿或引用修改不会改变本文件中的历史数值。解释与结论由作者核对，数值差异不自动证明因果或统计显著性。')
    if state['bindings']:
        table(doc, ['变量', '显示值', '指标'], [[b['alias'], b['formatted'], b['metric']] for b in state['bindings']], [1.8, 1.4, 3.7], school=bool(template_path))
    sources = {b['run_id']: {'name': b['run_name'], 'config': b['source_config'], 'created': b['source_created']} for b in state['bindings']}
    sources.update({r['id']: r for r in state['chart']})
    for index, (rid, run) in enumerate(sources.items(), 1):
        doc.add_heading(f'{index}. {run["name"]}', 2)
        doc.add_paragraph('运行编号：' + rid)
        doc.add_paragraph('运行时间：' + run['created'])
        import json
        doc.add_paragraph('实际配置：' + json.dumps(run['config'], ensure_ascii=False, indent=2), 'Code Block')
    if not sources:
        doc.add_paragraph('本文未绑定实验或分析指标。')
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()
