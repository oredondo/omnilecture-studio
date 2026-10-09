import os
import glob
import logging
from typing import List, Tuple, Optional, Callable

import config
from pipeline.pdf_compiler.schemas import LayoutStrategy
from pipeline.pdf_compiler.analyzer_graph import MDLayoutOptimizerGraph
from pipeline.pdf_compiler.html_generator import HTMLGenerator
from pipeline.pdf_compiler.pdf_renderer import PDFRenderer

logger = logging.getLogger("PDFCompiler")


def compile_markdowns_to_pdf(
    md_sources: List[str] | str,
    output_pdf_path: Optional[str] = None,
    force_orientation: Optional[str] = None,
    force_columns: Optional[int] = None,
    font_size_mode: Optional[str] = None,
    status_callback: Optional[Callable[[str, float], None]] = None
) -> Tuple[str, LayoutStrategy]:
    """Compiles one or more Markdown files into an ultra-compact, space-optimized PDF.

    Args:
        md_sources: A single markdown file path, a directory containing .md files,
                    a glob pattern, or a list of markdown file paths.
        output_pdf_path: Destination path for the generated PDF. If None, saves in
                         the output directory or alongside the first input file.
        force_orientation: Optional override: 'portrait' or 'landscape'.
        force_columns: Optional override: 1 or 2 columns.
        font_size_mode: Optional font size preset: 'normal', 'small' (pequeña), or 'ultra_small' (super pequeña).
        status_callback: Optional progress reporter callback (message: str, progress: float).

    Returns:
        Tuple containing (path_to_generated_pdf, layout_strategy_used).
    """
    # 1. Resolve list of files
    valid_paths = []
    if isinstance(md_sources, str):
        if os.path.isdir(md_sources):
            valid_paths = sorted(glob.glob(os.path.join(md_sources, "*.md")))
        elif "*" in md_sources:
            valid_paths = sorted(glob.glob(md_sources))
        elif os.path.isfile(md_sources):
            valid_paths = [md_sources]
    elif isinstance(md_sources, (list, tuple)):
        for item in md_sources:
            if isinstance(item, str) and os.path.isfile(item) and item.endswith(".md"):
                valid_paths.append(item)

    if not valid_paths:
        raise FileNotFoundError(f"No se encontraron archivos .md válidos en la fuente: {md_sources}")

    logger.info(f"Starting PDF compilation for {len(valid_paths)} Markdown file(s)...")
    if status_callback:
        status_callback(
            f"Analizando {len(valid_paths)} documento(s) con LangGraph y Pydantic...",
            0.15
        )

    # 2. Run LangGraph layout analysis
    graph = MDLayoutOptimizerGraph()
    state = graph.run(md_paths=valid_paths)

    strategy_dict = state.get("layout_strategy", {})
    strategy = LayoutStrategy(**strategy_dict)

    # 3. Apply user overrides if specified
    if force_orientation in ("portrait", "landscape"):
        strategy.orientation = force_orientation
    if force_columns in (1, 2, 3):
        strategy.columns = force_columns
    if font_size_mode:
        strategy.apply_font_preset(font_size_mode)

    logger.info(
        f"Layout Strategy determined: orientation={strategy.orientation}, "
        f"columns={strategy.columns}, font_size={strategy.font_size_pt}pt. "
        f"Justification: {strategy.justification}"
    )

    if status_callback:
        status_callback(
            f"Estrategia ({strategy.orientation.upper()}, {strategy.columns} col). Generando HTML maquetado...",
            0.50
        )

    # 4. Generate High-Density HTML
    html_generator = HTMLGenerator()
    merged_md = state.get("merged_markdown", "")
    html_content = html_generator.generate(merged_md, strategy)

    # 5. Resolve output path
    if not output_pdf_path:
        first_base = os.path.splitext(os.path.basename(valid_paths[0]))[0]
        if len(valid_paths) > 1:
            pdf_filename = f"compendio_{first_base}_y_otros_optimizado.pdf"
        else:
            pdf_filename = f"{first_base}_optimizado.pdf"

        target_dir = getattr(config, "OUTPUT_DIR", None) or os.path.dirname(valid_paths[0])
        pdf_dir = os.path.join(target_dir, "apuntes_pdf")
        os.makedirs(pdf_dir, exist_ok=True)
        output_pdf_path = os.path.join(pdf_dir, pdf_filename)

    # 6. Render PDF
    if status_callback:
        status_callback("Renderizando PDF de alta densidad con Chromium...", 0.80)

    renderer = PDFRenderer()
    final_pdf_path = renderer.render_to_pdf(html_content, output_pdf_path)

    if status_callback:
        status_callback(
            f"¡PDF optimizado generado con éxito! ({os.path.basename(final_pdf_path)})",
            1.0
        )

    return final_pdf_path, strategy
