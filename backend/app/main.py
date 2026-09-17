"""FastAPI application entrypoint: mounts the three PRD §40 API routes under
/api, then serves the already-built React app as static files (PRD §5 "FastAPI
靜態服務" — no Node runtime in the production image, PRD §38.2).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import Response

from app.api import router as api_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="SQLCheck AI", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(api_router, prefix="/api")

def _find_static_dir(main_py_path: Path) -> Path | None:
    """Two candidate locations for the built frontend, given this module's
    own `__file__`:

    1. Production (Dockerfile): `COPY --from=frontend-build .../dist ./static`
       runs from `WORKDIR /app/backend`, landing the build at `backend/static`
       — a *sibling* of `app/` (this file's own parent), not inside it. So
       resolving relative to this file requires going up **two** levels
       (`app/main.py` -> `app/` -> `backend/`), not one. A one-level
       `.parent / "static"` silently resolves to a directory that can never
       exist (`app/static`) and this whole block never activates — the exact
       bug that shipped to the first production deploy (confirmed live:
       `/`, `/index.html`, `/assets/*` all 404'd while `/api/*` worked fine,
       because FastAPI had no static routes registered at all).
    2. Local Phase 6 integration testing (`uvicorn app.main:app` run from
       `backend/`, frontend built separately via `npm run build`): a sibling
       `frontend/dist` two levels above `backend/` itself.
    """
    backend_dir = main_py_path.resolve().parent.parent  # app/main.py -> app/ -> backend/
    candidates = [
        backend_dir / "static",
        backend_dir.parent / "frontend" / "dist",
    ]
    return next((d for d in candidates if d.is_dir() and any(d.iterdir())), None)


_STATIC_DIR = _find_static_dir(Path(__file__))


def _safe_static_path(static_root: Path, requested_path: str) -> Path | None:
    """Resolve `requested_path` against `static_root` and return it only if
    the resolved path stays inside that root; otherwise None.

    Security: `requested_path` is attacker-controlled — FastAPI's
    `{full_path:path}` converter accepts arbitrary segments, `..` included,
    on this public, unauthenticated catch-all route. Without this check,
    `GET /../../app/config/app.yaml`-style requests could read files outside
    the intended static directory. Kept as a standalone, directly unit-
    testable function rather than inlined in the route handler.
    """
    try:
        candidate = (static_root / requested_path).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if not candidate.is_relative_to(static_root):
        return None
    return candidate


if _STATIC_DIR is not None:
    _STATIC_ROOT = _STATIC_DIR.resolve()
    _assets_dir = _STATIC_DIR / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.middleware("http")
    async def _cache_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif request.url.path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/", include_in_schema=False)
    async def _index() -> FileResponse:
        return FileResponse(_STATIC_ROOT / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            # A genuinely unknown /api/* path should 404, not silently fall
            # back to the SPA shell.
            raise HTTPException(status_code=404, detail="Not Found")

        candidate = _safe_static_path(_STATIC_ROOT, full_path)
        if candidate is not None and candidate.is_file():
            return FileResponse(candidate)
        # No client-side router in this MVP (PRD §27: single dashboard
        # page), but a stray deep link, refresh, or rejected traversal
        # attempt should still land on the app rather than a bare 404.
        return FileResponse(_STATIC_ROOT / "index.html")
else:
    logger.warning("No built frontend found (backend/static or frontend/dist) — serving API only.")
