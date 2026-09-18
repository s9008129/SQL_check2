from app.services import context_adapter
from app.services.pattern_selector import PatternMatch, PatternSelection


def _m(pattern_id: str, classification: str, *indexes: int, signal: str = "test") -> PatternMatch:
    return PatternMatch(
        pattern_id=pattern_id,
        classification=classification,
        match_kind="exact",
        statement_indexes=tuple(indexes or (0,)),
        signals=(signal,),
    )


def test_context_uses_exact_matches_only_and_excludes_out_of_scope():
    selection = PatternSelection(
        exact=(
            _m("SUBSTR_EQ_TO_LIKE", "VERIFIED_REWRITE", 0),
            _m("INDEX_ADVISORY", "OUT_OF_SCOPE", 0),
        ),
        family_signals=(
            PatternMatch(
                pattern_id="TRUNC_EQ_TO_RANGE",
                classification="ADVICE_ONLY",
                match_kind="family_signal",
                statement_indexes=(0,),
                signals=("family_rule:R005",),
            ),
        ),
    )
    context = context_adapter.build_knowledge_context(selection, {}, statement_index=0)
    assert context_adapter.context_ids(context) == ("SUBSTR_EQ_TO_LIKE",)
    assert all(item["classification"] != "OUT_OF_SCOPE" for item in context)
    assert "TRUNC_EQ_TO_RANGE" not in context_adapter.context_ids(context)


def test_context_requires_a_representative_statement():
    selection = PatternSelection(exact=(_m("SUBSTR_EQ_TO_LIKE", "VERIFIED_REWRITE", 0),))
    assert context_adapter.build_knowledge_context(selection, {}, statement_index=None) == []


def test_context_is_limited_to_representative_statement():
    selection = PatternSelection(
        exact=(
            _m("SUBSTR_EQ_TO_LIKE", "VERIFIED_REWRITE", 0),
            _m("OR_SAME_COLUMN_TO_IN", "VERIFIED_REWRITE", 1),
        )
    )
    context = context_adapter.build_knowledge_context(selection, {}, statement_index=1)
    assert context_adapter.context_ids(context) == ("OR_SAME_COLUMN_TO_IN",)


def test_priority_is_verified_then_advice_then_informational():
    selection = PatternSelection(
        exact=(
            _m("SELECT_STAR", "INFORMATIONAL", 0),
            _m("DISTINCT_REMOVAL", "ADVICE_ONLY", 0),
            _m("OR_SAME_COLUMN_TO_IN", "VERIFIED_REWRITE", 0),
        )
    )
    context = context_adapter.build_knowledge_context(
        selection, {"max_patterns": 3, "max_total_chars": 6000}, statement_index=0
    )
    assert context_adapter.context_ids(context) == (
        "OR_SAME_COLUMN_TO_IN",
        "DISTINCT_REMOVAL",
        "SELECT_STAR",
    )


def test_max_patterns_is_a_hard_top_n_boundary():
    selection = PatternSelection(
        exact=(
            _m("SUBSTR_EQ_TO_LIKE", "VERIFIED_REWRITE", 0),
            _m("OR_SAME_COLUMN_TO_IN", "VERIFIED_REWRITE", 0),
            _m("DISTINCT_REMOVAL", "ADVICE_ONLY", 0),
        )
    )
    context = context_adapter.build_knowledge_context(
        selection, {"max_patterns": 2, "max_total_chars": 6000}, statement_index=0
    )
    assert len(context) == 2
    assert context_adapter.context_ids(context) == ("SUBSTR_EQ_TO_LIKE", "OR_SAME_COLUMN_TO_IN")


def test_character_budget_skips_whole_items_never_truncates_guidance():
    selection = PatternSelection(exact=(_m("SUBSTR_EQ_TO_LIKE", "VERIFIED_REWRITE", 0),))
    full = context_adapter.build_knowledge_context(
        selection, {"max_patterns": 4, "max_total_chars": 6000}, statement_index=0
    )
    assert len(full) == 1
    item_chars = sum(len(v) for v in full[0].values())

    too_small = context_adapter.build_knowledge_context(
        selection, {"max_patterns": 4, "max_total_chars": item_chars - 1}, statement_index=0
    )
    exact_fit = context_adapter.build_knowledge_context(
        selection, {"max_patterns": 4, "max_total_chars": item_chars}, statement_index=0
    )
    assert too_small == []
    assert exact_fit == full


def test_context_can_be_disabled_without_touching_selector():
    selection = PatternSelection(exact=(_m("SUBSTR_EQ_TO_LIKE", "VERIFIED_REWRITE", 0),))
    assert context_adapter.build_knowledge_context(
        selection, {"enabled": False}, statement_index=0
    ) == []


def test_hard_caps_prevent_misconfiguration_from_unbounding_context():
    ids = [
        ("SUBSTR_EQ_TO_LIKE", "VERIFIED_REWRITE"),
        ("OR_SAME_COLUMN_TO_IN", "VERIFIED_REWRITE"),
        ("NOT_IN_SUBQUERY_TO_NOT_EXISTS", "ADVICE_ONLY"),
        ("CORRELATED_SUBQUERY_TO_JOIN_OR_WINDOW", "ADVICE_ONLY"),
        ("DISTINCT_REMOVAL", "ADVICE_ONLY"),
        ("LEADING_WILDCARD_LIKE", "ADVICE_ONLY"),
        ("CARTESIAN_JOIN_MISSING_CONDITION", "ADVICE_ONLY"),
        ("SELECT_STAR", "INFORMATIONAL"),
        ("IMPORTANT_TABLE_USAGE", "INFORMATIONAL"),
        ("STRUCTURAL_COMPLEXITY_MANY_TABLES", "INFORMATIONAL"),
    ]
    selection = PatternSelection(exact=tuple(_m(pid, cls, 0) for pid, cls in ids))
    context = context_adapter.build_knowledge_context(
        selection, {"max_patterns": 9999, "max_total_chars": 999999}, statement_index=0
    )
    assert len(context) <= context_adapter._HARD_MAX_PATTERNS
    assert sum(sum(len(v) for v in item.values()) for item in context) <= context_adapter._HARD_MAX_TOTAL_CHARS


def test_match_signals_never_enter_model_context():
    secret = "SECRET_SQL_LITERAL_AND_TABLE_NAME"
    selection = PatternSelection(
        exact=(_m("SUBSTR_EQ_TO_LIKE", "VERIFIED_REWRITE", 0, signal=secret),)
    )
    context = context_adapter.build_knowledge_context(selection, {}, statement_index=0)
    assert secret not in repr(context)


def test_catalog_classification_drift_fails_closed_for_context():
    selection = PatternSelection(exact=(_m("SUBSTR_EQ_TO_LIKE", "ADVICE_ONLY", 0),))
    # Selector/catalog drift is a configuration error. ai_service catches this
    # and sends an empty context rather than injecting ambiguous knowledge.
    try:
        context_adapter.build_knowledge_context(selection, {}, statement_index=0)
    except ValueError as exc:
        assert "classification drift" in str(exc)
    else:
        raise AssertionError("classification drift must not be silently injected")
