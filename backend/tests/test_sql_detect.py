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


def test_empty_text_not_found():
    r = detect_sql("", ".txt")
    assert r.found is False
