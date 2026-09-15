"""Tests for app/main.py's static-file serving, focused on the path-
traversal defense in `_safe_static_path` (flagged by automated security
review on the SPA-fallback catch-all route — `{full_path:path}` accepts
arbitrary attacker-controlled segments, `..` included)."""

import tempfile
from pathlib import Path

import pytest

from app.main import _safe_static_path


@pytest.fixture
def static_root():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        (root / "index.html").write_text("<html>index</html>")
        (root / "assets").mkdir()
        (root / "assets" / "app.js").write_text("console.log('ok')")
        # A secret file *outside* the static root, to prove traversal can't reach it.
        (root.parent / "secret.txt").write_text("do not serve this")
        yield root


def test_normal_file_resolves_inside_root(static_root):
    result = _safe_static_path(static_root, "assets/app.js")
    assert result is not None
    assert result == (static_root / "assets" / "app.js").resolve()


def test_dotdot_traversal_outside_root_is_rejected(static_root):
    result = _safe_static_path(static_root, "../secret.txt")
    assert result is None


def test_deep_dotdot_traversal_is_rejected(static_root):
    result = _safe_static_path(static_root, "assets/../../secret.txt")
    assert result is None


def test_encoded_looking_traversal_segments_are_rejected(static_root):
    # FastAPI's {full_path:path} converter already URL-decodes before the
    # handler sees it, so by the time this function runs the value looks
    # like a plain "../" segment either way — still must be rejected.
    result = _safe_static_path(static_root, "..%2f..%2fsecret.txt")
    # Either rejected outright, or (since '%2f' isn't decoded by this layer)
    # treated as a literal filename that doesn't exist inside root — both
    # are safe; the only unsafe outcome is resolving outside static_root.
    if result is not None:
        assert result.is_relative_to(static_root)


def test_absolute_path_segment_does_not_escape_root(static_root):
    # On Windows, joining an "absolute-looking" segment can replace the
    # base entirely if not guarded; the is_relative_to check must still
    # catch it even if `/` (Path.__truediv__) lets the absolute path win.
    result = _safe_static_path(static_root, str(static_root.parent / "secret.txt"))
    assert result is None


def test_nonexistent_but_in_root_path_resolves_but_caller_checks_is_file(static_root):
    # _safe_static_path only enforces containment, not existence -- the
    # route handler is responsible for the is_file() check afterwards.
    result = _safe_static_path(static_root, "does/not/exist.html")
    assert result is not None
    assert result.is_relative_to(static_root)
    assert not result.is_file()
