import os
import re
import logging
from typing import TypedDict, Dict, Any, List, Optional
from langgraph.graph import StateGraph, END

from pipeline.llm_manager import LLMManager
from pipeline.pdf_compiler.schemas import (
    LayoutStrategy,
    DocumentMetrics,
    TableMetric,
    MarginsConfig
)

logger = logging.getLogger("PDFCompiler.AnalyzerGraph")


class PDFCompilerState(TypedDict):
    md_paths: List[str]
    raw_texts: List[str]
    metrics: Dict[str, Any]
    layout_strategy: Dict[str, Any]
    merged_markdown: str


class MDLayoutOptimizerGraph:
    """LangGraph workflow that analyzes Markdown documents, extracts structural metrics,
    and uses LLM + Pydantic to determine the optimal PDF layout and space-saving strategy."""

    def __init__(self, temperature: float = 0.0):
        self.temperature = temperature
        self._llm_manager = None
        self.workflow = StateGraph(PDFCompilerState)
        self._build_graph()

    @property
    def llm_manager(self) -> LLMManager:
        if self._llm_manager is None:
            self._llm_manager = LLMManager(temperature=self.temperature)
        return self._llm_manager

    def _build_graph(self):
        self.workflow.add_node("extract_metrics", self.extract_metrics_node)
        self.workflow.add_node("analyze_layout", self.analyze_layout_node)
        self.workflow.add_node("merge_markdown", self.merge_markdown_node)

        self.workflow.set_entry_point("extract_metrics")
        self.workflow.add_edge("extract_metrics", "analyze_layout")
        self.workflow.add_edge("analyze_layout", "merge_markdown")
        self.workflow.add_edge("merge_markdown", END)

        self.app = self.workflow.compile()

    def extract_metrics_node(self, state: PDFCompilerState) -> Dict[str, Any]:
        """Node 1: Inspects the raw markdown contents and calculates structural metrics."""
        raw_texts = state.get("raw_texts", [])
        md_paths = state.get("md_paths", [])

        if not raw_texts and md_paths:
            raw_texts = []
            for path in md_paths:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        raw_texts.append(f.read())

        combined_text = "\n\n".join(raw_texts)
        words = combined_text.split()
        total_words = len(words)
        total_chars = len(combined_text)

        # Detect tables
        tables = self._extract_table_metrics(combined_text)
        max_cols = max([t.column_count for t in tables], default=0)
        has_wide = any(t.is_wide for t in tables)

        # Count callouts and headings
        callouts_count = len(re.findall(r'(?i)> \[!(NOTE|WARNING|IMPORTANT|TIP|CAUTION|question)\]', combined_text))
        headings_count = len(re.findall(r'(?m)^#{1,4}\s+', combined_text))

        # Infer title
        inferred_title = self._infer_document_title(raw_texts, md_paths)

        metrics = DocumentMetrics(
            total_files=len(raw_texts),
            file_names=[os.path.basename(p) for p in md_paths] if md_paths else [f"doc_{i+1}.md" for i in range(len(raw_texts))],
            total_words=total_words,
            total_characters=total_chars,
            total_tables=len(tables),
            max_table_columns=max_cols,
            has_wide_tables=has_wide,
            tables=tables,
            callouts_count=callouts_count,
            headings_count=headings_count,
            inferred_title=inferred_title
        )

        logger.info(
            f"Extracted metrics: {total_words} words, {len(tables)} tables (max {max_cols} cols), wide={has_wide}."
        )

        return {
            "raw_texts": raw_texts,
            "metrics": metrics.model_dump()
        }

    def analyze_layout_node(self, state: PDFCompilerState) -> Dict[str, Any]:
        """Node 2: Determines the optimal LayoutStrategy via LLM structured output or heuristic fallback."""
        metrics_dict = state["metrics"]
        metrics = DocumentMetrics(**metrics_dict)
        raw_texts = state.get("raw_texts", [])
        sample_snippet = ("\n\n".join(raw_texts))[:1200]

        layout = None
        try:
            structured_llm = self.llm_manager.llm.with_structured_output(LayoutStrategy)
            prompt = (
                "Eres un diseñador editorial y maquetador de documentos médicos y apuntes EIR de alta densidad.\n"
                "Tu objetivo es OPTIMIZAR EL ESPACIO AL MÁXIMO en un PDF para estudiar, reduciendo el número total de páginas "
                "sin perder legibilidad.\n\n"
                f"--- MÉTRICAS DEL DOCUMENTO ---\n"
                f"- Título inferido: {metrics.inferred_title}\n"
                f"- Total de palabras: {metrics.total_words}\n"
                f"- Total de tablas: {metrics.total_tables}\n"
                f"- Máximo de columnas en una tabla: {metrics.max_table_columns}\n"
                f"- Contiene tablas anchas: {metrics.has_wide_tables}\n"
                f"- Total de avisos/callouts: {metrics.callouts_count}\n"
                f"- Total de encabezados: {metrics.headings_count}\n\n"
                f"--- MUESTRA DEL CONTENIDO ---\n{sample_snippet}\n\n"
                "--- REGLAS CRÍTICAS DE DECISIÓN ---\n"
                "1. Orientación:\n"
                "   - 'landscape' (horizontal): Si hay tablas con 5 o más columnas o tablas comparativas muy anchas que desbordarían en vertical.\n"
                "   - 'portrait' (vertical): Si el texto es principalmente listas, párrafos y tablas compactas (≤ 4 columnas).\n"
                "2. Columnas:\n"
                "   - 2 columnas: Ideal en 'portrait' si el texto tiene muchas viñetas y pocas tablas anchas (ahorra hasta un 40% de espacio vertical).\n"
                "   - 1 columna: Si está en 'landscape' con tablas anchas o tablas complejas que ocupan todo el ancho.\n"
                "3. Márgenes: Usa márgenes estrechos pero imprimibles (6 a 8 mm) para maximizar la superficie útil.\n"
                "4. Tipografía: Tamaño base compacto (8.0 a 8.5 pt) y tablas a 7.0 - 7.5 pt.\n"
                "5. Justificación: Explica detalladamente por qué se elige horizontal/vertical y cómo se optimiza el espacio."
            )
            result = structured_llm.invoke(prompt)
            if isinstance(result, LayoutStrategy):
                layout = result
            elif isinstance(result, dict):
                layout = LayoutStrategy(**result)
            logger.info("LLM structured layout analysis succeeded.")
        except Exception as e:
            logger.warning(f"LLM structured analysis failed, using deterministic heuristics: {e}")
            layout = self._heuristic_layout_strategy(metrics)

        if not layout:
            layout = self._heuristic_layout_strategy(metrics)

        return {"layout_strategy": layout.model_dump()}

    def merge_markdown_node(self, state: PDFCompilerState) -> Dict[str, Any]:
        """Node 3: Cleans frontmatters, merges markdown texts, and normalizes headers."""
        raw_texts = state.get("raw_texts", [])
        metrics_dict = state.get("metrics", {})
        title = state.get("layout_strategy", {}).get("title", metrics_dict.get("inferred_title", "Compendio"))

        cleaned_docs = []
        for idx, text in enumerate(raw_texts):
            doc = text.strip()
            # Strip YAML frontmatter if present
            if doc.startswith("---"):
                parts = doc.split("---", 2)
                if len(parts) >= 3:
                    doc = parts[2].strip()

            if doc:
                cleaned_docs.append(doc)

        merged = "\n\n<div class=\"document-separator\"></div>\n\n".join(cleaned_docs)
        return {"merged_markdown": merged}

    def _extract_table_metrics(self, text: str) -> List[TableMetric]:
        """Parses markdown tables and measures column counts and width complexity."""
        tables = []
        lines = text.splitlines()
        i = 0
        table_idx = 0

        while i < len(lines):
            line = lines[i].strip()
            # Check if line looks like table header
            if line.startswith("|") and line.endswith("|") and i + 1 < len(lines):
                delimiter_line = lines[i + 1].strip()
                if re.match(r'^\|[\s:\-]+\|', delimiter_line):
                    headers = [c.strip() for c in line.strip("|").split("|")]
                    col_count = len(headers)
                    # Count rows and find max cell chars
                    row_idx = i + 2
                    rows_count = 0
                    max_chars = max([len(h) for h in headers], default=0)

                    while row_idx < len(lines) and lines[row_idx].strip().startswith("|"):
                        cell_line = lines[row_idx].strip().strip("|")
                        cells = [c.strip() for c in cell_line.split("|")]
                        for c in cells:
                            if len(c) > max_chars:
                                max_chars = len(c)
                        rows_count += 1
                        row_idx += 1

                    is_wide = col_count >= 5 or (col_count >= 4 and max_chars > 35) or (col_count * max_chars > 120)

                    tables.append(TableMetric(
                        table_index=table_idx,
                        column_count=col_count,
                        headers=headers,
                        max_cell_chars=max_chars,
                        estimated_row_count=rows_count,
                        is_wide=is_wide
                    ))
                    table_idx += 1
                    i = row_idx
                    continue
            i += 1

        return tables

    def _infer_document_title(self, raw_texts: List[str], md_paths: List[str]) -> str:
        """Infers a representative title for the compiled compendium."""
        # 1. Search for first H1 header '# Title'
        for text in raw_texts:
            match = re.search(r'(?m)^#\s+([^#\n]+)$', text)
            if match:
                clean_title = match.group(1).strip()
                # If multiple files, make it a compendium
                if len(raw_texts) > 1:
                    return f"Compendio: {clean_title} y temas afines"
                return clean_title

        # 2. Search for YAML title
        for text in raw_texts:
            match = re.search(r'(?m)^title:\s*["\']?([^"\'\n]+)["\']?', text)
            if match:
                return match.group(1).strip()

        # 3. Fallback to file name
        if md_paths:
            base = os.path.splitext(os.path.basename(md_paths[0]))[0]
            clean = re.sub(r'^\d{8}_\d{4}_?', '', base).replace('_', ' ').capitalize()
            return f"Apuntes de {clean}" if clean else "Compendio de Apuntes"

        return "Compendio de Apuntes de Estudio"

    def _heuristic_layout_strategy(self, metrics: DocumentMetrics) -> LayoutStrategy:
        """Deterministic rule-based layout analyzer used when LLM is unavailable or as fast baseline."""
        margins = MarginsConfig(top_mm=6.5, bottom_mm=6.5, left_mm=7.0, right_mm=7.0)

        if metrics.has_wide_tables or metrics.max_table_columns >= 5:
            # Wide tables need landscape to avoid horizontal scrolling or cutoffs
            orientation = "landscape"
            columns = 1
            font_size = 8.5
            table_font_size = 7.2
            table_strategy = "compact_fit"
            justification = (
                f"Se selecciona orientación HORIZONTAL (Landscape) porque el documento contiene {metrics.total_tables} tabla(s) "
                f"con hasta {metrics.max_table_columns} columnas de información médica densa. "
                "La orientación horizontal ofrece 297mm de ancho de página, evitando que las celdas se compriman excesivamente "
                "o que las filas alcancen alturas desproporcionadas."
            )
            tips = [
                "Orientación horizontal para visualización continua de tablas sin cortes",
                "Tipografía de tablas a 7.2pt con padding ultra-compacto (2.5px)",
                "Márgenes reducidos a 6.5mm / 7.0mm para maximizar área imprimible"
            ]
        else:
            # Narrative / bullet text fits well in portrait
            orientation = "portrait"
            if metrics.total_words > 1200:
                # 2-column layout saves 35-40% vertical space on lists and text
                columns = 2
                table_strategy = "full_width_span"
                justification = (
                    "Se selecciona orientación VERTICAL (Portrait) con diseño a 2 COLUMNAS de alta densidad. "
                    "Para apuntes con listas viñeteadas y texto explicativo, las dos columnas aprovechan los espacios "
                    "en blanco laterales ahorrando hasta un 35% de páginas totales. Las tablas intermedias se expanden "
                    "al ancho completo (span-all) para mantener máxima legibilidad."
                )
                tips = [
                    "Diseño periodístico a 2 columnas para comprimir listas y apuntes",
                    "Expansión automática de tablas a ancho completo entre columnas",
                    "Márgenes ajustados a 7.0mm"
                ]
            else:
                columns = 1
                table_strategy = "compact_fit"
                justification = (
                    "Se selecciona orientación VERTICAL (Portrait) a 1 columna debido a la longitud moderada del documento, "
                    "manteniendo una estructura limpia y márgenes compactos de 7mm."
                )
                tips = [
                    "Diseño vertical estándar con márgenes de alta densidad (7mm)",
                    "Espaciado interlineal compacto (1.22) para máxima condensación"
                ]

            font_size = 8.5
            table_font_size = 7.5

        return LayoutStrategy(
            orientation=orientation,
            columns=columns,
            font_size_pt=font_size,
            table_font_size_pt=table_font_size,
            line_height=1.24,
            margins_mm=margins,
            table_strategy=table_strategy,
            title=metrics.inferred_title,
            theme="clinical_compact",
            space_saving_tips=tips,
            justification=justification
        )

    def run(self, md_paths: List[str] = None, raw_texts: List[str] = None) -> Dict[str, Any]:
        """Executes the graph workflow and returns the final state."""
        initial_state = {
            "md_paths": md_paths or [],
            "raw_texts": raw_texts or [],
            "metrics": {},
            "layout_strategy": {},
            "merged_markdown": ""
        }
        return self.app.invoke(initial_state)
