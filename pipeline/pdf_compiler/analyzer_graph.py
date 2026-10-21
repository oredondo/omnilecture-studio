import os
import re
import hashlib
from datetime import datetime
import logging
from typing import TypedDict, Dict, Any, List, Optional
from langgraph.graph import StateGraph, END

from pipeline.llm_manager import LLMManager
from pipeline.pdf_compiler.md_utils import preprocess_markdown
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
    organize: bool


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
        self.workflow.add_node("organize_content", self.organize_content_node)
        self.workflow.add_node("extract_metrics", self.extract_metrics_node)
        self.workflow.add_node("analyze_layout", self.analyze_layout_node)
        self.workflow.add_node("merge_markdown", self.merge_markdown_node)

        self.workflow.set_entry_point("organize_content")
        self.workflow.add_edge("organize_content", "extract_metrics")
        self.workflow.add_edge("extract_metrics", "analyze_layout")
        self.workflow.add_edge("analyze_layout", "merge_markdown")
        self.workflow.add_edge("merge_markdown", END)

        self.app = self.workflow.compile()

    @staticmethod
    def _strip_frontmatter(text: str) -> str:
        doc = text.strip()
        if doc.startswith("---"):
            parts = doc.split("---", 2)
            if len(parts) >= 3:
                doc = parts[2].strip()
        return doc

    @staticmethod
    def _word_set(text: str) -> set:
        return set(re.findall(r"\w+", text.lower()))

    def organize_content_node(self, state: PDFCompilerState) -> Dict[str, Any]:
        """Node 0: Joins all markdown files and, via LLM, gives them a coherent structure
        (title, sections, ordering) WITHOUT altering, removing or inventing information.
        Falls back to the plain concatenation if the LLM fails or loses content."""
        raw_texts = state.get("raw_texts", [])
        md_paths = state.get("md_paths", [])

        if not raw_texts and md_paths:
            raw_texts = []
            for path in md_paths:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        raw_texts.append(f.read())

        docs = [preprocess_markdown(self._strip_frontmatter(t)) for t in raw_texts]
        docs = [d for d in docs if d]
        if not docs:
            return {"raw_texts": raw_texts}

        joined = "\n\n".join(docs)
        if len(docs) == 1 and len(joined.split()) < 20:
            return {"raw_texts": [joined]}

        if not state.get("organize", False):
            logger.info("LLM organization disabled; using plain merge.")
            self._report("Organización con IA desactivada; uniendo archivos...", 0.85)
            return {"raw_texts": docs}

        chunks = self._chunk_docs(docs, self.ORGANIZE_CHUNK_WORDS)
        logger.info(f"Organizing content in {len(chunks)} block(s).")
        self._report(f"Organizando contenido: 0/{len(chunks)} bloques...", 0.0)

        # Headings of the ORIGINAL previous blocks are known upfront, so blocks can run in parallel.
        outlines: List[List[str]] = []
        acc: List[str] = []
        for chunk in chunks:
            outlines.append(list(acc))
            acc.extend(re.findall(r"(?m)^#{1,3}\s+.+$", chunk))

        llm = self.llm_manager.llm  # create once before spawning threads
        self._debug_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            ".temp", "pdf_debug", datetime.now().strftime("run_%Y%m%d_%H%M%S"),
        )
        done_count = [0]

        def work(idx: int) -> str:
            result = None
            try:
                result = self._organize_chunk(chunks[idx], idx, len(chunks), outlines[idx])
            except Exception as e:
                logger.warning(f"Block {idx + 1}/{len(chunks)} failed, keeping original text: {e}")
            done_count[0] += 1
            logger.info(f"Organize progress: {done_count[0]}/{len(chunks)} blocks finished.")
            self._report(f"Organizando contenido: {done_count[0]}/{len(chunks)} bloques...",
                         0.85 * done_count[0] / len(chunks))
            return result if result is not None else chunks[idx]

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.ORGANIZE_PARALLEL) as ex:
            organized_parts = list(ex.map(work, range(len(chunks))))

        # Debug files are only kept when some block was discarded; otherwise remove them.
        if os.path.isdir(self._debug_dir):
            logger.warning(f"Discarded blocks saved for inspection in: {self._debug_dir}")
        organized = "\n\n".join(organized_parts)
        return {"raw_texts": [organized]}

    ORGANIZE_PARALLEL = 7
    ORGANIZE_CHUNK_WORDS = 3500  # model: 98k ctx, 16k max output -> keep each block well inside both

    @staticmethod
    def _chunk_docs(docs: List[str], max_words: int) -> List[str]:
        """Splits documents (in order) into blocks of ~max_words, cutting at headings
        or blank lines so that no sentence/table is split."""
        pieces: List[str] = []
        for doc in docs:
            sections = re.split(r"(?m)^(?=#{1,3}\s)", doc)
            for sec in sections:
                if not sec.strip():
                    continue
                if len(sec.split()) <= max_words:
                    pieces.append(sec.strip())
                    continue
                buf: List[str] = []
                count = 0
                for para in re.split(r"\n\s*\n", sec):
                    w = len(para.split())
                    if buf and count + w > max_words:
                        pieces.append("\n\n".join(buf))
                        buf, count = [], 0
                    buf.append(para)
                    count += w
                if buf:
                    pieces.append("\n\n".join(buf))

        chunks: List[str] = []
        cur: List[str] = []
        count = 0
        for piece in pieces:
            w = len(piece.split())
            if cur and count + w > max_words:
                chunks.append("\n\n".join(cur))
                cur, count = [], 0
            cur.append(piece)
            count += w
        if cur:
            chunks.append("\n\n".join(cur))
        return chunks

    CACHE_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".temp", "pdf_cache",
    )

    @classmethod
    def _cache_path(cls, prompt: str) -> str:
        """Cache key = hash of the full prompt (rules + outline + block text) so any change invalidates it."""
        return os.path.join(cls.CACHE_DIR, hashlib.sha256(prompt.encode("utf-8")).hexdigest() + ".md")

    @staticmethod
    def _cache_read(path: str) -> Optional[str]:
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception:
            pass
        return None

    @classmethod
    def _cache_write(cls, path: str, content: str) -> None:
        try:
            os.makedirs(cls.CACHE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            logger.warning(f"Could not write block cache: {e}")

    def _save_debug_block(self, idx: int, original: str, llm_output: str, missing: set) -> None:
        """Stores a discarded block (original, LLM output, missing words) in a temp folder."""
        try:
            d = getattr(self, "_debug_dir", None)
            if not d:
                return
            os.makedirs(d, exist_ok=True)
            base = os.path.join(d, f"block_{idx + 1:02d}")
            with open(base + "_original.md", "w", encoding="utf-8") as f:
                f.write(original)
            with open(base + "_llm.md", "w", encoding="utf-8") as f:
                f.write(llm_output)
            with open(base + "_missing_words.txt", "w", encoding="utf-8") as f:
                f.write(f"{len(missing)} words missing in LLM output\n\n" + "\n".join(sorted(missing)))
        except Exception as e:
            logger.warning(f"Could not save debug block {idx + 1}: {e}")

    def _organize_chunk(self, chunk: str, idx: int, total: int, outline: List[str]) -> Optional[str]:
        """Organizes one block with the LLM. Returns None if the result loses information."""
        if len(chunk.split()) < 15:
            return None

        if idx == 0:
            title_rule = "Empieza con un único título general (#) para todo el material. "
        else:
            title_rule = ("NO pongas título general (#): este bloque continúa un documento ya iniciado; "
                          "usa ## y ### para las secciones. ")
        outline_txt = ""
        if outline:
            outline_txt = ("Encabezados ya usados en bloques anteriores (si el tema coincide, continúa esa sección "
                           "en vez de repetir el encabezado):\n" + "\n".join(outline[-60:]) + "\n\n")

        prompt = (
            "Eres un editor de apuntes de estudio. Recibes un fragmento (bloque "
            f"{idx + 1} de {total}) de un material en Markdown. Devuélvelo como Markdown bien formado, "
            "coherente y lo más COMPACTO posible para imprimir.\n\n"
            "REGLAS ESTRICTAS (información):\n"
            "1. NO elimines, resumas, reformules ni inventes información. Todo dato, cifra, nombre, definición, "
            "lista y tabla debe conservarse con sus palabras.\n"
            f"2. {title_rule}Crea/normaliza encabezados (##, ###), agrupa y reordena bloques del mismo tema "
            "y fusiona encabezados duplicados.\n"
            "3b. Si hay un 'Esquema Inicial del Tema' o esquema general, déjalo como lista con viñetas simple y corta "
            "(máx. 2 niveles); NUNCA uses diagramas mermaid ni bloques de código para esquemas.\n"
            "3. Mantén los callouts (> [!NOTE], etc.) en su sintaxis, pero no crees callouts nuevos decorativos.\n\n"
            "REGLAS DE AHORRO DE ESPACIO (sin perder datos):\n"
            "4. Convierte en tablas Markdown compactas las comparativas, clasificaciones, listas de elementos con "
            "los mismos atributos (p. ej. concepto | definición | ejemplo) y datos repetitivos. Máx. 5-6 columnas. "
            "Cada dato original debe quedar en alguna celda. No fuerces tablas donde no encajan.\n"
            "5. Solo une tablas consecutivas si tienen exactamente las mismas columnas y el resultado no supera ~20 filas; "
            "nunca crees tablas gigantes: divide las largas por subtemas.\n"
            "6. Listas muy cortas (elementos de 1-3 palabras) pueden ir en una sola línea separadas por ' · ' "
            "o ' | ' en lugar de una viñeta por línea.\n"
            "7. Elimina SOLO relleno de formato: líneas en blanco sobrantes, separadores (---), encabezados vacíos o "
            "que solo repiten el título de la tabla que sigue, numeraciones redundantes, negritas/emojis decorativos "
            "y frases de transición sin contenido (p. ej. 'A continuación se muestra la tabla'). "
            "Si un encabezado tiene un solo párrafo corto, intégralo en negrita en la sección superior.\n"
            "8. Evita anidar listas a más de 2 niveles; no dejes encabezados consecutivos sin contenido entre ellos.\n"
            "9. Responde SOLO con el Markdown final, sin explicaciones ni bloques ``` envolventes.\n\n"
            f"{outline_txt}--- BLOQUE {idx + 1}/{total} ---\n\n{chunk}"
        )
        cache_file = self._cache_path(prompt)
        cached = self._cache_read(cache_file)
        if cached is not None:
            logger.info(f"Block {idx + 1}/{total} loaded from cache.")
            return cached

        response = self.llm_manager.llm.invoke(prompt)
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
        content = str(content).strip()
        content = re.sub(r"^```(?:markdown|md)?\s*\n|\n```\s*$", "", content).strip()

        original_words = self._word_set(chunk)
        coverage = len(original_words & self._word_set(content)) / max(len(original_words), 1)
        if coverage < 0.97:
            self._save_debug_block(idx, chunk, content, original_words - self._word_set(content))
            logger.warning(f"Block {idx + 1}/{total} lost content (coverage {coverage:.1%}); keeping original.")
            return None
        self._cache_write(cache_file, content)
        logger.info(f"Block {idx + 1}/{total} organized (coverage {coverage:.1%}, "
                    f"{len(chunk.split())}->{len(content.split())} words).")
        return content

    def extract_metrics_node(self, state: PDFCompilerState) -> Dict[str, Any]:
        """Node 1: Inspects the raw markdown contents and calculates structural metrics."""
        self._report("Calculando métricas del documento...", 0.85)
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
        self._report("Analizando la maquetación óptima con el LLM...", 0.90)
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

    def _report(self, message: str, fraction: float) -> None:
        """Reports graph progress (fraction 0..1 of the whole graph) if a callback was given."""
        cb = getattr(self, "_progress_cb", None)
        if cb:
            try:
                cb(message, max(0.0, min(1.0, fraction)))
            except Exception:
                pass

    def run(self, md_paths: List[str] = None, raw_texts: List[str] = None,
            progress_callback=None, organize: bool = False) -> Dict[str, Any]:
        """Executes the graph workflow and returns the final state.

        progress_callback: optional callable(message: str, fraction: float 0..1)."""
        self._progress_cb = progress_callback
        initial_state = {
            "md_paths": md_paths or [],
            "raw_texts": raw_texts or [],
            "metrics": {},
            "layout_strategy": {},
            "merged_markdown": "",
            "organize": organize
        }
        return self.app.invoke(initial_state)
