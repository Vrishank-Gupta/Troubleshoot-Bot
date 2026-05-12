"""Extract text from PDF files preserving structure."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_pdf(file_path: str | Path) -> str:
    """Return extracted text from PDF, preserving headings and numbered lists."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(file_path))
        parts = []
        for page in doc:
            text = page.get_text("text")
            if text.strip():
                parts.append(text)
        doc.close()
        return "\n\n".join(parts)
    except ImportError:
        logger.warning("PyMuPDF not available, trying pdfplumber")
        return _extract_pdfplumber(file_path)
    except Exception as e:
        logger.error("PDF extraction error for %s: %s", file_path, e)
        raise


def _extract_pdfplumber(file_path: str | Path) -> str:
    try:
        import pdfplumber
        parts = []
        with pdfplumber.open(str(file_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
        return "\n\n".join(parts)
    except ImportError:
        raise RuntimeError("Neither PyMuPDF nor pdfplumber is installed.")
