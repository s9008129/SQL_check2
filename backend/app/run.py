"""Production/dev entrypoint (Dockerfile CMD: `python -m app.run`).

Always binds a single internal port (8000): HTTPS when a cert+key exist
under the certs directory, plain HTTP otherwise. Production always has
certs by the time the container starts (deploy.ps1 runs `app.certgen`
before `docker compose up`); plain HTTP is purely a dev-machine convenience
since there is no TLS requirement locally.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

CERTS_DIR = Path(os.environ.get("SQLCHECK_CERTS_DIR", "/certs"))
CERT_FILE = CERTS_DIR / "sqlcheck.crt"
KEY_FILE = CERTS_DIR / "sqlcheck.key"


def main() -> None:
    has_tls = CERT_FILE.exists() and KEY_FILE.exists()
    kwargs: dict[str, object] = {"host": "0.0.0.0", "port": 8000}
    if has_tls:
        kwargs["ssl_certfile"] = str(CERT_FILE)
        kwargs["ssl_keyfile"] = str(KEY_FILE)
    uvicorn.run("app.main:app", **kwargs)


if __name__ == "__main__":
    main()
