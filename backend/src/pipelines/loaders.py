from pathlib import Path
from typing import Iterable

from langchain_core.documents import Document as LCDocument
from langchain_community.document_loaders import PyPDFLoader


def _load_pdf(path: Path) -> list[LCDocument]:
    docs = PyPDFLoader(str(path)).load()
    for d in docs:
        if "page" not in d.metadata:
            d.metadata["page"] = d.metadata.get("page_number", 0)
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
