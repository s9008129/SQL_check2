"""Contract guard: the frontend's TypeScript mirror of the execution-plan
response models must stay field-for-field identical to the Pydantic models.

2026-09-22 P0 schema drift: the frontend used to miss `options`, so a SQL
Developer PLAN_TABLE export ("TABLE ACCESS" + "FULL") reached the UI as a bare
"TABLE ACCESS". `tsc --noEmit` cannot catch that kind of drift — an object
literal that is missing a field is still a valid TypeScript shape — so this
test compares the two contracts directly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.schemas import (
    ExecutionPlanAnalysis,
    ExecutionPlanMetric,
    ExecutionPlanObservation,
    ExecutionPlanStep,
)

_API_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "api.ts"
_INTERFACE_RE = re.compile(
    r"^export interface (?P<name>\w+) \{(?P<body>.*?)^\}$",
    re.DOTALL | re.MULTILINE,
)
_FIELD_RE = re.compile(r"^  (?P<name>[A-Za-z_]\w*)\??:", re.MULTILINE)


def _frontend_interface_fields(interface_name: str) -> list[str]:
    text = _API_TS.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    match = _INTERFACE_RE.search(text)
    while match is not None and match.group("name") != interface_name:
        match = _INTERFACE_RE.search(text, match.end())
    assert match is not None, f"{interface_name} not found in {_API_TS}"
    return _FIELD_RE.findall(match.group("body"))


@pytest.mark.parametrize(
    ("interface_name", "model"),
    [
        ("ExecutionPlanMetric", ExecutionPlanMetric),
        ("ExecutionPlanStep", ExecutionPlanStep),
        ("ExecutionPlanObservation", ExecutionPlanObservation),
        ("ExecutionPlanAnalysis", ExecutionPlanAnalysis),
    ],
)
def test_frontend_interface_mirrors_backend_model(interface_name: str, model: type[BaseModel]) -> None:
    assert _frontend_interface_fields(interface_name) == list(model.model_fields)
