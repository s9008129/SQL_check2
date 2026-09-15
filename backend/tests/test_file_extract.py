import dataclasses

import pytest

from app.services import file_extract
from app.settings import get_settings
from tests import make_fixtures as fx


def _settings(**upload_overrides):
    base = get_settings()
    upload = dataclasses.replace(base.upload, **upload_overrides)
    return dataclasses.replace(base, upload=upload)


SETTINGS = get_settings()


# ---------------------------------------------------------------------------
# validate_upload
# ---------------------------------------------------------------------------
def test_disallowed_extension_rejected():
    with pytest.raises(file_extract.AttachmentError):
        file_extract.validate_upload("virus.exe", b"MZ" + b"\x00" * 20, SETTINGS)


def test_empty_file_rejected():
    with pytest.raises(file_extract.AttachmentError):
        file_extract.validate_upload("a.sql", b"", SETTINGS)


def test_oversized_file_rejected():
    settings = _settings(max_file_mb=1)
    with pytest.raises(file_extract.AttachmentError):
        file_extract.validate_upload("a.sql", b"x" * (2 * 1024 * 1024), settings)


def test_executable_disguised_as_txt_rejected():
    with pytest.raises(file_extract.AttachmentError):
        file_extract.validate_upload("notes.txt", b"MZ\x90\x00\x03", SETTINGS)


def test_extension_magic_mismatch_rejected():
    with pytest.raises(file_extract.AttachmentError):
        file_extract.validate_upload("fake.pdf", b"not a real pdf", SETTINGS)


def test_valid_extension_and_magic_accepted():
    ext = file_extract.validate_upload("q.sql", b"SELECT 1 FROM DUAL", SETTINGS)
    assert ext == ".sql"


# ---------------------------------------------------------------------------
# Text decoding (PRD §54 TXT cases)
# ---------------------------------------------------------------------------
def test_utf8_decoding():
    text = "SELECT * FROM T A WHERE A.X = 1 -- 中文註解"
    result = file_extract.extract_text("q.sql", fx.build_utf8_bytes(text), SETTINGS)
    assert result.text == text


def test_utf8_bom_decoding():
    text = "SELECT * FROM T A WHERE A.X = 1"
    result = file_extract.extract_text("q.sql", fx.build_utf8_bom_bytes(text), SETTINGS)
    assert result.text == text


def test_big5_decoding():
    text = "SELECT * FROM T A WHERE A.備註 = '測試'"
    result = file_extract.extract_text("q.sql", fx.build_big5_bytes(text), SETTINGS)
    assert "SELECT" in result.text
    assert "測試" in result.text


def test_truncation_at_max_extracted_chars():
    settings = _settings(max_extracted_chars=10)
    result = file_extract.extract_text("q.txt", fx.build_utf8_bytes("SELECT * FROM T WHERE X=1"), settings)
    assert result.truncated is True
    assert len(result.text) == 10


# ---------------------------------------------------------------------------
# DOCX (PRD §54 DOCX cases)
# ---------------------------------------------------------------------------
def test_docx_paragraph_and_table_extraction_in_order():
    content = fx.build_docx_bytes(
        paragraphs=["申請單位說明如下：", "SELECT A.X FROM T A WHERE A.Y=1"],
        table_rows=[["說明", "SQL"], ["備註", "SELECT B.Z FROM T2 B WHERE B.W=2"]],
    )
    result = file_extract.extract_text("report.docx", content, SETTINGS)
    assert "SELECT A.X FROM T A WHERE A.Y=1" in result.text
    assert "SELECT B.Z FROM T2 B WHERE B.W=2" in result.text
    # paragraphs must appear before the table that follows them
    assert result.text.index("申請單位說明如下") < result.text.index("SELECT A.X")


def test_corrupted_docx_rejected():
    with pytest.raises(file_extract.AttachmentError):
        file_extract.extract_text("broken.docx", fx.build_corrupted_docx_bytes(), SETTINGS)


def test_macro_docx_rejected():
    with pytest.raises(file_extract.AttachmentError):
        file_extract.extract_text("macro.docx", fx.build_docx_with_macro_bytes(), SETTINGS)


def test_docx_compression_ratio_zip_bomb_rejected():
    with pytest.raises(file_extract.AttachmentError):
        file_extract.extract_text("bomb.docx", fx.build_highly_compressed_docx_bytes(), SETTINGS)


def test_docx_total_uncompressed_size_guard():
    # Use a low, deliberately-tiny cap so a perfectly ordinary docx trips it,
    # isolating this test from the compression-ratio guard.
    settings = _settings(docx_max_uncompressed_mb=0, docx_max_compression_ratio=100_000)
    content = fx.build_docx_bytes(paragraphs=["SELECT 1 FROM DUAL"])
    with pytest.raises(file_extract.AttachmentError):
        file_extract.extract_text("normal.docx", content, settings)


# ---------------------------------------------------------------------------
# PDF (PRD §54 PDF cases)
# ---------------------------------------------------------------------------
def test_pdf_text_extraction():
    content = fx.build_pdf_bytes(["SELECT A.X FROM T A WHERE A.Y = 1"])
    result = file_extract.extract_text("q.pdf", content, SETTINGS)
    assert "SELECT A.X FROM T A WHERE A.Y = 1" in result.text


def test_pdf_multi_page_extraction():
    content = fx.build_pdf_bytes(["SELECT * FROM T1 WHERE X=1", "SELECT * FROM T2 WHERE Y=2"])
    result = file_extract.extract_text("q.pdf", content, SETTINGS)
    assert "T1" in result.text and "T2" in result.text


def test_scanned_pdf_rejected_with_friendly_message():
    with pytest.raises(file_extract.AttachmentError) as exc_info:
        file_extract.extract_text("scan.pdf", fx.build_scanned_pdf_bytes(), SETTINGS)
    assert "掃描影像" in str(exc_info.value)


def test_encrypted_pdf_rejected_with_friendly_message():
    with pytest.raises(file_extract.AttachmentError) as exc_info:
        file_extract.extract_text("secure.pdf", fx.build_encrypted_pdf_bytes(), SETTINGS)
    assert "密碼保護" in str(exc_info.value)
