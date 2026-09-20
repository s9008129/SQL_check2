"""Tests for app/main.py's static-file serving, focused on the path-
traversal defense in `_safe_static_path` (flagged by automated security
review on the SPA-fallback catch-all route — `{full_path:path}` accepts
arbitrary attacker-controlled segments, `..` included)."""

import tempfile
from pathlib import Path

import pytest

from app.main import _find_static_dir, _safe_static_path


# ---------------------------------------------------------------------------
# _find_static_dir: regression coverage for a real bug found on the first
# production deploy. `/`, `/index.html`, and `/assets/*` all 404'd (while
# `/api/*` worked fine) because the production candidate path was computed
# one directory level too shallow, so it could never exist and the whole
# static-serving block silently never activated. Builds a fake directory
# tree mirroring the real container layout instead of relying on an actual
# Docker build (unavailable on the dev machine) to catch this class of bug.
# ---------------------------------------------------------------------------
def test_find_static_dir_matches_dockerfile_production_layout():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Mirrors WORKDIR /app/backend in the Dockerfile: app/main.py lives
        # at <backend>/app/main.py; `COPY ... ./static` lands at
        # <backend>/static, a *sibling* of app/, not inside it.
        backend_dir = root / "app" / "backend"
        app_dir = backend_dir / "app"
        static_dir = backend_dir / "static"
        app_dir.mkdir(parents=True)
        static_dir.mkdir(parents=True)
        (static_dir / "index.html").write_text("<html>prod build</html>")
        fake_main_py = app_dir / "main.py"

        result = _find_static_dir(fake_main_py)

        assert result == static_dir.resolve()
        assert (result / "index.html").is_file()


def test_find_static_dir_falls_back_to_frontend_dist_for_local_dev():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Mirrors the repo layout for local Phase 6 integration testing:
        # <repo>/backend/app/main.py and <repo>/frontend/dist/index.html,
        # with backend/static left empty (just as it is in the real repo,
        # populated only by a Docker build).
        repo_dir = root / "SQL_check2"
        backend_static = repo_dir / "backend" / "static"
        app_dir = repo_dir / "backend" / "app"
        frontend_dist = repo_dir / "frontend" / "dist"
        backend_static.mkdir(parents=True)  # exists but empty -> must be skipped
        app_dir.mkdir(parents=True)
        frontend_dist.mkdir(parents=True)
        (frontend_dist / "index.html").write_text("<html>local dev build</html>")
        fake_main_py = app_dir / "main.py"

        result = _find_static_dir(fake_main_py)

        assert result == frontend_dist.resolve()


def test_find_static_dir_returns_none_when_nothing_built():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        app_dir = root / "backend" / "app"
        app_dir.mkdir(parents=True)
        fake_main_py = app_dir / "main.py"

        assert _find_static_dir(fake_main_py) is None


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
