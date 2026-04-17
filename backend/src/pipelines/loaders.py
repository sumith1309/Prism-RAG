import re
from pathlib import Path
from typing import Iterable

from langchain_core.documents import Document as LCDocument
from langchain_community.document_loaders import PyPDFLoader


# ─── Table-aware text preprocessing ─────────────────────────────────────────
# Tables in PDFs/DOCX often get chunked into orphaned rows that lose their
# column headers. "JWT (httpOnly cookies)" becomes meaningless without knowing
# it's in the "Authentication" row under "Technology Stack". Fix: detect
# table-like structures and serialize each row as a natural-language sentence
# BEFORE the text splitter runs.
#
# Pattern detected: lines with | separators (markdown tables) or consistent
# tab/multi-space alignment. We convert:
#   | Layer | Technology |
#   | Authentication | JWT (httpOnly cookies) |
# Into:
#   "Layer: Authentication. Technology: JWT (httpOnly cookies)."

_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")  # separator like |---|---|


def _serialize_tables(text: str) -> str:
    """Convert markdown-style tables into natural-language sentences so
    table cells retain their column-header context after chunking.

    Non-table text passes through unchanged. Multiple tables in one
    document are handled independently.
    """
    lines = text.split("\n")
    result: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Detect table start: a line with | separators.
        if _TABLE_ROW_RE.match(line):
            # Collect the full table.
            table_lines: list[str] = []
            while i < len(lines) and (_TABLE_ROW_RE.match(lines[i]) or _TABLE_SEP_RE.match(lines[i])):
                if not _TABLE_SEP_RE.match(lines[i]):  # skip separator rows
                    table_lines.append(lines[i])
                i += 1

            if len(table_lines) >= 2:
                # First row = headers, rest = data rows.
                headers = [
                    h.strip() for h in table_lines[0].split("|") if h.strip()
                ]
                for row_line in table_lines[1:]:
                    cells = [c.strip() for c in row_line.split("|") if c.strip()]
                    # Build sentence: "Header1: Cell1. Header2: Cell2."
                    parts = []
                    for j, cell in enumerate(cells):
                        header = headers[j] if j < len(headers) else f"Column {j+1}"
                        parts.append(f"{header}: {cell}")
                    sentence = ". ".join(parts) + "."
                    result.append(sentence)
                result.append("")  # blank line after serialized table
            else:
                # Single-row "table" — just pass through.
                for tl in table_lines:
                    result.append(tl)
                i += 1
        else:
            result.append(line)
            i += 1

    return "\n".join(result)


def _preprocess_text(text: str) -> str:
    """Run all text preprocessing steps before chunking.
    Currently: table serialization. Extensible for future transforms.
    """
    return _serialize_tables(text)


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


def _extract_pdf_tables(path: Path) -> dict[int, list[str]]:
    """Extract tables from a PDF using pdfplumber and serialize each row
    as 'Header: Value' sentences. Returns {page_number: [serialized_rows]}.

    Falls back to empty dict if pdfplumber is unavailable.
    """
    try:
        import pdfplumber
    except ImportError:
        return {}

    tables_by_page: dict[int, list[str]] = {}
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_tables = page.extract_tables()
                if not page_tables:
                    continue
                serialized: list[str] = []
                for table in page_tables:
                    if len(table) < 2:
                        continue
                    # First row = headers
                    headers = [(h or "").strip() or f"Column {j+1}"
                               for j, h in enumerate(table[0])]
                    for row in table[1:]:
                        cells = [(c or "").strip() for c in row]
                        if not any(cells):
                            continue
                        parts = []
                        for j, cell_val in enumerate(cells):
                            if not cell_val:
                                continue
                            header = headers[j] if j < len(headers) else f"Column {j+1}"
                            parts.append(f"{header}: {cell_val}")
                        if parts:
                            serialized.append(". ".join(parts) + ".")
                if serialized:
                    tables_by_page[page_num] = serialized
    except Exception:
        pass
    return tables_by_page


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
            docs = ocr_docs

    # Extract structured tables via pdfplumber and append serialized rows
    # to the page content. This preserves column headers on every row so
    # table data survives chunking — same fix as DOCX/Excel.
    pdf_tables = _extract_pdf_tables(path)
    for d in docs:
        page_idx = d.metadata.get("page", 0)
        # PyPDFLoader uses 0-based page index; pdfplumber also 0-based.
        if page_idx in pdf_tables:
            table_block = "\n".join(pdf_tables[page_idx])
            d.page_content = (d.page_content or "") + "\n\n" + table_block

    # Table-aware preprocessing: serialize markdown-style tables into
    # natural-language sentences (catches any tables pdfplumber missed).
    for d in docs:
        d.page_content = _preprocess_text(d.page_content or "")
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


def _extract_docx_with_tables(path: Path) -> str:
    """Extract DOCX content using python-docx, serializing tables with
    column headers on every row so table structure survives chunking.

    Falls back to docx2txt if python-docx fails.
    """
    try:
        from docx import Document as DocxDocument
    except ImportError:
        import docx2txt
        return (docx2txt.process(str(path)) or "").strip()

    try:
        doc = DocxDocument(str(path))
    except Exception:
        import docx2txt
        return (docx2txt.process(str(path)) or "").strip()

    # Build a content-order list from the document body. python-docx
    # exposes body.iter_inner_content() in newer versions but we use
    # the XML element tree for compatibility with all versions.
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    parts: list[str] = []
    for element in doc.element.body:
        tag = element.tag.split("}")[-1]

        if tag == "p":
            para = Paragraph(element, doc)
            text = para.text.strip()
            if text:
                parts.append(text)

        elif tag == "tbl":
            table = Table(element, doc)
            if len(table.rows) < 2:
                # Single-row table — just dump cell values.
                cells = [c.text.strip() for c in table.rows[0].cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
                continue

            headers = [cell.text.strip() for cell in table.rows[0].cells]
            for row in table.rows[1:]:
                cells = [cell.text.strip() for cell in row.cells]
                row_parts = []
                for j, cell_val in enumerate(cells):
                    if not cell_val:
                        continue
                    header = headers[j] if j < len(headers) else f"Column {j+1}"
                    row_parts.append(f"{header}: {cell_val}")
                if row_parts:
                    parts.append(". ".join(row_parts) + ".")
            parts.append("")  # blank line after table

    return "\n\n".join(parts)


def _load_docx(path: Path) -> list[LCDocument]:
    """Load a .docx as N pseudo-pages (N = real page count when available,
    otherwise estimated from text length at ~3000 chars/page). This matches
    PDF/text behavior — one LCDocument per page, then the standard text
    splitter produces chunks on top. Fixes the old behavior that treated
    each paragraph as a page and produced hundreds of fake pages."""

    text = _preprocess_text(_extract_docx_with_tables(path))
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
    text = _preprocess_text(path.read_text(encoding="utf-8", errors="ignore"))
    # split into ~3000-char pseudo-pages so retrieval scores reference a stable page number
    page_size = 3000
    chunks = [text[i : i + page_size] for i in range(0, len(text), page_size)] or [text]
    return [LCDocument(page_content=c, metadata={"page": i + 1}) for i, c in enumerate(chunks)]


def _load_excel(path: Path) -> list[LCDocument]:
    """Load .xlsx/.xls — serialize each row as 'Header: Value' sentences.

    Multi-sheet workbooks produce one section per sheet. Row 1 of each
    sheet is treated as column headers. Empty rows are skipped.
    """
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []

    for sheet in wb.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            continue

        # First row = headers
        headers = [str(h).strip() if h is not None else f"Column {j+1}"
                   for j, h in enumerate(rows[0])]

        if len(wb.worksheets) > 1:
            parts.append(f"Sheet: {sheet.title}")

        for row in rows[1:]:
            cells = [str(v).strip() if v is not None else "" for v in row]
            if not any(cells):
                continue
            row_parts = []
            for j, cell_val in enumerate(cells):
                if not cell_val:
                    continue
                header = headers[j] if j < len(headers) else f"Column {j+1}"
                row_parts.append(f"{header}: {cell_val}")
            if row_parts:
                parts.append(". ".join(row_parts) + ".")

        parts.append("")  # blank line between sheets

    wb.close()
    text = "\n".join(parts).strip()
    if not text:
        return [LCDocument(page_content="", metadata={"page": 1})]

    # Split into pseudo-pages (~3000 chars each)
    page_size = 3000
    chunks = [text[i : i + page_size] for i in range(0, len(text), page_size)] or [text]
    return [LCDocument(page_content=c, metadata={"page": i + 1}) for i, c in enumerate(chunks)]


def _load_csv(path: Path) -> list[LCDocument]:
    """Load .csv — serialize each row as 'Header: Value' sentences.

    First row is treated as column headers.
    """
    import csv

    with open(path, newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if len(rows) < 2:
        text = "\n".join(",".join(r) for r in rows)
        return [LCDocument(page_content=text, metadata={"page": 1})]

    headers = [h.strip() or f"Column {j+1}" for j, h in enumerate(rows[0])]
    parts: list[str] = []

    for row in rows[1:]:
        cells = [v.strip() for v in row]
        if not any(cells):
            continue
        row_parts = []
        for j, cell_val in enumerate(cells):
            if not cell_val:
                continue
            header = headers[j] if j < len(headers) else f"Column {j+1}"
            row_parts.append(f"{header}: {cell_val}")
        if row_parts:
            parts.append(". ".join(row_parts) + ".")

    text = "\n".join(parts).strip()
    if not text:
        return [LCDocument(page_content="", metadata={"page": 1})]

    page_size = 3000
    chunks = [text[i : i + page_size] for i in range(0, len(text), page_size)] or [text]
    return [LCDocument(page_content=c, metadata={"page": i + 1}) for i, c in enumerate(chunks)]


SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".md", ".markdown", ".xlsx", ".xls", ".csv"}


def load_any(path: Path) -> list[LCDocument]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _load_pdf(path)
    if ext == ".docx":
        return _load_docx(path)
    if ext in {".xlsx", ".xls"}:
        return _load_excel(path)
    if ext == ".csv":
        return _load_csv(path)
    if ext in {".txt", ".md", ".markdown"}:
        return _load_text(path)
    raise ValueError(f"Unsupported file type: {ext}")


def detect_mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".csv": "text/csv",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
    }.get(ext, "application/octet-stream")
