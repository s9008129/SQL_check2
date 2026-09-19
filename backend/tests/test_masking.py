from app.services.masking import (
    DEIDENTIFY_FAILED_MARKER,
    deidentify_sql,
    mask_sql,
    scrub_invented_placeholders,
    unmask_sql,
)


# ---------------------------------------------------------------------------
# String literal masking
# ---------------------------------------------------------------------------
def test_string_literal_masked_prd_example():
    # PRD example: WHERE IDN_BAN = 'A123456789' -> WHERE IDN_BAN = :STR_001
    result = mask_sql("SELECT * FROM T A WHERE A.IDN_BAN = 'A123456789'")
    assert "A123456789" not in result.masked_sql
    assert ":STR_001" in result.masked_sql
    assert result.reverse_map[":STR_001"] == "'A123456789'"


def test_multiple_string_literals_numbered_in_first_seen_order():
    # This exact shape (OR before AND in source, literal 'second' appearing
    # before 'first') is what exposed that sqlglot's tree.find_all() does
    # NOT walk in source order — see masking.py's module docstring. Assert
    # numbering follows the SQL text, not AST traversal order.
    sql = "SELECT * FROM T WHERE B = 'second' AND A = 'first' OR C = 'third'"
    result = mask_sql(sql)
    assert result.masked_sql == "SELECT * FROM T WHERE B = :STR_001 AND A = :STR_002 OR C = :STR_003"
    assert result.reverse_map[":STR_001"] == "'second'"
    assert result.reverse_map[":STR_002"] == "'first'"
    assert result.reverse_map[":STR_003"] == "'third'"


def test_string_literal_with_escaped_quote():
    result = mask_sql("SELECT * FROM T WHERE NAME = 'O''Brien'")
    assert "O'Brien" not in result.masked_sql
    assert result.reverse_map[":STR_001"] == "'O''Brien'"


# ---------------------------------------------------------------------------
# Numeric literal masking
# ---------------------------------------------------------------------------
def test_large_numeric_literal_masked():
    result = mask_sql("SELECT * FROM T A WHERE A.AMT = 1234567")
    assert "1234567" not in result.masked_sql
    assert ":NUM_001" in result.masked_sql
    assert result.reverse_map[":NUM_001"] == "1234567"


def test_six_digit_boundary_is_masked_five_digit_is_not():
    result = mask_sql("SELECT * FROM T WHERE A = 123456 AND B = 12345")
    assert ":NUM_001" in result.masked_sql
    assert result.reverse_map[":NUM_001"] == "123456"
    assert "12345" in result.masked_sql  # 5-digit number left alone, unmasked


def test_small_numbers_left_alone():
    result = mask_sql("SELECT * FROM T A WHERE A.SMALL = 2 LIMIT 10")
    assert result.masked_sql == "SELECT * FROM T A WHERE A.SMALL = 2 LIMIT 10"
    assert result.reverse_map == {}


def test_digits_inside_identifier_not_masked():
    result = mask_sql("SELECT * FROM TABLE123456 A WHERE A.X = 1")
    assert "TABLE123456" in result.masked_sql
    assert result.reverse_map == {}


# ---------------------------------------------------------------------------
# Bind variables
# ---------------------------------------------------------------------------
def test_existing_named_bind_variable_untouched():
    result = mask_sql("SELECT * FROM T A WHERE A.IDN_BAN = :IDN_BAN")
    assert result.masked_sql == "SELECT * FROM T A WHERE A.IDN_BAN = :IDN_BAN"
    assert result.reverse_map == {}


def test_bind_variable_alongside_masked_literal():
    result = mask_sql("SELECT * FROM T A WHERE A.X = 'secret' AND A.Y = :Y_BIND")
    assert ":Y_BIND" in result.masked_sql
    assert ":STR_001" in result.masked_sql
    assert result.reverse_map == {":STR_001": "'secret'"}


# ---------------------------------------------------------------------------
# Reverse-mapping round trip
# ---------------------------------------------------------------------------
def test_reverse_mapping_round_trip():
    original = "SELECT * FROM T A WHERE A.IDN_BAN = 'A123456789' AND A.AMT = 1234567"
    result = mask_sql(original)
    restored = unmask_sql(result.masked_sql, result.reverse_map)
    assert restored == original


def test_unmask_leaves_unknown_placeholder_as_is():
    text = "SELECT * FROM T WHERE X = :STR_001 AND Y = :STR_999"
    restored = unmask_sql(text, {":STR_001": "'known'"})
    assert restored == "SELECT * FROM T WHERE X = 'known' AND Y = :STR_999"


def test_unmask_none_and_empty_do_not_crash():
    assert unmask_sql(None, {}) is None
    assert unmask_sql("", {}) == ""


# ---------------------------------------------------------------------------
# Fallback path (unparseable input must never crash)
# ---------------------------------------------------------------------------
def test_invalid_sql_does_not_crash():
    result = mask_sql("not valid sql at all !!! ###")
    assert isinstance(result.masked_sql, str)


def test_fallback_still_masks_string_literal_in_garbage_input():
    # Deliberately malformed (dangling AND with nothing after) so sqlglot's
    # parser fails and the regex fallback kicks in, but a real string
    # literal is still present and should still be masked.
    result = mask_sql("SELEKT GARBAGE 'A123456789' FRM WHERE AND")
    assert "A123456789" not in result.masked_sql
    assert ":STR_001" in result.masked_sql
    assert result.reverse_map[":STR_001"] == "'A123456789'"


def test_fallback_masks_large_number_and_leaves_small_and_bind_alone():
    result = mask_sql("SELEKT GARBAGE 1234567 AND SMALL 2 AND :BIND FRM WHERE AND")
    assert ":NUM_001" in result.masked_sql
    assert result.reverse_map[":NUM_001"] == "1234567"
    assert " 2 " in result.masked_sql
    assert ":BIND" in result.masked_sql


def test_empty_string_input_does_not_crash():
    result = mask_sql("")
    assert result.masked_sql == ""
    assert result.reverse_map == {}


# ---------------------------------------------------------------------------
# Short-ASCII literal exception (2026-09-16): short codes/wildcard patterns
# stay visible to the AI so it can actually reason about LIKE-prefix /
# year-code style conditions, while anything longer or non-ASCII (real
# personal data) is still always masked.
# ---------------------------------------------------------------------------
def test_short_ascii_literal_kept_unmasked():
    result = mask_sql("SELECT * FROM T A WHERE A.TAX_CD = '55' AND A.HSN_CD = 'H'")
    assert "'55'" in result.masked_sql
    assert "'H'" in result.masked_sql
    assert result.reverse_map == {}
    assert result.literal_hints == {}


def test_short_ascii_like_pattern_with_wildcard_kept_unmasked():
    result = mask_sql("SELECT * FROM T A WHERE A.APPR_DATE LIKE '114%'")
    assert "'114%'" in result.masked_sql


def test_literal_longer_than_threshold_still_masked():
    # 5 chars > default keep threshold of 4.
    result = mask_sql("SELECT * FROM T A WHERE A.CODE = '55R12'")
    assert "'55R12'" not in result.masked_sql
    assert ":STR_001" in result.masked_sql


def test_non_ascii_short_literal_still_masked():
    # 3 Chinese characters, well under the length threshold, but not ASCII
    # -> must still be masked (this is exactly the personal-name case).
    result = mask_sql("SELECT * FROM T A WHERE A.NAME = '王小明'")
    assert "王小明" not in result.masked_sql
    assert ":STR_001" in result.masked_sql


def test_keep_threshold_is_configurable():
    result = mask_sql("SELECT * FROM T A WHERE A.CODE = '12345'", keep_short_ascii_max_len=5)
    assert "'12345'" in result.masked_sql


def test_masked_literal_produces_literal_hint_without_value():
    result = mask_sql("SELECT * FROM T A WHERE A.APPR_DATE LIKE '1140101X%'")
    hint = result.literal_hints[":STR_001"]
    assert hint["kind"] == "string"
    assert hint["wildcard"] == "trailing"
    assert "1140101" not in str(hint)


def test_number_literal_produces_literal_hint():
    result = mask_sql("SELECT * FROM T A WHERE A.AMOUNT = 1234567")
    hint = result.literal_hints[":NUM_001"]
    assert hint["kind"] == "number"
    assert hint["shape"] == "digits"


def test_date_and_timestamp_literals_keep_type_hint_without_exposing_value():
    result = mask_sql(
        "SELECT * FROM T A WHERE A.D = DATE '2026-09-18' "
        "AND A.TS < TIMESTAMP '2026-09-18 12:34:56'"
    )
    assert "2026-09-18" not in result.masked_sql
    assert result.literal_hints[":STR_001"]["oracle_literal_type"] == "date"
    assert result.literal_hints[":STR_002"]["oracle_literal_type"] == "timestamp"
    assert "2026-09-18" not in str(result.literal_hints)


def test_placeholder_numbering_has_no_gap_from_kept_short_literals():
    # A kept short literal must not consume a placeholder number — the next
    # masked literal must still be :STR_001, not :STR_002.
    result = mask_sql("SELECT * FROM T A WHERE A.HSN_CD = 'H' AND A.NAME = '王小明'")
    assert ":STR_001" in result.masked_sql
    assert ":STR_002" not in result.masked_sql
    assert result.reverse_map[":STR_001"] == "'王小明'"


# ---------------------------------------------------------------------------
# deidentify_sql (SQL archive only — stricter than mask_sql)
# ---------------------------------------------------------------------------
def test_deidentify_masks_literals_like_mask_sql():
    text = deidentify_sql("SELECT * FROM T A WHERE A.NAME = '王小明' AND A.ID = 'A123456789'")
    assert "王小明" not in text
    assert "A123456789" not in text


def test_deidentify_strips_non_hint_line_comment():
    text = deidentify_sql("SELECT * FROM T A WHERE A.X = 1 --承辦人：王小明\n")
    assert "承辦人" not in text
    assert "王小明" not in text


def test_deidentify_strips_non_hint_block_comment():
    text = deidentify_sql("SELECT /* 備註：測試資料 */ * FROM T A WHERE A.X = 1")
    assert "備註" not in text


def test_deidentify_keeps_parallel_hint_comment():
    text = deidentify_sql("SELECT /*+ PARALLEL(A,4) */ * FROM T A WHERE A.X = 1")
    assert "PARALLEL" in text


def test_deidentify_redacts_bare_id_like_token_outside_quotes():
    text = deidentify_sql("SELECT A123456789 FROM T A WHERE A.X = 1")
    assert "A123456789" not in text
    assert "[REDACTED]" in text


def test_deidentify_never_raises_on_garbage_input():
    text = deidentify_sql("not valid sql at all !!! ### \x00\x01")
    assert isinstance(text, str)


def test_deidentify_empty_input():
    assert deidentify_sql("") == ""


def test_scrub_invented_placeholders_neutralises_only_model_made_binds():
    # 2026-09-17 blind-spot test: the model invented `:STR_001` for a
    # statement that had no literal, so nothing in reverse_map matched and the
    # masking-internal name leaked to the reviewer.
    original = "SELECT B.TAX_ID FROM HOUT130 B"
    assert scrub_invented_placeholders("WHERE B.TAX_ID = :STR_001", original) == "WHERE B.TAX_ID = :VALUE"
    # A bind the user's own SQL already uses must survive untouched.
    original2 = "SELECT A.X FROM T A WHERE A.Y = :STR_001"
    assert scrub_invented_placeholders("A.Y = :STR_001 AND A.Z = :NUM_007", original2) == "A.Y = :STR_001 AND A.Z = :VALUE"
    assert scrub_invented_placeholders(None, original) is None


def test_deidentify_failed_marker_leaks_nothing_when_reachable():
    # Documents the contract: on any unexpected failure, deidentify_sql must
    # degrade to a fixed marker, never to the raw input.
    assert "SELECT" not in DEIDENTIFY_FAILED_MARKER
    assert "FROM" not in DEIDENTIFY_FAILED_MARKER
