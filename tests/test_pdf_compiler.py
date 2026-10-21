import os
import sys
import tempfile
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from pipeline.pdf_compiler.schemas import (
    MarginsConfig,
    TableMetric,
    DocumentMetrics,
    LayoutStrategy
)
from pipeline.pdf_compiler.analyzer_graph import MDLayoutOptimizerGraph
from pipeline.pdf_compiler.html_generator import HTMLGenerator
from pipeline.pdf_compiler.compiler import compile_markdowns_to_pdf


class TestPDFCompilerSchemas:

    def test_margins_config_css_string(self):
        m = MarginsConfig(top_mm=6.0, bottom_mm=6.0, left_mm=8.0, right_mm=8.0)
        assert m.css_string == "6.0mm 8.0mm 6.0mm 8.0mm"

    def test_layout_strategy_validation(self):
        strategy = LayoutStrategy(
            orientation="landscape",
            columns=1,
            font_size_pt=8.5,
            table_font_size_pt=7.5,
            title="Compendio Test",
            justification="Tablas anchas presentes"
        )
        assert strategy.orientation == "landscape"
        assert strategy.columns == 1
        assert strategy.margins_mm.top_mm == 7.0

    def test_table_metric_wide_flag(self):
        narrow = TableMetric(
            table_index=0,
            column_count=2,
            headers=["Concepto", "Definición"],
            max_cell_chars=20,
            estimated_row_count=3,
            is_wide=False
        )
        assert narrow.is_wide is False

        wide = TableMetric(
            table_index=1,
            column_count=6,
            headers=["Enfermedad", "Agente", "Vector", "Prevención", "Síntomas", "Notificación"],
            max_cell_chars=120,
            estimated_row_count=5,
            is_wide=True
        )
        assert wide.is_wide is True

    def test_apply_font_presets(self):
        strategy = LayoutStrategy(
            orientation="portrait",
            columns=1,
            title="Test Presets",
            justification="Test"
        )
        # Default is small
        assert strategy.font_size_pt == 8.5
        assert strategy.table_font_size_pt == 7.5

        # Normal
        strategy.apply_font_preset("normal")
        assert strategy.font_size_pt == 9.5
        assert strategy.table_font_size_pt == 8.5
        assert strategy.line_height == 1.32
        assert strategy.font_size_preset == "normal"

        # Super pequeña / ultra_small
        strategy.apply_font_preset("super_pequeña")
        assert strategy.font_size_pt == 7.2
        assert strategy.table_font_size_pt == 6.4
        assert strategy.line_height == 1.15
        assert strategy.font_size_preset == "ultra_small"

        # Small / pequeña
        strategy.apply_font_preset("pequeña")
        assert strategy.font_size_pt == 8.5
        assert strategy.table_font_size_pt == 7.5
        assert strategy.line_height == 1.24
        assert strategy.font_size_preset == "small"


class TestMDLayoutOptimizerGraph:

    def test_extract_metrics_wide_table(self):
        graph = MDLayoutOptimizerGraph()
        md_text = """
# Estudio de Enfermedades

| Enfermedad | Agente Etiológico | Vector / Transmisión | Prevención | Síntomas | Notificación |
|---|---|---|---|---|---|
| Peste | Yersinia pestis | Pulga | Cuarentena | Bubones | EDO Urgente |
| Dengue | Flavivirus | Mosquito Aedes | Repelentes | Fiebre hemorrágica | Semanal |

> [!WARNING]
> Cuidado con la transmisión vectorial en zonas endémicas.
"""
        tables = graph._extract_table_metrics(md_text)
        assert len(tables) == 1
        assert tables[0].column_count == 6
        assert tables[0].is_wide is True

    def test_heuristic_landscape_for_wide_tables(self):
        graph = MDLayoutOptimizerGraph()
        metrics = DocumentMetrics(
            total_files=1,
            file_names=["test.md"],
            total_words=800,
            total_characters=5000,
            total_tables=1,
            max_table_columns=6,
            has_wide_tables=True,
            callouts_count=1,
            headings_count=2,
            inferred_title="Enfermedades Infecciosas"
        )
        strategy = graph._heuristic_layout_strategy(metrics)
        assert strategy.orientation == "landscape"
        assert strategy.columns == 1
        assert "HORIZONTAL" in strategy.justification

    def test_heuristic_portrait_multicol_for_dense_notes(self):
        graph = MDLayoutOptimizerGraph()
        metrics = DocumentMetrics(
            total_files=1,
            file_names=["test.md"],
            total_words=2000,
            total_characters=14000,
            total_tables=0,
            max_table_columns=0,
            has_wide_tables=False,
            callouts_count=3,
            headings_count=6,
            inferred_title="Metodología y Gestión"
        )
        strategy = graph._heuristic_layout_strategy(metrics)
        assert strategy.orientation == "portrait"
        assert strategy.columns == 2
        assert "2 COLUMNAS" in strategy.justification


class TestHTMLGenerator:

    def test_callout_transformation(self):
        gen = HTMLGenerator()
        strategy = LayoutStrategy(
            orientation="portrait",
            columns=1,
            title="Test Callouts",
            justification="Test"
        )
        md = "> [!IMPORTANT]\n> **Punto Crítico**: Datos de alta frecuencia."
        html = gen.generate(md, strategy)

        assert "callout-important" in html
        assert "Punto Crítico" in html
        assert "📌" in html

    def test_wide_table_tagging_in_multicolumn(self):
        gen = HTMLGenerator()
        strategy = LayoutStrategy(
            orientation="portrait",
            columns=2,
            table_strategy="full_width_span",
            title="Test Tables",
            justification="Test"
        )
        md = """
| Col1 | Col2 | Col3 | Col4 |
|---|---|---|---|
| A | B | C | D |
"""
        html = gen.generate(md, strategy)
        assert "table-span-all" in html

    def test_font_presets_styling(self):
        gen = HTMLGenerator()
        strategy = LayoutStrategy(
            orientation="portrait",
            columns=1,
            title="Test Typography",
            justification="Test"
        )
        strategy.apply_font_preset("ultra_small")
        html = gen.generate("# Título\nContenido de prueba.", strategy)
        assert "font-size: 7.2pt;" in html
        assert "font-size: 6.4pt;" in html
        assert "LETRA SUPER PEQUEÑA" in html


class TestPDFCompilerEndToEnd:

    def test_compile_single_and_multiple_markdowns(self):
        temp_dir = tempfile.mkdtemp()
        file1 = os.path.join(temp_dir, "doc1.md")
        file2 = os.path.join(temp_dir, "doc2.md")

        with open(file1, "w", encoding="utf-8") as f:
            f.write("""# Farmacología EIR

## 1. Antibióticos
* **Betalactámicos**: Inhiben la síntesis de pared celular bacteriana.
* **Macrólidos**: Inhiben subunidad ribosomal 50S.

> [!NOTE]
> Recordar que las penicilinas presentan hipersensibilidad cruzada con cefalosporinas (5-10%).
""")

        with open(file2, "w", encoding="utf-8") as f:
            f.write("""# Epidemiología y Zoonosis

| Patología | Agente | Vector |
|---|---|---|
| Lyme | Borrelia | Garrapata |
| Peste | Yersinia | Pulga |

* ★★ **Pregunta Repetida**: La pulga del roedor es Xenopsylla cheopis.
""")

        out_pdf = os.path.join(temp_dir, "compendio_test.pdf")
        pdf_path, strategy = compile_markdowns_to_pdf(
            md_sources=[file1, file2],
            output_pdf_path=out_pdf
        )

        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 1000
        # Verify it has PDF signature
        with open(pdf_path, "rb") as f:
            header = f.read(5)
            assert header == b"%PDF-"

        assert strategy.title is not None
        assert strategy.orientation in ("portrait", "landscape")

    def test_compile_with_font_size_preset(self):
        temp_dir = tempfile.mkdtemp()
        file1 = os.path.join(temp_dir, "doc_font.md")
        with open(file1, "w", encoding="utf-8") as f:
            f.write("# Notas Ultra Densas\nTexto de prueba en letra super pequeña.\n")

        out_pdf = os.path.join(temp_dir, "ultra_small_test.pdf")
        pdf_path, strategy = compile_markdowns_to_pdf(
            md_sources=file1,
            output_pdf_path=out_pdf,
            font_size_mode="super_pequeña"
        )

        assert os.path.exists(pdf_path)
        assert strategy.font_size_pt == 7.2
        assert strategy.table_font_size_pt == 6.4
        assert strategy.font_size_preset == "ultra_small"

