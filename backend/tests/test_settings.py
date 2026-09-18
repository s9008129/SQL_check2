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
