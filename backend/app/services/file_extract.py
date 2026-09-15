"""Attachment text extraction (PRD §9, §10, §50.1).

Every supported format converges on one extracted text string. Nothing is
ever written to disk: uploads are held only in the in-memory `bytes` the
caller passes in, for the duration of one request (PRD §6.3, §9.4).
sql_detect.py — not this module — decides whether the extracted text looks
like SQL; this module's only job is "attachment bytes -> plain text",
validated and security-checked per format.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

import charset_normalizer
import docx
import pypdf
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.settings import Settings


class AttachmentError(Exception):
    """A user-facing, Traditional-Chinese error message (PRD §52). api.py
    catches this and returns it as an HTTPException detail."""


@dataclass
class ExtractResult:
    text: str
    truncated: bool = False


# Executable / disallowed-container magic bytes, checked before anything
# else regardless of the claimed extension (PRD §9.4 "拒絕可執行檔").
_EXECUTABLE_MAGICS = (
    b"MZ",  # Windows PE
    b"\x7fELF",  # Linux ELF
    b"\xca\xfe\xba\xbe",  # Mach-O / Java class (fat binary)
    b"\xfe\xed\xfa",  # Mach-O
)
_MAGIC_CHECKS = {
    ".pdf": lambda b: b.startswith(b"%PDF-"),
    ".docx": lambda b: b.startswith(b"PK\x03\x04"),
}
_PAGE_NUMBER_LINE_RE = re.compile(r"^(page\s*)?\d{1,4}(\s*/\s*\d{1,4})?$", re.IGNORECASE)


def _ext_of(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx >= 0 else ""


def validate_upload(filename: str, content: bytes, settings: Settings) -> str:
    """Extension + size + magic-byte checks. Returns the validated lowercase
    extension, or raises AttachmentError with a friendly message."""
    ext = _ext_of(filename)
    if ext not in settings.upload.allowed_extensions:
        allowed = "、".join(e.lstrip(".").upper() for e in settings.upload.allowed_extensions)
        raise AttachmentError(f"此格式目前不支援，請使用 {allowed} 檔案，或直接貼上 SQL。")
    if len(content) == 0:
        raise AttachmentError("檔案內容為空，請確認後再試一次。")
    if len(content) > settings.upload.max_file_bytes:
        raise AttachmentError("檔案超過允許大小，請精簡內容或直接貼上 SQL。")
    for magic in _EXECUTABLE_MAGICS:
        if content.startswith(magic):
            raise AttachmentError("不允許上傳可執行檔。")
    check = _MAGIC_CHECKS.get(ext)
    if check and not check(content):
        raise AttachmentError("檔案內容與副檔名不符，請確認檔案是否正確。")
    return ext


def extract_text(filename: str, content: bytes, settings: Settings) -> ExtractResult:
    ext = validate_upload(filename, content, settings)
    if ext in (".txt", ".sql", ".md", ".markdown", ".csv"):
        text = _decode_text(content)
    elif ext == ".docx":
        text = _extract_docx(content, settings)
    elif ext == ".pdf":
        text = _extract_pdf(content)
    else:  # pragma: no cover - guarded by validate_upload
        raise AttachmentError("此格式目前不支援，請確認附件內容或直接貼上 SQL。")

    max_chars = settings.upload.max_extracted_chars
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    return ExtractResult(text=text, truncated=truncated)


# ---------------------------------------------------------------------------
# Plain text decoding (PRD §10.1): UTF-8 (with/without BOM) first, then
# charset-normalizer, then a Big5/CP950 fallback for older Taiwanese files.
# ---------------------------------------------------------------------------
def _decode_text(content: bytes) -> str:
    if content.startswith(b"\xef\xbb\xbf"):
        return content[3:].decode("utf-8", errors="replace")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # PRD §10.1 names Big5/CP950 specifically as the expected legacy Taiwan
    # encoding — tried explicitly, ahead of the general-purpose detector.
    # charset-normalizer's statistical guess is unreliable on short CJK byte
    # sequences (verified: it mis-detected a Big5 test string as CP949/
    # Korean); a strict CP950 decode attempt is a strong, low-false-positive
    # signal on its own — arbitrary non-Big5 bytes are unlikely to happen to
    # form a fully valid CP950 sequence.
    try:
        return content.decode("cp950")
    except UnicodeDecodeError:
        pass
    match = charset_normalizer.from_bytes(content).best()
    if match is not None:
        return str(match)
    return content.decode("cp950", errors="replace")


# ---------------------------------------------------------------------------
# DOCX (PRD §10.4): document-order paragraph + table-cell text; zip-bomb and
# macro-document guards run before python-docx ever opens the archive.
# ---------------------------------------------------------------------------
def _check_zip_safety(content: bytes, settings: Settings) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise AttachmentError("附件檔案已損壞，無法讀取，請確認檔案是否正確。") from exc

    if any(name.lower() == "word/vbaproject.bin" for name in zf.namelist()):
        raise AttachmentError("不支援巨集文件，請另存為一般 .docx 後再上傳。")

    total_uncompressed = 0
    for info in zf.infolist():
        total_uncompressed += info.file_size
        if info.file_size > 0 and info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > settings.upload.docx_max_compression_ratio:
                raise AttachmentError("附件檔案內容異常，無法處理，請確認檔案是否正確。")
    if total_uncompressed > settings.upload.docx_max_uncompressed_bytes:
        raise AttachmentError("附件檔案內容過大，無法處理，請精簡內容或直接貼上 SQL。")
    return zf


def _iter_block_items(document):
    """Yield paragraphs and tables in true document order (python-docx has
    no built-in helper for this; `.paragraphs`/`.tables` are separate flat
    lists that lose interleaving order)."""
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _extract_docx(content: bytes, settings: Settings) -> str:
    _check_zip_safety(content, settings)
    try:
        document = docx.Document(io.BytesIO(content))
    except Exception as exc:
        raise AttachmentError("附件檔案已損壞或格式不正確，無法讀取。") from exc

    parts: list[str] = []
    for block in _iter_block_items(document):
        if isinstance(block, Paragraph):
            if block.text.strip():
                parts.append(block.text)
        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        parts.append(cell.text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# PDF (PRD §10.5): text-layer only, no OCR. Encrypted -> friendly error.
# "Scanned" (no real text layer) -> friendly error, never silently proceeds.
# ---------------------------------------------------------------------------
_SCANNED_MESSAGE = (
    "此 PDF 可能為掃描影像，第一版無法自動辨識。"
    "請改用可選取文字的 PDF、DOCX、TXT，或直接貼上 SQL。"
)


def _strip_page_furniture(pages_text: list[str]) -> list[str]:
    """Drop lines repeated on (almost) every page (running headers/footers)
    and bare page-number lines, so they cannot pollute SQL detection or
    count toward the "this page has real text" check below."""
    if len(pages_text) < 2:
        return [ln for ln in pages_text]

    per_page_lines = [p.split("\n") for p in pages_text]
    line_counts: dict[str, int] = {}
    for lines in per_page_lines:
        for stripped in {ln.strip() for ln in lines if ln.strip()}:
            line_counts[stripped] = line_counts.get(stripped, 0) + 1

    threshold = max(2, len(pages_text) - 1)
    repeated = {line for line, count in line_counts.items() if count >= threshold and len(line) < 80}

    cleaned = []
    for lines in per_page_lines:
        kept = [
            ln
            for ln in lines
            if ln.strip() not in repeated and not _PAGE_NUMBER_LINE_RE.match(ln.strip())
        ]
        cleaned.append("\n".join(kept))
    return cleaned


def _meaningful_char_count(text: str) -> int:
    return sum(1 for ch in text if ch.isalnum() or "一" <= ch <= "鿿")


def _extract_pdf(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise AttachmentError("附件檔案已損壞或格式不正確，無法讀取。") from exc

    if reader.is_encrypted:
        opened = False
        try:
            opened = bool(reader.decrypt(""))
        except Exception:
            opened = False
        if not opened:
            raise AttachmentError(
                "此 PDF 受密碼保護，系統無法自動開啟，"
                "請移除密碼後再上傳，或改用可選取文字的 PDF、DOCX、TXT，或直接貼上 SQL。"
            )

    pages_text: list[str] = []
    for page in reader.pages:
        try:
            pages_text.append(page.extract_text() or "")
        except Exception:
            pages_text.append("")

    cleaned = _strip_page_furniture(pages_text)
    # Threshold is deliberately low (not PRD-mandated, chosen to avoid a
    # false positive on a legitimately short SQL statement — a real scanned
    # page has ~0 extractable characters after furniture-stripping, not a
    # borderline count) while still catching genuinely empty/scanned pages.
    if not cleaned or all(_meaningful_char_count(p) < 10 for p in cleaned):
        raise AttachmentError(_SCANNED_MESSAGE)

    return "\n".join(cleaned).strip()
