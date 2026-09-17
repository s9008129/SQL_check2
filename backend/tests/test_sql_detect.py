from app.services.sql_detect import detect_sql


def test_sql_file_wholesale():
    r = detect_sql("SELECT * FROM T A WHERE A.X=1", ".sql")
    assert r.found is True
    assert r.statement_count == 1
    assert "已辨識 1 段 SQL" in r.message


def test_plain_text_with_prose_and_sql():
    text = "以下為本次申請之查詢內容：\n\nSELECT A.X FROM T A WHERE A.Y = 1\n\n如有問題請洽承辦人。"
    r = detect_sql(text, ".txt")
    assert r.found is True
    assert "SELECT A.X" in r.sql
    assert "承辦人" not in r.sql


def test_plain_text_multi_statement_not_truncated_at_blank_line():
    text = "SELECT A.X\nFROM T A\n\nWHERE A.Y = 1"
    r = detect_sql(text, ".txt")
    assert r.found is True
    assert "WHERE A.Y = 1" in r.sql


def test_plain_text_multiple_consecutive_blank_lines_not_truncated():
    """Regression for a real production case (LND_台糖馬稠後產業園區土地課稅
    情形.docx, 2026-09-15): the DOCX had 4 consecutive blank lines between
    the last JOIN's ON clause and the WHERE clause. A single-blank-line-only
    paragraph splitter turned that run of blank lines into an empty leading
    paragraph that failed the continuation check, silently dropping the
    WHERE clause and everything after it — which then caused a false R002
    "缺少 WHERE 條件" BLOCK downstream even though the SQL genuinely has a
    WHERE clause."""
    text = (
        "SELECT A.X\n"
        "FROM T A\n"
        "LEFT JOIN U B\n"
        "ON A.K = B.K\n"
        "\n\n\n\n"
        "WHERE A.Y = '114'"
    )
    r = detect_sql(text, ".txt")
    assert r.found is True
    assert "WHERE A.Y" in r.sql


def test_plain_text_trailing_prose_after_multiple_blank_lines_still_trimmed():
    text = (
        "SELECT A.X FROM T A WHERE A.Y = 1"
        "\n\n\n"
        "如有問題請洽承辦人。"
    )
    r = detect_sql(text, ".txt")
    assert r.found is True
    assert "承辦人" not in r.sql


def test_plain_text_no_sql_found():
    r = detect_sql("這是一份普通的文件，沒有任何 SQL 內容。", ".txt")
    assert r.found is False
    assert r.statement_count == 0
    assert "未辨識到可檢核的 SQL" in r.message


def test_markdown_sql_fence_priority():
    text = (
        "# 說明\n\n這是文件內容。\n\n```sql\nSELECT A.X FROM T A WHERE A.Y=1\n```\n\n"
        "```text\n這不是 SQL\n```\n"
    )
    r = detect_sql(text, ".md")
    assert r.found is True
    assert "SELECT A.X" in r.sql
    assert "這不是 SQL" not in r.sql


def test_markdown_generic_fence_used_when_no_sql_fence():
    text = "```\nSELECT A.X FROM T A WHERE A.Y=1\n```\n"
    r = detect_sql(text, ".markdown")
    assert r.found is True
    assert "SELECT A.X" in r.sql


def test_markdown_prose_headings_excluded():
    text = "# 申請單說明\n\n```sql\nSELECT A.X FROM T A WHERE A.Y=1\n```\n"
    r = detect_sql(text, ".md")
    assert "申請單說明" not in r.sql


def test_csv_single_cell_sql():
    text = 'id,sql\n1,"SELECT A.X FROM T A WHERE A.Y=1"\n'
    r = detect_sql(text, ".csv")
    assert r.found is True
    assert "SELECT A.X" in r.sql


def test_csv_one_row_per_sql():
    text = "SELECT A.X FROM T A WHERE A.Y=1\nSELECT B.X FROM T2 B WHERE B.Y=2\n"
    r = detect_sql(text, ".csv")
    assert r.found is True
    assert r.statement_count == 2


def test_csv_plain_data_not_misdetected():
    text = "id,name,amount\n1,Alice,100\n2,Bob,200\n"
    r = detect_sql(text, ".csv")
    assert r.found is False


def test_csv_comma_inside_sql_string_literal_handled_by_csv_module():
    text = 'id,sql\n1,"SELECT A.X FROM T A WHERE A.NOTE = ''hello, world''"\n'
    r = detect_sql(text, ".csv")
    assert r.found is True


def test_multi_statement_message_wording():
    text = "SELECT * FROM T1 WHERE X=1;\nSELECT * FROM T2 WHERE Y=2;\nSELECT * FROM T3 WHERE Z=3;"
    r = detect_sql(text, ".sql")
    assert r.statement_count == 3
    assert "已辨識 3 段 SQL" in r.message


def test_nested_subquery_with_blank_lines_is_one_statement():
    # 2026-09-17 production DOCX: a three-level nested query, hand-formatted
    # with blank lines after each `FROM (`. The free-text scanner used to cut
    # it at every SELECT and inject `;` inside the open parens, producing five
    # incomplete fragments.
    text = (
        "SELECT T3.*\nFROM\n  (\n\nSELECT T1.X, T2.Y\n    FROM\n      (\n        /*抓出面積*/\n\nSELECT M.X FROM Q.T604 M\n"
        "            WHERE M.DATA_YR = '110'\n      ) T1,\n      (\n\nSELECT * FROM Q.T607 WHERE DATA_YR = '114'\n      ) T2\n"
        "    WHERE T1.X = T2.X\n  ) T3;\n\n如有問題請洽承辦人。"
    )
    r = detect_sql(text, ".docx")
    assert r.found is True
    assert r.statement_count == 1
    assert "(;" not in r.sql
    assert r.sql.count(";") == 1
    assert "如有問題" not in r.sql


def test_two_real_statements_still_split_after_paren_fix():
    text = "SELECT A.X FROM T A WHERE A.Y = (SELECT MAX(B.Y) FROM T B)\n\nSELECT C.Z FROM T C WHERE C.W = 1"
    r = detect_sql(text, ".txt")
    assert r.statement_count == 2


def test_empty_text_not_found():
    r = detect_sql("", ".txt")
    assert r.found is False
