import re
import logging
from markdown_it import MarkdownIt
from pipeline.pdf_compiler.schemas import LayoutStrategy

logger = logging.getLogger("PDFCompiler.HTMLGenerator")


class HTMLGenerator:
    """Transforms merged Markdown into high-density, beautifully styled HTML
    configured specifically for headless Chrome PDF generation."""

    def __init__(self):
        self.md_parser = MarkdownIt().disable("linkify").enable("table")

    def generate(self, markdown_text: str, strategy: LayoutStrategy) -> str:
        """Generates standalone HTML with custom CSS according to LayoutStrategy."""
        from pipeline.pdf_compiler.md_utils import preprocess_markdown
        raw_html = self.md_parser.render(preprocess_markdown(markdown_text))
        processed_html = self._post_process_html(raw_html, strategy)
        css = self._build_css(strategy)

        font_label = "NORMAL" if strategy.font_size_preset == "normal" else ("SUPER PEQUEÑA" if strategy.font_size_preset == "ultra_small" else "PEQUEÑA")
        full_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{strategy.title}</title>
<style>
{css}
</style>
</head>
<body>
<div class="document-header">
    <div class="header-title">{strategy.title}</div>
    <div class="header-badge">{strategy.orientation.upper()} · {strategy.columns} COL · LETRA {font_label}</div>
</div>
<div class="content-container">
{processed_html}
</div>
</body>
</html>"""
        return full_html

    def _post_process_html(self, html_content: str, strategy: LayoutStrategy) -> str:
        """Transforms blockquotes into Obsidian-style callouts and adds classes to tables."""
        # 1. Transform Obsidian Callouts
        callout_pattern = r'<blockquote>\s*<p>\[!(IMPORTANT|WARNING|NOTE|TIP|CAUTION|question)\](?:\s*<br\s*/?>)?\s*(.*?)</p>\s*(.*?)</blockquote>'

        def callout_replacer(match):
            c_type = match.group(1).lower()
            first_line = match.group(2).strip()
            rest = match.group(3).strip()

            icon_titles = {
                "important": ("📌", "Punto Crítico / Importante"),
                "warning": ("⚠️", "Advertencia / Ojo EIR"),
                "note": ("📝", "Nota Técnica"),
                "tip": ("💡", "Consejo de Estudio"),
                "caution": ("🛑", "Precaución Clínica"),
                "question": ("❓", "Autoevaluación (Active Recall)")
            }
            icon, default_title = icon_titles.get(c_type, ("ℹ️", c_type.capitalize()))

            # If first line contains a custom title (e.g. **Ojo con X**)
            title_text = default_title
            body_first = first_line
            if first_line.startswith("<strong>") and "</strong>" in first_line:
                title_match = re.match(r'^<strong>(.*?)</strong>:?\s*(.*)$', first_line)
                if title_match:
                    title_text = title_match.group(1)
                    body_first = title_match.group(2)

            body_content = ""
            if body_first:
                body_content += f"<p>{body_first}</p>"
            if rest:
                body_content += f"\n{rest}"

            return (
                f'<div class="callout callout-{c_type}">'
                f'<div class="callout-header"><span class="callout-icon">{icon}</span> {title_text}</div>'
                f'<div class="callout-body">{body_content}</div>'
                f'</div>'
            )

        html_content = re.sub(callout_pattern, callout_replacer, html_content, flags=re.DOTALL | re.IGNORECASE)

        # 2. Mark tables for full-width span if in multi-column mode
        def table_tagger(match):
            table_html = match.group(0)
            col_count = len(re.findall(r'<th\b', table_html))
            classes = ["content-table"]
            if strategy.columns > 1:
                if strategy.table_strategy == "full_width_span" or col_count >= 4:
                    classes.append("table-span-all")
            return f'<table class="{" ".join(classes)}">'

        html_content = re.sub(r'<table>', table_tagger, html_content)

        # 3. Style star tags (★, ★★) as highlighted badges
        # Single pass so '★★' is not re-matched by the '★' rule; swallow a literal "EIR" after the star(s)
        html_content = re.sub(
            r'(★{1,2})(?:\s*EIR\b)?',
            lambda m: ('<span class="star-badge double-star">★★ EIR</span>' if len(m.group(1)) == 2
                       else '<span class="star-badge single-star">★ EIR</span>'),
            html_content,
        )

        return html_content

    def _build_css(self, strategy: LayoutStrategy) -> str:
        """Builds CSS dynamically tuned to the Pydantic layout specification."""
        margins = strategy.margins_mm
        is_landscape = strategy.orientation == "landscape"
        page_size_str = "A4 landscape" if is_landscape else "A4 portrait"

        # Theme colors (clinical compact)
        primary_color = "#0f2b48"      # Deep medical navy
        secondary_color = "#1e40af"    # Clinical blue
        accent_color = "#2563eb"
        border_color = "#cbd5e1"
        bg_alt = "#f8fafc"
        text_color = "#1e293b"

        # Column configuration
        if strategy.columns > 1:
            column_css = f"""
            column-count: {strategy.columns};
            column-gap: 5.5mm;
            column-rule: 0.5px solid {border_color};
            """
        else:
            column_css = ""

        font_label = "NORMAL" if strategy.font_size_preset == "normal" else ("SUPER PEQUEÑA" if strategy.font_size_preset == "ultra_small" else "PEQUEÑA")
        h1_size = round(strategy.font_size_pt * 1.3, 1)
        h2_size = round(strategy.font_size_pt * 1.12, 1)
        h3_size = round(strategy.font_size_pt * 1.03, 1)

        css = f"""
        @page {{
            size: {page_size_str};
            margin-top: {margins.top_mm}mm;
            margin-bottom: {margins.bottom_mm}mm;
            margin-left: {margins.left_mm}mm;
            margin-right: {margins.right_mm}mm;
            @bottom-right {{
                content: "Página " counter(page);
                font-family: system-ui, -apple-system, sans-serif;
                font-size: 7pt;
                font-weight: 600;
                color: #64748b;
            }}
            @bottom-left {{
                content: "{strategy.title}";
                font-family: system-ui, -apple-system, sans-serif;
                font-size: 6.5pt;
                color: #94a3b8;
            }}
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-size: {strategy.font_size_pt}pt;
            line-height: {strategy.line_height};
            color: {text_color};
            margin: 0;
            padding: 0;
            text-rendering: optimizeLegibility;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}

        .document-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid {primary_color};
            padding-bottom: 3px;
            margin-bottom: 6px;
            column-span: all;
        }}

        .header-title {{
            font-size: 11pt;
            font-weight: 700;
            color: {primary_color};
            letter-spacing: -0.2px;
        }}

        .header-badge {{
            font-size: 6pt;
            font-weight: 700;
            background-color: #e2e8f0;
            color: #334155;
            padding: 2px 6px;
            border-radius: 3px;
            letter-spacing: 0.5px;
        }}

        .content-container {{
            {column_css}
            orphans: 2;
            widows: 2;
        }}

        h1 {{
            font-size: {h1_size}pt;
            color: {primary_color};
            margin: 6px 0 3px 0;
            border-bottom: 1.5px solid {accent_color};
            padding-bottom: 2px;
            break-after: avoid;
            page-break-after: avoid;
            break-inside: avoid;
            page-break-inside: avoid;
        }}

        h2 {{
            font-size: {h2_size}pt;
            color: {secondary_color};
            margin: 5px 0 2px 0;
            border-bottom: 0.5px solid {border_color};
            padding-bottom: 1px;
            break-after: avoid;
            page-break-after: avoid;
            break-inside: avoid;
            page-break-inside: avoid;
        }}

        h3 {{
            font-size: {h3_size}pt;
            color: #334155;
            margin: 4px 0 1px 0;
            break-after: avoid;
            page-break-after: avoid;
            break-inside: avoid;
            page-break-inside: avoid;
        }}

        pre {{
            white-space: pre-wrap;
            word-break: break-word;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 6.5pt;
            background-color: #f8fafc;
            border: 0.5px solid #cbd5e1;
            border-radius: 3px;
            padding: 3px 6px;
            margin: 3px 0 5px 0;
            break-inside: avoid;
            page-break-inside: avoid;
        }}

        code {{
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.9em;
        }}

        p {{
            margin: 0 0 3px 0;
            text-align: justify;
        }}

        ul, ol {{
            margin: 1px 0 3px 0;
            padding-left: 13px;
        }}

        li {{
            margin-bottom: 1.5px;
        }}

        li > p {{
            display: inline;
        }}

        /* High-density medical tables */
        table.content-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 4px 0 5px 0;
            font-size: {strategy.table_font_size_pt}pt;
            line-height: 1.15;
        }}

        /* Tables may flow across pages (avoids big blank gaps); rows stay whole and header repeats */
        table.content-table tr {{
            break-inside: avoid;
            page-break-inside: avoid;
        }}

        table.content-table thead {{
            display: table-header-group;
        }}

        table.table-span-all {{
            column-span: all;
        }}

        table.content-table th,
        table.content-table td {{
            border: 0.5px solid {border_color};
            padding: 2.2px 4.5px;
            text-align: left;
            vertical-align: top;
        }}

        table.content-table th {{
            background-color: {primary_color};
            color: #ffffff;
            font-weight: 600;
            letter-spacing: 0.2px;
        }}

        table.content-table tr:nth-child(even) {{
            background-color: {bg_alt};
        }}

        /* Obsidian Callouts */
        .callout {{
            border-left: 3px solid #3b82f6;
            background-color: #f0f7ff;
            padding: 3px 6px;
            margin: 4px 0;
            border-radius: 0 3px 3px 0;
            break-inside: avoid;
            page-break-inside: avoid;
            font-size: {strategy.font_size_pt * 0.95:.1f}pt;
        }}

        .callout-header {{
            font-weight: 700;
            color: #1e3a8a;
            margin-bottom: 2px;
            display: flex;
            align-items: center;
            gap: 4px;
        }}

        .callout-icon {{
            font-size: 8.5pt;
        }}

        .callout-body p {{
            margin: 0 0 2px 0;
        }}

        .callout-body p:last-child {{
            margin-bottom: 0;
        }}

        .callout-important {{
            border-left-color: #2563eb;
            background-color: #eff6ff;
        }}
        .callout-important .callout-header {{ color: #1e40af; }}

        .callout-warning {{
            border-left-color: #f59e0b;
            background-color: #fffbeb;
        }}
        .callout-warning .callout-header {{ color: #b45309; }}

        .callout-note {{
            border-left-color: #64748b;
            background-color: #f8fafc;
        }}
        .callout-note .callout-header {{ color: #334155; }}

        .callout-question {{
            border-left-color: #8b5cf6;
            background-color: #f5f3ff;
        }}
        .callout-question .callout-header {{ color: #6d28d9; }}

        /* Badges */
        .star-badge {{
            display: inline-block;
            font-size: 6.5pt;
            font-weight: 700;
            padding: 1px 4px;
            border-radius: 2px;
            margin: 0 2px;
            vertical-align: 1px;
        }}

        .star-badge.double-star {{
            background-color: #fef3c7;
            color: #92400e;
            border: 0.5px solid #f59e0b;
        }}

        .star-badge.single-star {{
            background-color: #e0f2fe;
            color: #0369a1;
            border: 0.5px solid #0284c7;
        }}

        .document-separator {{
            border-top: 1px dashed #94a3b8;
            margin: 8px 0;
            column-span: all;
        }}

        hr {{
            border: none;
            border-top: 0.5px solid {border_color};
            margin: 4px 0;
        }}
        """
        return css
