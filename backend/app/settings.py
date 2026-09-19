"""Application settings: YAML config loading + environment variable overrides.

The runtime is intentionally provider-agnostic:
- app.yaml: product/runtime settings (upload, guards, archive, knowledge context)
- llm.yaml: selectable LLM provider profiles (Ollama, Gemini, future providers)
- rules.yaml / important_tables.yaml: deterministic governance rules

Secrets are never stored in YAML. Cloud provider credentials are read only from
an environment variable declared by the selected profile (for Gemini:
GEMINI_API_KEY).
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
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def _env_int(name: str | None, default: int) -> int:
    if not name:
        return default
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str | None, default: bool) -> bool:
    if not name:
        return default
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _env_float(name: str | None, default: float | None) -> float | None:
    if not name:
        return default
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _resolve_project_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


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
class LLMSettings:
    """One active provider profile from config/llm.yaml.

    The common fields are deliberately named by product meaning
    (max_output_tokens / context_window) rather than one vendor's API names.
    Provider-specific request translation lives in services/llm_provider.py.
    """

    provider: str
    provider_type: str
    remote: bool
    base_url: str
    model: str
    api_key_env: str | None
    api_key: str | None
    timeout_seconds: int
    max_output_tokens: int
    context_window: int
    context_window_max: int
    temperature: float | None
    keep_alive: str | None
    max_retries_on_invalid_json: int
    think: bool
    allow_short_ascii_literals: bool


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
    llm: LLMSettings
    ai_gate: dict[str, Any]
    ai_guard: dict[str, Any]
    knowledge_context: dict[str, Any]
    masking: MaskingSettings
    archive: ArchiveSettings
    rules_config: dict[str, Any]
    important_tables_config: dict[str, Any]
    prompts_dir: Path = PROMPTS_DIR


def _load_llm_settings() -> LLMSettings:
    cfg = _load_yaml("llm.yaml")
    provider_env = str(cfg.get("active_provider_env", "SQLCHECK_LLM_PROVIDER"))
    provider = os.environ.get(provider_env, str(cfg.get("active_provider_default", "ollama"))).strip().lower()

    providers = cfg.get("providers", {})
    if not isinstance(providers, dict) or provider not in providers:
        known = ", ".join(sorted(providers)) if isinstance(providers, dict) else ""
        raise ValueError(f"Unknown LLM provider '{provider}'. Available: {known}")

    section = providers[provider] or {}
    provider_type = str(section.get("type", provider)).strip().lower()
    api_key_env = section.get("api_key_env")
    api_key_env = str(api_key_env) if api_key_env else None

    base_url_env = str(section.get("base_url_env", "")).strip() or None
    model_env = str(section.get("model_env", "")).strip() or None
    temperature_env = str(section.get("temperature_env", "")).strip() or None

    base_url = (
        os.environ.get(base_url_env, str(section.get("base_url_default", "")))
        if base_url_env
        else str(section.get("base_url_default", ""))
    ).rstrip("/")
    model = (
        os.environ.get(model_env, str(section.get("model_default", "")))
        if model_env
        else str(section.get("model_default", ""))
    ).strip()

    if not base_url:
        raise ValueError(f"LLM provider '{provider}' has no base_url")
    if not model:
        raise ValueError(f"LLM provider '{provider}' has no model")

    return LLMSettings(
        provider=provider,
        provider_type=provider_type,
        remote=bool(section.get("remote", False)),
        base_url=base_url,
        model=model,
        api_key_env=api_key_env,
        api_key=os.environ.get(api_key_env) if api_key_env else None,
        timeout_seconds=_env_int(
            str(section.get("timeout_seconds_env", "")).strip() or None,
            int(section.get("timeout_seconds_default", 120)),
        ),
        max_output_tokens=_env_int(
            str(section.get("max_output_tokens_env", "")).strip() or None,
            int(section.get("max_output_tokens_default", 3072)),
        ),
        context_window=_env_int(
            str(section.get("context_window_env", "")).strip() or None,
            int(section.get("context_window_default", 16384)),
        ),
        context_window_max=_env_int(
            str(section.get("context_window_max_env", "")).strip() or None,
            int(section.get("context_window_max_default", section.get("context_window_default", 16384))),
        ),
        temperature=_env_float(temperature_env, section.get("temperature_default")),
        keep_alive=str(section["keep_alive"]) if section.get("keep_alive") is not None else None,
        max_retries_on_invalid_json=int(section.get("max_retries_on_invalid_json", 1)),
        think=_env_bool(
            str(section.get("think_env", "")).strip() or None,
            bool(section.get("think_default", False)),
        ),
        allow_short_ascii_literals=bool(section.get("allow_short_ascii_literals", not bool(section.get("remote", False)))),
    )


@lru_cache
def get_settings() -> Settings:
    app_cfg = _load_yaml("app.yaml")
    rules_cfg = _load_yaml("rules.yaml")
    tables_cfg = _load_yaml("important_tables.yaml")

    app_section = app_cfg.get("app", {})
    upload_section = app_cfg.get("upload", {})
    masking_section = app_cfg.get("masking", {})
    archive_section = app_cfg.get("archive", {})

    upload = UploadSettings(
        max_file_mb=int(upload_section.get("max_file_mb", 10)),
        max_extracted_chars=int(upload_section.get("max_extracted_chars", 300_000)),
        allowed_extensions=tuple(ext.lower() for ext in upload_section.get("allowed_extensions", [])),
        docx_max_uncompressed_mb=int(upload_section.get("docx_max_uncompressed_mb", 80)),
        docx_max_compression_ratio=int(upload_section.get("docx_max_compression_ratio", 100)),
    )

    masking = MaskingSettings(
        keep_short_ascii_literal_max_len=int(masking_section.get("keep_short_ascii_literal_max_len", 4)),
    )

    archive_dir_raw = os.environ.get(
        str(archive_section.get("dir_env", "SQLCHECK_ARCHIVE_DIR")),
        str(archive_section.get("dir_default", "data/sql_archive")),
    )
    archive = ArchiveSettings(
        enabled=_env_bool(
            str(archive_section.get("enabled_env", "SQLCHECK_ARCHIVE_ENABLED")),
            bool(archive_section.get("enabled", True)),
        ),
        dir=_resolve_project_path(archive_dir_raw),
    )

    knowledge_context = dict(app_cfg.get("knowledge_context", {}))
    knowledge_context["enabled"] = _env_bool(
        str(knowledge_context.get("enabled_env", "SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED")),
        bool(knowledge_context.get("enabled", True)),
    )

    return Settings(
        app_name=app_section.get("name", "SQLCheck AI"),
        app_title=app_section.get("title", "SQL 智慧效能檢核與改善助手"),
        upload=upload,
        llm=_load_llm_settings(),
        ai_gate=app_cfg.get("ai_gate", {}),
        ai_guard=app_cfg.get("ai_guard", {}),
        knowledge_context=knowledge_context,
        masking=masking,
        archive=archive,
        rules_config=rules_cfg,
        important_tables_config=tables_cfg,
    )
