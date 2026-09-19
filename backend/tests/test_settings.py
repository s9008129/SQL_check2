from app.settings import get_settings


def test_knowledge_context_can_be_disabled_by_environment(monkeypatch):
    monkeypatch.setenv("SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED", "false")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.knowledge_context["enabled"] is False
    finally:
        get_settings.cache_clear()


def test_knowledge_context_default_is_enabled(monkeypatch):
    monkeypatch.delenv("SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.knowledge_context["enabled"] is True
        assert settings.knowledge_context["max_patterns"] == 4
        assert settings.knowledge_context["max_total_chars"] == 1800
    finally:
        get_settings.cache_clear()

def test_default_llm_provider_is_ollama(monkeypatch):
    monkeypatch.delenv("SQLCHECK_LLM_PROVIDER", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.llm.provider == "ollama"
        assert settings.llm.provider_type == "ollama"
        assert settings.llm.model == "gemma4:31b"
        assert settings.llm.remote is False
        assert settings.llm.allow_short_ascii_literals is True
    finally:
        get_settings.cache_clear()


def test_gemini_provider_selected_from_environment(monkeypatch):
    monkeypatch.setenv("SQLCHECK_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-for-test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.llm.provider == "gemini"
        assert settings.llm.provider_type == "gemini"
        assert settings.llm.model == "gemini-test"
        assert settings.llm.api_key == "secret-for-test"
        assert settings.llm.remote is True
        assert settings.llm.allow_short_ascii_literals is False
    finally:
        get_settings.cache_clear()


def test_archive_relative_default_resolves_under_project_root(monkeypatch):
    monkeypatch.delenv("SQLCHECK_ARCHIVE_DIR", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.archive.dir.name == "sql_archive"
        assert settings.archive.dir.parent.name == "data"
        assert settings.archive.dir.is_absolute()
    finally:
        get_settings.cache_clear()

