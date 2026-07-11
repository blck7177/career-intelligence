"""
Convert a generated .docx to PDF via headless LibreOffice.

Requires the `soffice` binary on PATH (package: libreoffice). Not yet
wired into any Docker image — see docs/runbook.md before deploying
anything that calls this.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class PdfConversionError(Exception):
    pass


def docx_to_pdf(docx_path: str | Path, output_dir: str | Path | None = None, timeout: int = 60) -> Path:
    docx_path = Path(docx_path)
    output_dir = Path(output_dir) if output_dir else docx_path.parent

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise PdfConversionError("LibreOffice (soffice) not found on PATH")

    result = subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(docx_path)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise PdfConversionError(f"soffice conversion failed (exit {result.returncode}): {result.stderr}")

    pdf_path = output_dir / (docx_path.stem + ".pdf")
    if not pdf_path.exists():
        raise PdfConversionError(f"Expected output not found: {pdf_path}")
    return pdf_path
