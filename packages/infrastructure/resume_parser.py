"""
Resume file parser — extracts plain text from PDF and DOCX files.

Used by the profile upload-resume endpoint to convert uploaded files
into text before feeding into the existing profile_import LLM pipeline.
"""

from __future__ import annotations

import io
import logging
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
MIN_TEXT_LENGTH = 50

ALLOWED_EXTENSIONS = {".pdf", ".docx"}


class ResumeParseError(Exception):
    pass


def parse_resume(file_bytes: bytes, filename: str) -> str:
    ext = PurePosixPath(filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise ResumeParseError(
            f"Unsupported file type '{ext}'. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    if len(file_bytes) > MAX_FILE_BYTES:
        raise ResumeParseError(
            f"File too large ({len(file_bytes) / 1024 / 1024:.1f} MB). Maximum is 10 MB."
        )

    if ext == ".pdf":
        text = _parse_pdf(file_bytes)
    else:
        text = _parse_docx(file_bytes)

    text = text.strip()

    if len(text) < MIN_TEXT_LENGTH:
        raise ResumeParseError(
            f"Extracted text too short ({len(text)} chars). "
            "The file may be empty, image-only, or password-protected."
        )

    logger.info("resume_parser: extracted %d chars from %s", len(text), filename)
    return text


def _parse_pdf(file_bytes: bytes) -> str:
    import fitz

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def _parse_docx(file_bytes: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)
