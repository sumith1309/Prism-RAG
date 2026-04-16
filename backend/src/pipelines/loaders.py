from pathlib import Path
from typing import Iterable

from langchain_core.documents import Document as LCDocument
from langchain_community.document_loaders import PyPDFLoader


# Tier 2.1 — minimum chars per page below which we suspect a scanned PDF.
# PyPDFLoader returns empty/near-empty page_content for image-only pages;
# we kick those over to Tesseract via pdf2image for OCR.
_OCR_MIN_CHARS_PER_PAGE = 40


def _ocr_pdf(path: Path) -> list[LCDocument]:
    """Run Tesseract OCR on each page of a PDF. Used as a fallback for
    scanned/image-only PDFs where PyPDFLoader returns empty text. Slow
    (~1-3s per page on CPU) but unavoidable for non-OCR'd scans.

    Requires system: tesseract + poppler (brew install tesseract poppler).
    Requires Python: pytesseract + pdf2image.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        return []

    try:
        # 200 DPI is the sweet spot — high enough for clean OCR on body
        # text, low enough to keep each page render under ~1.5s on CPU.
        images = convert_from_path(str(path), dpi=200)
    except Exception:
        return []

    out: list[LCDocument] = []
    for i, img in enumerate(images):
        try:
            text = pytesseract.image_to_string(img, lang="eng").strip()
        except Exception:
            text = ""
        if text:
            out.append(
                LCDocument(
                    page_content=text,
                    metadata={"page": i + 1, "source": "ocr"},
                )
            )
    return out


def _load_pdf(path: Path) -> list[LCDocument]:
    docs = PyPDFLoader(str(path)).load()
    for d in docs:
        if "page" not in d.metadata:
            d.metadata["page"] = d.metadata.get("page_number", 0)

    # Tier 2.1 — OCR fallback for scanned PDFs. If PyPDFLoader produced
    # no docs OR the average page has < _OCR_MIN_CHARS_PER_PAGE of
    # extracted text, the PDF is almost certainly an image-only scan.
    # Re-process via Tesseract.
    text_total = sum(len((d.page_content or "").strip()) for d in docs)
    needs_ocr = (
        not docs
        or (docs and text_total / max(len(docs), 1) < _OCR_MIN_CHARS_PER_PAGE)
    )
    if needs_ocr:
        ocr_docs = _ocr_pdf(path)
        if ocr_docs:
            return ocr_docs
    return docs


def _docx_page_count(path: Path) -> int:
    """Read the real page count from docProps/app.xml inside the DOCX zip.
    Word writes <Pages>N</Pages> on save; returns 0 if absent (older/odd docs)."""
    import xml.etree.ElementTree as ET
    import zipfile

    try:
        with zipfile.ZipFile(path) as z:
            with z.open("docProps/app.xml") as f:
                root = ET.parse(f).getroot()
        # Namespace-agnostic lookup — property lives under the extended-properties ns.
        for child in root.iter():
            tag = child.tag.split("}", 1)[-1]
            if tag == "Pages" and (child.text or "").strip().isdigit():
                return int(child.text.strip())
    except Exception:
        pass
    return 0


def _load_docx(path: Path) -> list[LCDocument]:
    """Load a .docx as N pseudo-pages (N = real page count when available,
    otherwise estimated from text length at ~3000 chars/page). This matches
    PDF/text behavior — one LCDocument per page, then the standard text
    splitter produces chunks on top. Fixes the old behavior that treated
    each paragraph as a page and produced hundreds of fake pages."""
    import docx2txt

    text = (docx2txt.process(str(path)) or "").strip()
    if not text:
        return [LCDocument(page_content="", metadata={"page": 1})]

    pages_meta = _docx_page_count(path)
    if pages_meta > 0:
        n_pages = pages_meta
    else:
        # Fallback estimate: ~3000 chars per printed page.
        n_pages = max(1, (len(text) + 2999) // 3000)

    # Split the concatenated text into roughly equal pseudo-page spans so page
    # citations are stable and meaningful. Splits prefer paragraph boundaries
    # where possible.
    if n_pages == 1:
        return [LCDocument(page_content=text, metadata={"page": 1})]

    span = max(1, len(text) // n_pages)
    docs: list[LCDocument] = []
    cursor = 0
    for i in range(n_pages):
        end = len(text) if i == n_pages - 1 else cursor + span
        # Nudge the cut to the next paragraph boundary so pages read naturally.
        if end < len(text):
            nl = text.find("\n\n", end)
            if nl != -1 and nl - end < 400:
                end = nl
        page_text = text[cursor:end].strip()
        if page_text:
            docs.append(LCDocument(page_content=page_text, metadata={"page": i + 1}))
        cursor = end
    return docs or [LCDocument(page_content=text, metadata={"page": 1})]


def _load_text(path: Path) -> list[LCDocument]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    # split into ~3000-char pseudo-pages so retrieval scores reference a stable page number
    page_size = 3000
    chunks = [text[i : i + page_size] for i in range(0, len(text), page_size)] or [text]
    return [LCDocument(page_content=c, metadata={"page": i + 1}) for i, c in enumerate(chunks)]


SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".md", ".markdown"}


def load_any(path: Path) -> list[LCDocument]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _load_pdf(path)
    if ext == ".docx":
        return _load_docx(path)
    if ext in {".txt", ".md", ".markdown"}:
        return _load_text(path)
    raise ValueError(f"Unsupported file type: {ext}")


def detect_mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
    }.get(ext, "application/octet-stream")
