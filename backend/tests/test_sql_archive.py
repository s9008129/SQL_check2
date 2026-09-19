"""Tests for the de-identified SQL archive (app/services/sql_archive.py).

Focus: the archive record must never contain the application number, raw
SQL literal values, or any way to recover them; writing must be resilient
to a disabled setting, a missing directory, and an unwritable path.
"""

from __future__ import annotations

import dataclasses
import json

from app.schemas import (
    AdviceItem,
    AiResult,
    ComplianceResult,
    Finding,
    ImprovementResult,
    RuleRow,
    SuggestedSql,
)
from app.services import sql_archive
from app.services.sql_parser import parse_sql_text
from app.settings import get_settings


def _base_kwargs(sql: str, cost: int = 68420):
    parsed = parse_sql_text(sql)
    compliance = ComplianceResult(status="PASS", label="符合中心規範", notice_count=0, block_count=0)
    rule_rows = [RuleRow(rule_id="R001", name="COST", status="PASS", evidence="1000", note="")]
    findings: list[Finding] = []
    improvement = ImprovementResult(score=10, level="GOOD", label="目前良好", color="green", breakdown=[])
    ai_result = AiResult(
        status="ok",
        summary="測試摘要",
        advice=[AdviceItem(title="調整寫法", explanation="說明", impact="medium")],
        suggested_sql=SuggestedSql(available=False, reason="測試原因"),
        estimated_improvement_pct=None,
    )
    return {
        "parsed": parsed,
        "compliance": compliance,
        "rule_rows": rule_rows,
        "findings": findings,
        "improvement": improvement,
        "ai_result": ai_result,
        "cost": cost,
    }


# ---------------------------------------------------------------------------
# build_record
# ---------------------------------------------------------------------------
def test_build_record_never_contains_application_no_field():
    record = sql_archive.build_record(**_base_kwargs("SELECT * FROM T A WHERE A.NAME = '王小明'"))
    assert "application_no" not in record
    assert "applicant" not in record


def test_build_record_deidentifies_literal_values():
    record = sql_archive.build_record(
        **_base_kwargs("SELECT * FROM T A WHERE A.NAME = '王小明' AND A.ID = 'A123456789'")
    )
    dumped = json.dumps(record, ensure_ascii=False)
    assert "王小明" not in dumped
    assert "A123456789" not in dumped


def test_build_record_never_contains_reverse_map_or_filename():
    record = sql_archive.build_record(**_base_kwargs("SELECT * FROM T A WHERE A.X = 1"))
    dumped = json.dumps(record)
    assert "reverse_map" not in dumped
    assert "filename" not in dumped


def test_build_record_is_json_serializable():
    record = sql_archive.build_record(**_base_kwargs("SELECT * FROM T A WHERE A.X = 1"))
    # Must not raise.
    json.dumps(record, ensure_ascii=False)


def test_build_record_includes_expected_top_level_fields():
    record = sql_archive.build_record(**_base_kwargs("SELECT * FROM T A WHERE A.X = 1"))
    for key in (
        "schema_version",
        "id",
        "ts",
        "sql_deidentified",
        "sql_fingerprint",
        "sql_chars",
        "statement_count",
        "statements",
        "cost",
        "compliance",
        "rules",
        "findings",
        "improvement",
        "ai",
    ):
        assert key in record


def test_build_record_includes_rewrite_outcome():
    kwargs = _base_kwargs("SELECT A.X FROM T A WHERE A.Y = 1")
    kwargs["ai_result"] = AiResult(
        status="ok",
        summary="s",
        advice=[],
        suggested_sql=SuggestedSql(available=False, reason="r", outcome="not_needed"),
        estimated_improvement_pct=0,
    )
    record = sql_archive.build_record(**kwargs)
    assert record["ai"]["rewrite_outcome"] == "not_needed"


def test_build_record_suggested_sql_deidentified_when_available():
    kwargs = _base_kwargs("SELECT A.X FROM T A WHERE A.Y = 1")
    kwargs["ai_result"] = AiResult(
        status="ok",
        summary="s",
        advice=[],
        suggested_sql=SuggestedSql(
            available=True, reason="r", sql="SELECT A.X FROM T A WHERE A.NAME = '王小明'"
        ),
        estimated_improvement_pct=30,
    )
    record = sql_archive.build_record(**kwargs)
    assert record["ai"]["suggested_available"] is True
    assert "王小明" not in record["ai"]["suggested_sql_deidentified"]


def test_build_record_fingerprint_stable_for_same_deidentified_sql():
    r1 = sql_archive.build_record(**_base_kwargs("SELECT * FROM T A WHERE A.X = 1"))
    r2 = sql_archive.build_record(**_base_kwargs("select * from t a where a.x = 1".upper()))
    assert r1["sql_fingerprint"] == r2["sql_fingerprint"]




def test_build_record_prefers_submitted_sql_for_future_learning_archive():
    # Even if parser output is incomplete in a future edge case, the archive
    # should de-identify the submitted text itself rather than silently store
    # an empty SQL sample.
    record = sql_archive.build_record(
        **_base_kwargs("SELECT A.X FROM T A WHERE A.X = 1"),
        sql_text="SELEKT BROKEN WHERE NAME = '王小明'",
    )
    assert record["sql_deidentified"]
    assert "王小明" not in record["sql_deidentified"]

# ---------------------------------------------------------------------------
# append_record / record_analysis (I/O)
# ---------------------------------------------------------------------------
def test_append_record_writes_one_jsonl_line(tmp_path):
    settings = get_settings()
    settings = dataclasses.replace(
        settings, archive=dataclasses.replace(settings.archive, enabled=True, dir=tmp_path / "archive")
    )
    record = {"schema_version": 1, "id": "x"}
    sql_archive.append_record(record, settings)

    files = list((tmp_path / "archive").glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == record


def test_append_record_appends_multiple_lines(tmp_path):
    settings = get_settings()
    settings = dataclasses.replace(
        settings, archive=dataclasses.replace(settings.archive, enabled=True, dir=tmp_path / "archive")
    )
    sql_archive.append_record({"id": "a"}, settings)
    sql_archive.append_record({"id": "b"}, settings)

    files = list((tmp_path / "archive").glob("*.jsonl"))
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["id"] for line in lines] == ["a", "b"]


def test_append_record_disabled_writes_nothing(tmp_path):
    settings = get_settings()
    settings = dataclasses.replace(
        settings, archive=dataclasses.replace(settings.archive, enabled=False, dir=tmp_path / "archive")
    )
    sql_archive.append_record({"id": "x"}, settings)
    assert not (tmp_path / "archive").exists()


def test_append_record_never_raises_when_directory_is_unwritable(tmp_path):
    # Point the archive dir at a path that already exists as a *file*, so
    # `mkdir(parents=True, exist_ok=True)` fails with NotADirectoryError.
    blocked = tmp_path / "blocked_file"
    blocked.write_text("not a directory", encoding="utf-8")
    settings = get_settings()
    settings = dataclasses.replace(
        settings, archive=dataclasses.replace(settings.archive, enabled=True, dir=blocked / "archive")
    )
    # Must not raise.
    sql_archive.append_record({"id": "x"}, settings)


def test_record_analysis_disabled_skips_build_and_write(tmp_path, monkeypatch):
    settings = get_settings()
    settings = dataclasses.replace(
        settings, archive=dataclasses.replace(settings.archive, enabled=False, dir=tmp_path / "archive")
    )

    def _boom(**kwargs):
        raise AssertionError("build_record must not be called when archive is disabled")

    monkeypatch.setattr(sql_archive, "build_record", _boom)
    sql_archive.record_analysis(settings=settings, **_base_kwargs("SELECT * FROM T A WHERE A.X = 1"))


def test_record_analysis_never_raises_on_build_failure(tmp_path, monkeypatch):
    settings = get_settings()
    settings = dataclasses.replace(
        settings, archive=dataclasses.replace(settings.archive, enabled=True, dir=tmp_path / "archive")
    )

    def _boom(**kwargs):
        raise RuntimeError("simulated build failure")

    monkeypatch.setattr(sql_archive, "build_record", _boom)
    # Must not raise.
    sql_archive.record_analysis(settings=settings, **_base_kwargs("SELECT * FROM T A WHERE A.X = 1"))
    assert not (tmp_path / "archive").exists()


def test_record_analysis_end_to_end_writes_deidentified_record(tmp_path):
    settings = get_settings()
    settings = dataclasses.replace(
        settings, archive=dataclasses.replace(settings.archive, enabled=True, dir=tmp_path / "archive")
    )
    sql_archive.record_analysis(
        settings=settings, **_base_kwargs("SELECT * FROM T A WHERE A.NAME = '王小明'")
    )
    files = list((tmp_path / "archive").glob("*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "王小明" not in content
