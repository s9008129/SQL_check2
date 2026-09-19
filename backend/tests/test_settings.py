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
        assert settings.llm.thinking_level is None
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
        assert settings.llm.thinking_level == "minimal"
        assert settings.llm.allow_short_ascii_literals is True
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

def test_gemini_thinking_level_can_be_overridden(monkeypatch):
    monkeypatch.setenv("SQLCHECK_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-for-test")
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "high")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.llm.thinking_level == "high"
    finally:
        get_settings.cache_clear()

def test_gemini_default_profile_matches_formal_gemma(monkeypatch):
    monkeypatch.setenv("SQLCHECK_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-for-test")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.llm.model == "gemma-4-31b-it"
        assert settings.llm.temperature == 0.2
        assert settings.llm.top_p == 0.95
        assert settings.llm.top_k == 64
        assert settings.llm.thinking_level == "minimal"
        assert settings.llm.max_output_tokens == 3072
        assert settings.llm.context_window == 16384
        assert settings.llm.context_window_max == 32768
        assert settings.llm.allow_short_ascii_literals is True
    finally:
        get_settings.cache_clear()

def test_ollama_cloud_provider_selected_from_environment(monkeypatch):
    monkeypatch.setenv("SQLCHECK_LLM_PROVIDER", "ollama_cloud")
    monkeypatch.setenv("OLLAMA_API_KEY", "secret-for-test")
    monkeypatch.delenv("OLLAMA_CLOUD_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.llm.provider == "ollama_cloud"
        assert settings.llm.provider_type == "ollama"
        assert settings.llm.remote is True
        assert settings.llm.base_url == "https://ollama.com"
        assert settings.llm.model == "gemma4:31b"
        assert settings.llm.api_key_env == "OLLAMA_API_KEY"
        assert settings.llm.api_key == "secret-for-test"
        assert settings.llm.temperature == 0.2
        assert settings.llm.top_p == 0.95
        assert settings.llm.top_k == 64
        assert settings.llm.max_output_tokens == 3072
        assert settings.llm.context_window == 16384
        assert settings.llm.context_window_max == 32768
        assert settings.llm.think is False
        assert settings.llm.keep_alive is None
        assert settings.llm.allow_short_ascii_literals is True
    finally:
        get_settings.cache_clear()

