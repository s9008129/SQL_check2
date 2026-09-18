"""Application settings: YAML config loading + environment variable overrides.

Deliberately plain (stdlib + PyYAML, no pydantic-settings): the PRD's backend
dependency list (§39) does not include a settings framework, and the only
things that vary by environment are a handful of Ollama connection values
already named explicitly in PRD §46. See CLAUDE plan "改善優先指數編製模型"
for why rules/scoring config is data (YAML), not code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent / "config"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class UploadSettings:
    max_file_mb: int
    max_extracted_chars: int
    allowed_extensions: tuple[str, ...]
    docx_max_uncompressed_mb: int
    docx_max_compression_ratio: int

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def docx_max_uncompressed_bytes(self) -> int:
        return self.docx_max_uncompressed_mb * 1024 * 1024


@dataclass(frozen=True)
class OllamaSettings:
    base_url: str
    model: str
    timeout_seconds: int
    num_ctx: int
    num_predict: int
    temperature: float
    keep_alive: str
    max_retries_on_invalid_json: int
    think: bool = False
    # 2026-09-17: upper bound for the per-request num_ctx that ai_service
    # raises when a long SQL would not fit into `num_ctx` (see
    # ai_service._num_ctx_for). Default 32768 = Gemma4's comfortable window.
    num_ctx_max: int = 32768


@dataclass(frozen=True)
class MaskingSettings:
    keep_short_ascii_literal_max_len: int


@dataclass(frozen=True)
class ArchiveSettings:
    enabled: bool
    dir: Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_title: str
    upload: UploadSettings
    ollama: OllamaSettings
    ai_gate: dict[str, Any]
    ai_guard: dict[str, Any]
    knowledge_context: dict[str, Any]
    masking: MaskingSettings
    archive: ArchiveSettings
    rules_config: dict[str, Any]
    important_tables_config: dict[str, Any]
    prompts_dir: Path = PROMPTS_DIR


@lru_cache
def get_settings() -> Settings:
    app_cfg = _load_yaml("app.yaml")
    rules_cfg = _load_yaml("rules.yaml")
    tables_cfg = _load_yaml("important_tables.yaml")

    app_section = app_cfg.get("app", {})
    upload_section = app_cfg.get("upload", {})
    ollama_section = app_cfg.get("ollama", {})
    masking_section = app_cfg.get("masking", {})
    archive_section = app_cfg.get("archive", {})

    upload = UploadSettings(
        max_file_mb=int(upload_section.get("max_file_mb", 10)),
        max_extracted_chars=int(upload_section.get("max_extracted_chars", 300_000)),
        allowed_extensions=tuple(
            ext.lower() for ext in upload_section.get("allowed_extensions", [])
        ),
        docx_max_uncompressed_mb=int(upload_section.get("docx_max_uncompressed_mb", 80)),
        docx_max_compression_ratio=int(upload_section.get("docx_max_compression_ratio", 100)),
    )

    ollama = OllamaSettings(
        base_url=os.environ.get(
            ollama_section.get("base_url_env", "OLLAMA_BASE_URL"),
            ollama_section.get("base_url_default", "http://host.docker.internal:11434"),
        ),
        model=os.environ.get(
            ollama_section.get("model_env", "OLLAMA_MODEL"),
            ollama_section.get("model_default", "gemma4:31b"),
        ),
        timeout_seconds=_env_int(
            ollama_section.get("timeout_seconds_env", "OLLAMA_TIMEOUT_SECONDS"),
            int(ollama_section.get("timeout_seconds_default", 120)),
        ),
        num_ctx=_env_int(
            ollama_section.get("num_ctx_env", "OLLAMA_NUM_CTX"),
            # 2026-09-17: fallback kept in sync with app.yaml's num_ctx_default
            # (16384, not the old 8192) — app.yaml is the source of truth, this
            # only applies if that key ever goes missing.
            int(ollama_section.get("num_ctx_default", 16384)),
        ),
        num_predict=int(ollama_section.get("num_predict", 1024)),
        temperature=float(ollama_section.get("temperature", 0.2)),
        keep_alive=str(ollama_section.get("keep_alive", "30m")),
        max_retries_on_invalid_json=int(ollama_section.get("max_retries_on_invalid_json", 1)),
        think=_env_bool(
            ollama_section.get("think_env", "OLLAMA_THINK"),
            bool(ollama_section.get("think_default", False)),
        ),
        num_ctx_max=_env_int(
            ollama_section.get("num_ctx_max_env", "OLLAMA_NUM_CTX_MAX"),
            int(ollama_section.get("num_ctx_max_default", 32768)),
        ),
    )

    masking = MaskingSettings(
        keep_short_ascii_literal_max_len=int(masking_section.get("keep_short_ascii_literal_max_len", 4)),
    )

    archive = ArchiveSettings(
        enabled=_env_bool(
            archive_section.get("enabled_env", "SQLCHECK_ARCHIVE_ENABLED"),
            bool(archive_section.get("enabled", True)),
        ),
        dir=Path(
            os.environ.get(
                archive_section.get("dir_env", "SQLCHECK_ARCHIVE_DIR"),
                archive_section.get("dir_default", "/data/sql_archive"),
            )
        ),
    )

    knowledge_context = dict(app_cfg.get("knowledge_context", {}))
    knowledge_context["enabled"] = _env_bool(
        str(knowledge_context.get("enabled_env", "SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED")),
        bool(knowledge_context.get("enabled", True)),
    )

    return Settings(
        app_name=app_section.get("name", "SQLCheck AI"),
        app_title=app_section.get("title", "SQL 效能優化助手"),
        upload=upload,
        ollama=ollama,
        ai_gate=app_cfg.get("ai_gate", {}),
        ai_guard=app_cfg.get("ai_guard", {}),
        knowledge_context=knowledge_context,
        masking=masking,
        archive=archive,
        rules_config=rules_cfg,
        important_tables_config=tables_cfg,
    )
