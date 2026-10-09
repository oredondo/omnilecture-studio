import os
import shutil
import tempfile
import logging
import subprocess

logger = logging.getLogger("PDFCompiler.PDFRenderer")


class PDFRenderer:
    """Renders HTML documents into pixel-perfect, space-optimized PDFs
    using headless Chromium / Google Chrome."""

    def __init__(self, chrome_executable: str = None):
        self.chrome_bin = chrome_executable or self._find_chrome()
        if not self.chrome_bin:
            raise RuntimeError(
                "No se encontró Google Chrome o Chromium en el sistema. "
                "Asegúrate de tener instalado google-chrome o chromium-browser."
            )

    def _find_chrome(self) -> str | None:
        """Finds Chrome or Chromium executable on the system."""
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
        ]
        for c in candidates:
            if c and os.path.exists(c) and os.access(c, os.X_OK):
                return c
        return None

    def render_to_pdf(self, html_content: str, output_pdf_path: str) -> str:
        """Renders the HTML string directly to the target PDF file path."""
        output_pdf_path = os.path.abspath(output_pdf_path)
        os.makedirs(os.path.dirname(output_pdf_path), exist_ok=True)

        temp_dir = tempfile.mkdtemp(prefix="pdf_compile_")
        temp_html_path = os.path.join(temp_dir, "document.html")

        try:
            with open(temp_html_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            cmd = [
                self.chrome_bin,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--print-to-pdf-no-header",
                f"--print-to-pdf={output_pdf_path}",
                temp_html_path
            ]

            logger.info(f"Rendering PDF with {os.path.basename(self.chrome_bin)} -> {output_pdf_path}...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=45
            )

            if result.returncode != 0:
                logger.error(f"Chrome PDF rendering failed (code {result.returncode}): {result.stderr}")
                raise RuntimeError(f"Error generando PDF con Chrome: {result.stderr}")

            if not os.path.exists(output_pdf_path) or os.path.getsize(output_pdf_path) < 500:
                raise RuntimeError(
                    f"El archivo PDF generado está vacío o no se creó correctamente en {output_pdf_path}"
                )

            pdf_size_kb = os.path.getsize(output_pdf_path) / 1024
            logger.info(f"PDF successfully rendered ({pdf_size_kb:.1f} KB) at: {output_pdf_path}")
            return output_pdf_path

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
