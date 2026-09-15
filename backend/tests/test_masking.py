from app.services.masking import mask_sql, unmask_sql


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
