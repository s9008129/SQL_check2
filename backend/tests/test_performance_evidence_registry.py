from pathlib import Path

import yaml

from app.services import performance_evidence
from app.services.pattern_selector import PATTERN_CATALOG_PATH

_REGISTRY_PATH = Path(__file__).parents[1] / "app" / "knowledge" / "performance_evidence.yaml"


def test_oracle11g_evidence_registry_is_versioned_official_and_unique():
    data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert data["registry_version"] == 1
    assert data["target_database"]["vendor"] == "oracle"
    assert data["target_database"]["major_version"] == "11g"

    ids = [entry["id"] for entry in data["evidence"]]
    assert len(ids) == len(set(ids))
    assert ids

    for entry in data["evidence"]:
        assert entry["source_type"] == "oracle_official"
        assert entry["source_label"] == "Oracle Database 11g 官方文件"
        assert entry["source_url"].startswith("https://docs.oracle.com/")
        assert entry["strength"] in {"strong", "conditional"}
        assert entry["claim_zh_tw"].strip()
        assert entry["caveat_zh_tw"].strip()


def test_every_pattern_evidence_ref_exists_in_registry():
    registry = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    evidence_ids = {entry["id"] for entry in registry["evidence"]}
    catalog = yaml.safe_load(PATTERN_CATALOG_PATH.read_text(encoding="utf-8"))

    referenced = {
        evidence_id
        for pattern in catalog["patterns"]
        for evidence_id in pattern.get("evidence_refs", [])
    }
    assert referenced
    assert referenced <= evidence_ids


def test_registry_urls_are_audit_only_not_api_fields():
    entry = performance_evidence.get_evidence_entry("ORACLE11G_TRANSFORMED_COLUMN")
    assert entry is not None
    assert "source_url" in entry
    # The response model deliberately has no source_url field.
    model = performance_evidence._build_item(
        "ORACLE11G_TRANSFORMED_COLUMN",
        pattern_id="SUBSTR_EQ_TO_LIKE",
        statement_indexes=(0,),
        applicability="synthetic",
    )
    assert "source_url" not in model.model_dump()
