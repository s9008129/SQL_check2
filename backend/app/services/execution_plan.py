"""Deterministic Oracle execution-plan parser for SQL Developer exports.

SQLCheck never connects to Oracle. This module only interprets plan text the
reviewer explicitly pasted/uploaded from the TEST environment. Supported v1
inputs are:
- DBMS_XPLAN / SQL Developer text tables using |...| columns;
- SQL Developer grid exports copied/saved as CSV or tab-delimited text;
- optional SQL*Plus/Autotrace statistics lines.

The output is evidence, not a compliance rule. TABLE ACCESS FULL, HASH JOIN,
large row counts, etc. are reported as observed facts and are never declared
"bad" on their own. Production behavior is never inferred from a test plan.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections.abc import Iterable

from app.schemas import (
    ExecutionPlanAnalysis,
    ExecutionPlanMetric,
    ExecutionPlanObservation,
    ExecutionPlanStep,
    VerifiedRewrite,
)

_PLAN_HASH_RE = re.compile(r"Plan\s+hash\s+value\s*:\s*(\d+)", re.IGNORECASE)
_SQL_ID_RE = re.compile(r"\bSQL_ID\b\s*(?::|=)?\s*([0-9a-z]{5,20})", re.IGNORECASE)
_PREDICATE_START_RE = re.compile(
    r"^\s*(?P<id>\d+)\s*-\s*(?P<kind>access|filter)\s*\((?P<body>.*)$",
    re.IGNORECASE,
)
_SECTION_STOP_RE = re.compile(
    r"^(?:Column Projection Information|Query Block Name|Outline Data|Hint Report|"
    r"Peeked Binds|Note|Statistics)\b",
    re.IGNORECASE,
)

_HEADER_ALIASES = {
    "ID": "id",
    "OPERATION": "operation",
    "NAME": "object_name",
    "OBJECT_NAME": "object_name",
    "ROWS": "estimated_rows",
    "E_ROWS": "estimated_rows",
    "A_ROWS": "actual_rows",
    "STARTS": "starts",
    "COST": "cost",
    "COST_CPU": "cost",
    "BUFFERS": "buffers",
    "READS": "reads",
    "A_TIME": "actual_time",
    "ACTUAL_TIME": "actual_time",
}

_RUNTIME_METRICS = {
    "recursive calls": ("recursive_calls", "Recursive calls"),
    "db block gets": ("db_block_gets", "DB block gets"),
    "consistent gets": ("consistent_gets", "Consistent gets"),
    "physical reads": ("physical_reads", "Physical reads"),
    "redo size": ("redo_size", "Redo size"),
    "bytes sent via sql*net to client": ("sqlnet_bytes_sent", "SQL*Net 傳送位元組"),
    "bytes received via sql*net from client": ("sqlnet_bytes_received", "SQL*Net 接收位元組"),
    "sql*net roundtrips to/from client": ("sqlnet_roundtrips", "SQL*Net roundtrips"),
    "sorts (memory)": ("sorts_memory", "Memory sorts"),
    "sorts (disk)": ("sorts_disk", "Disk sorts"),
    "rows processed": ("rows_processed", "Rows processed"),
}

_FUNCTION_IN_FILTER_RE = re.compile(
    r"\b(SUBSTR|TRUNC|NVL|TO_CHAR|UPPER|LOWER|TRIM)\s*\(",
    re.IGNORECASE,
)


def _normalize_header(value: str) -> str:
    text = value.strip().upper()
    text = text.replace("%", "CPU")
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"[^A-Z0-9]+", "_", text).strip("_")
    return text


def _header_key(value: str) -> str | None:
    normalized = _normalize_header(value)
    if normalized.startswith("COST"):
        return "cost"
    return _HEADER_ALIASES.get(normalized)


def _parse_number(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip().replace(",", "")
    if not raw or raw == "-":
        return None
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([KMGT])?", raw, re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    suffix = (match.group(2) or "").upper()
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "G": 1_000_000_000, "T": 1_000_000_000_000}[suffix]
    return int(number * multiplier)


def _parse_id(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _step_from_cells(headers: list[str], cells: list[str]) -> ExecutionPlanStep | None:
    values: dict[str, str] = {}
    for header, cell in zip(headers, cells, strict=False):
        key = _header_key(header)
        if key:
            values[key] = cell.strip()

    step_id = _parse_id(values.get("id"))
    operation = (values.get("operation") or "").strip()
    if step_id is None or not operation:
        return None

    object_name = (values.get("object_name") or "").strip() or None
    return ExecutionPlanStep(
        id=step_id,
        operation=operation,
        object_name=object_name,
        estimated_rows=_parse_number(values.get("estimated_rows")),
        actual_rows=_parse_number(values.get("actual_rows")),
        starts=_parse_number(values.get("starts")),
        cost=_parse_number(values.get("cost")),
        buffers=_parse_number(values.get("buffers")),
        reads=_parse_number(values.get("reads")),
        actual_time=(values.get("actual_time") or "").strip() or None,
    )


def _parse_pipe_steps(text: str) -> list[ExecutionPlanStep]:
    lines = text.splitlines()
    header_index = None
    headers: list[str] = []
    for index, line in enumerate(lines):
        if line.count("|") < 3:
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        normalized = {_normalize_header(cell) for cell in cells}
        if "ID" in normalized and "OPERATION" in normalized:
            header_index = index
            headers = cells
            break

    if header_index is None:
        return []

    steps: list[ExecutionPlanStep] = []
    started = False
    for line in lines[header_index + 1 :]:
        if "|" not in line:
            if started:
                break
            continue
        cells = [cell for cell in line.split("|")[1:-1]]
        step = _step_from_cells(headers, cells)
        if step is None:
            if started and line.strip().startswith("|"):
                continue
            continue
        started = True
        steps.append(step)
    return steps


def _parse_delimited_steps(text: str) -> list[ExecutionPlanStep]:
    for delimiter in ("\t", ","):
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        except csv.Error:
            continue

        header_index = None
        headers: list[str] = []
        for index, row in enumerate(rows[:40]):
            normalized = {_normalize_header(cell) for cell in row}
            if "ID" in normalized and "OPERATION" in normalized:
                header_index = index
                headers = row
                break
        if header_index is None:
            continue

        steps = []
        for row in rows[header_index + 1 :]:
            if not any(cell.strip() for cell in row):
                if steps:
                    break
                continue
            step = _step_from_cells(headers, row)
            if step is not None:
                steps.append(step)
        if steps:
            return steps
    return []


def _parse_predicates(text: str) -> dict[int, dict[str, list[str]]]:
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if "Predicate Information" in line),
        None,
    )
    if start is None:
        return {}

    found: dict[int, dict[str, list[str]]] = {}
    current: tuple[int, str, str] | None = None

    def finish(item: tuple[int, str, str]) -> None:
        step_id, kind, body = item
        body = body.strip()
        if body.endswith(")"):
            body = body[:-1].rstrip()
        found.setdefault(step_id, {"access": [], "filter": []})[kind].append(body)

    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped or set(stripped) <= {"-"}:
            continue
        if _SECTION_STOP_RE.match(stripped):
            if current is not None:
                finish(current)
            break

        match = _PREDICATE_START_RE.match(line)
        if match:
            if current is not None:
                finish(current)
            current = (
                int(match.group("id")),
                match.group("kind").lower(),
                match.group("body").strip(),
            )
            if current[2].endswith(")"):
                finish(current)
                current = None
            continue

        if current is not None:
            current = (current[0], current[1], f"{current[2]} {stripped}".strip())
            if current[2].endswith(")"):
                finish(current)
                current = None
        elif re.match(r"^\d+\s*-", stripped):
            continue
        elif found:
            break

    if current is not None:
        finish(current)
    return found


def _attach_predicates(steps: list[ExecutionPlanStep], text: str) -> None:
    predicates = _parse_predicates(text)
    for step in steps:
        item = predicates.get(step.id)
        if not item:
            continue
        step.access_predicates.extend(item["access"])
        step.filter_predicates.extend(item["filter"])


def _parse_runtime_metrics(text: str) -> list[ExecutionPlanMetric]:
    metrics: list[ExecutionPlanMetric] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^\s*([0-9][0-9,]*)\s+(.+?)\s*$", line)
        if not match:
            continue
        metric_name = re.sub(r"\s+", " ", match.group(2).strip().lower())
        spec = _RUNTIME_METRICS.get(metric_name)
        if spec is None:
            continue
        key, label = spec
        if key in seen:
            continue
        seen.add(key)
        metrics.append(
            ExecutionPlanMetric(
                key=key,
                label=label,
                value=int(match.group(1).replace(",", "")),
            )
        )
    return metrics


def _runtime_stats_present(steps: Iterable[ExecutionPlanStep], metrics: list[ExecutionPlanMetric]) -> bool:
    if metrics:
        return True
    return any(
        step.actual_rows is not None
        or step.starts is not None
        or step.buffers is not None
        or step.reads is not None
        or step.actual_time is not None
        for step in steps
    )


def _source_label(source: str) -> str:
    if source == "actual":
        return "測試機實際執行計畫"
    if source == "estimated":
        return "測試機預估執行計畫"
    return "執行計畫格式待確認"


def _root_cost(steps: list[ExecutionPlanStep]) -> int | None:
    for step in steps:
        if step.id == 0 and step.cost is not None:
            return step.cost
    return steps[0].cost if steps else None


def _cardinality_ratio(step: ExecutionPlanStep) -> tuple[float, float] | None:
    if step.estimated_rows is None or step.actual_rows is None:
        return None
    starts = max(step.starts or 1, 1)
    actual_per_start = step.actual_rows / starts
    estimated = float(step.estimated_rows)
    if estimated == actual_per_start:
        return (1.0, actual_per_start)
    if estimated == 0 or actual_per_start == 0:
        return (math.inf, actual_per_start)
    return (max(estimated, actual_per_start) / min(estimated, actual_per_start), actual_per_start)


def _observations(
    steps: list[ExecutionPlanStep],
    *,
    expected_cost: int,
    plan_cost: int | None,
    has_runtime_stats: bool,
    verified_rewrites: list[VerifiedRewrite],
) -> list[ExecutionPlanObservation]:
    observations: list[ExecutionPlanObservation] = []

    if plan_cost is not None and plan_cost != expected_cost:
        observations.append(
            ExecutionPlanObservation(
                code="COST_MISMATCH",
                level="review",
                title="輸入 COST 與執行計畫 COST 不一致",
                detail=(
                    f"本次輸入 COST 為 {expected_cost:,}，計畫根節點 COST 為 {plan_cost:,}。"
                    "請確認 SQL 與執行計畫是否來自同一次測試。"
                ),
            )
        )

    for step in steps:
        if "TABLE ACCESS FULL" in step.operation.upper():
            target = f" {step.object_name}" if step.object_name else ""
            observations.append(
                ExecutionPlanObservation(
                    code="TABLE_ACCESS_FULL",
                    level="fact",
                    title="測試計畫包含 TABLE ACCESS FULL",
                    detail=(
                        f"Step {step.id}{target} 使用 TABLE ACCESS FULL。"
                        "這是測試機計畫事實，本身不代表一定需要改成索引存取。"
                    ),
                    step_id=step.id,
                )
            )

        for predicate in step.filter_predicates:
            function_match = _FUNCTION_IN_FILTER_RE.search(predicate)
            if function_match:
                function_name = function_match.group(1).upper()
                observations.append(
                    ExecutionPlanObservation(
                        code="FUNCTION_FILTER_PREDICATE",
                        level="opportunity",
                        title=f"{function_name} 條件出現在 Filter Predicate",
                        detail=(
                            f"Step {step.id} 的 Filter Predicate 可看到 {function_name}()。"
                            "可優先回頭對照 SQL 寫法與 SQLCheck 的既有改善規則。"
                        ),
                        step_id=step.id,
                    )
                )

        if has_runtime_stats:
            ratio_info = _cardinality_ratio(step)
            if ratio_info is not None:
                ratio, actual_per_start = ratio_info
                if ratio >= 10:
                    ratio_text = "超過 10 倍" if math.isinf(ratio) else f"約 {ratio:.1f} 倍"
                    observations.append(
                        ExecutionPlanObservation(
                            code="CARDINALITY_GAP",
                            level="review",
                            title="估計列數與實際列數差距較大",
                            detail=(
                                f"Step {step.id}：E-Rows {step.estimated_rows:,}，"
                                f"A-Rows/Start 約 {actual_per_start:,.0f}，差距 {ratio_text}。"
                                "這可作為測試環境後續確認統計資訊或條件選擇性的證據。"
                            ),
                            step_id=step.id,
                        )
                    )

    has_verified_substr = any(item.rule == "substr_eq_to_like" for item in verified_rewrites)
    if has_verified_substr:
        substr_step = next(
            (
                step
                for step in steps
                if any(re.search(r"\bSUBSTR\s*\(", p, re.IGNORECASE) for p in step.filter_predicates)
            ),
            None,
        )
        if substr_step is not None:
            observations.append(
                ExecutionPlanObservation(
                    code="VERIFIED_REWRITE_PLAN_MATCH",
                    level="opportunity",
                    title="已有可確認改寫，也有測試計畫證據可對照",
                    detail=(
                        f"SQLCheck 已能確認 SUBSTR→LIKE 的等價改寫；測試機計畫 Step {substr_step.id} "
                        "同時顯示 SUBSTR 出現在 Filter Predicate。建議在測試機重跑改寫後 SQL，"
                        "再比較 COST、計畫與實際統計，而不是直接推定一定變快。"
                    ),
                    step_id=substr_step.id,
                )
            )

    return observations


def unrecognized(message: str = "未辨識到可解析的 Oracle 執行計畫表格。") -> ExecutionPlanAnalysis:
    return ExecutionPlanAnalysis(
        recognized=False,
        source="unknown",
        source_label=_source_label("unknown"),
        message=message,
    )


def analyze(
    plan_text: str,
    *,
    expected_cost: int,
    verified_rewrites: list[VerifiedRewrite] | None = None,
) -> ExecutionPlanAnalysis:
    """Parse one SQL Developer/DBMS_XPLAN execution-plan text deterministically."""
    text = plan_text.strip()
    if not text:
        return unrecognized("執行計畫內容為空。")

    steps = _parse_pipe_steps(text) or _parse_delimited_steps(text)
    if not steps:
        return unrecognized(
            "未辨識到 SQL Developer／DBMS_XPLAN 的 Id、Operation 欄位。"
            "請貼上完整執行計畫，或上傳 TXT／CSV。"
        )

    _attach_predicates(steps, text)
    runtime_metrics = _parse_runtime_metrics(text)
    has_runtime_stats = _runtime_stats_present(steps, runtime_metrics)
    source = "actual" if has_runtime_stats else "estimated"
    plan_cost = _root_cost(steps)
    cost_matches_input = None if plan_cost is None else plan_cost == expected_cost

    plan_hash_match = _PLAN_HASH_RE.search(text)
    sql_id_match = _SQL_ID_RE.search(text)
    observations = _observations(
        steps,
        expected_cost=expected_cost,
        plan_cost=plan_cost,
        has_runtime_stats=has_runtime_stats,
        verified_rewrites=verified_rewrites or [],
    )

    if source == "actual":
        message = (
            "已辨識測試機實際執行計畫／執行統計。這些資料可用來找優先驗證點，"
            "但不代表正式機會採用相同計畫。"
        )
    else:
        message = (
            "已辨識測試機預估執行計畫。可用來理解 Optimizer 的預估路徑；"
            "若要比較真實執行差異，建議在測試機使用 SQL Developer Autotrace。"
        )

    return ExecutionPlanAnalysis(
        recognized=True,
        source=source,
        source_label=_source_label(source),
        plan_hash_value=plan_hash_match.group(1) if plan_hash_match else None,
        sql_id=sql_id_match.group(1) if sql_id_match else None,
        step_count=len(steps),
        plan_cost=plan_cost,
        cost_matches_input=cost_matches_input,
        has_runtime_stats=has_runtime_stats,
        runtime_metrics=runtime_metrics,
        steps=steps,
        observations=observations,
        message=message,
    )
