from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class MarginsConfig(BaseModel):
    """Page margins configuration in millimeters."""
    top_mm: float = Field(default=7.0, ge=3.0, le=25.0, description="Margen superior en mm")
    bottom_mm: float = Field(default=7.0, ge=3.0, le=25.0, description="Margen inferior en mm")
    left_mm: float = Field(default=7.0, ge=3.0, le=25.0, description="Margen izquierdo en mm")
    right_mm: float = Field(default=7.0, ge=3.0, le=25.0, description="Margen derecho en mm")

    @property
    def css_string(self) -> str:
        return f"{self.top_mm}mm {self.right_mm}mm {self.bottom_mm}mm {self.left_mm}mm"


class TableMetric(BaseModel):
    """Metrics extracted from a markdown table."""
    table_index: int
    column_count: int
    headers: List[str]
    max_cell_chars: int
    estimated_row_count: int
    is_wide: bool = Field(
        description="True si la tabla tiene 4 o más columnas o texto denso que requiere ancho completo"
    )


class DocumentMetrics(BaseModel):
    """Aggregated structural metrics from all input Markdown documents."""
    total_files: int
    file_names: List[str]
    total_words: int
    total_characters: int
    total_tables: int
    max_table_columns: int
    has_wide_tables: bool
    tables: List[TableMetric] = Field(default_factory=list)
    callouts_count: int
    headings_count: int
    inferred_title: str


class LayoutStrategy(BaseModel):
    """Pydantic model defining the complete layout, typography, and page strategy
    for maximizing space efficiency in the generated PDF."""

    orientation: Literal["portrait", "landscape"] = Field(
        description="Orientación del documento: 'portrait' (vertical) para texto/listas o 'landscape' (horizontal) para tablas anchas"
    )
    columns: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Número de columnas de texto (1 para flujo secuencial, 2 para estilo compendio compacto de alta densidad)"
    )
    font_size_pt: float = Field(
        default=8.5,
        ge=6.5,
        le=12.0,
        description="Tamaño de fuente base en puntos tipográficos (pt)"
    )
    table_font_size_pt: float = Field(
        default=7.5,
        ge=6.0,
        le=10.0,
        description="Tamaño de fuente para celdas y cabeceras de tablas en pt"
    )
    line_height: float = Field(
        default=1.25,
        ge=1.1,
        le=1.6,
        description="Interlineado del cuerpo de texto"
    )
    margins_mm: MarginsConfig = Field(
        default_factory=MarginsConfig,
        description="Configuración de márgenes en milímetros"
    )
    table_strategy: Literal["compact_fit", "full_width_span", "landscape_table"] = Field(
        default="compact_fit",
        description="Estrategia de renderizado para tablas (ej. full_width_span rompe las 2 columnas para usar todo el ancho)"
    )
    title: str = Field(
        description="Título principal para la portada o encabezado superior del compendio consolidado"
    )
    theme: Literal["clinical_compact", "academic_dense", "modern_minimal"] = Field(
        default="clinical_compact",
        description="Tema cromático y visual del documento"
    )
    space_saving_tips: List[str] = Field(
        default_factory=list,
        description="Estrategias activadas para maximizar el aprovechamiento del papel"
    )
    justification: str = Field(
        description="Justificación técnica detallada de por qué se eligieron estos parámetros (orientación, columnas, márgenes)."
    )
    font_size_preset: Optional[str] = Field(
        default="small",
        description="Preajuste de tamaño de letra: 'normal', 'small' (pequeña), 'ultra_small' (super pequeña)"
    )

    def apply_font_preset(self, preset: str):
        """Adjusts font sizes and line heights according to the requested density preset."""
        preset_clean = preset.lower().strip().replace(" ", "_")
        if preset_clean in ("normal", "estándar", "standard"):
            self.font_size_pt = 9.5
            self.table_font_size_pt = 8.5
            self.line_height = 1.32
            self.font_size_preset = "normal"
        elif preset_clean in ("small", "pequeña", "pequena", "compact"):
            self.font_size_pt = 8.5
            self.table_font_size_pt = 7.5
            self.line_height = 1.24
            self.font_size_preset = "small"
        elif preset_clean in ("ultra_small", "super_pequeña", "super_pequena", "superpequeña", "superpequena", "mini"):
            self.font_size_pt = 7.2
            self.table_font_size_pt = 6.4
            self.line_height = 1.15
            self.font_size_preset = "ultra_small"

