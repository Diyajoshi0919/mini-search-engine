"""
Turns each supported file type into a list of (page, text) lines.

Every format ends up looking the same to the indexer: a list of lines,
each tagged with the page it came from (page is None for formats that
don't have pages, like .txt).
"""
import os

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def is_supported(filename):
    return os.path.splitext(filename)[1].lower() in SUPPORTED_EXTENSIONS


def _read_text_file(path):
    # try utf-8 first, fall back for files saved by older Windows editors
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                content = f.read()
            # utf-16 "succeeds" on plain ascii as garbage, so sanity check it
            if enc == "utf-16" and "\x00" in content:
                continue
            return [(None, line) for line in content.splitlines()]
        except (UnicodeDecodeError, UnicodeError):
            continue
    return []


def _read_pdf(path):
    from pypdf import PdfReader

    reader = PdfReader(path)
    lines = []
    for page_num, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            # one broken page shouldn't kill the whole document
            text = ""
        for line in text.splitlines():
            lines.append((page_num, line))
    return lines


def _read_docx(path):
    import docx

    document = docx.Document(path)
    lines = [(None, p.text) for p in document.paragraphs]

    # tables are separate from paragraphs in a .docx, so grab them too
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                lines.append((None, " | ".join(cells)))
    return lines


def extract_lines(path):
    ext = os.path.splitext(path)[1].lower()

    if ext in (".txt", ".md"):
        raw = _read_text_file(path)
    elif ext == ".pdf":
        raw = _read_pdf(path)
    elif ext == ".docx":
        raw = _read_docx(path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    # drop blank lines and squash runs of whitespace (PDFs are full of them)
    cleaned = []
    for page, text in raw:
        text = " ".join(text.split())
        if text:
            cleaned.append((page, text))
    return cleaned
