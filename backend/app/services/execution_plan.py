"""Deterministic Oracle execution-plan parser for SQL Developer exports.

SQLCheck never connects to Oracle. This module only interprets plan text the
reviewer explicitly pasted/uploaded. The owner-confirmed production workflow uses
SQL Developer F10 Explain Plan against the formal Oracle database. Supported v1
inputs are:
- DBMS_XPLAN / SQL Developer text tables using |...| columns;
- SQL Developer grid exports copied/saved as CSV or tab-delimited text;
- optional SQL*Plus/Autotrace statistics lines.

The output is evidence, not a compliance rule. TABLE ACCESS FULL, HASH JOIN,
large row counts, etc. are reported as observed facts and are never declared
"bad" on their own. F10 is an estimated plan from the formal database
environment, not proof that the SQL was actually executed or that runtime
time/I/O matched the estimate.

The raw plan is never sent to the LLM. build_ai_context converts the
deterministic parse result into a small, literal-free summary so the plan can
improve AI prioritization without exposing predicate values or turning the LLM
into the execution-plan authority.
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

_AI_FILTER_FUNCTION_RE = re.compile(
    r"\b(SUBSTR|TRUNC|NVL|TO_CHAR|UPPER|LOWER|TRIM|LTRIM|RTRIM)\s*\(",
    re.IGNORECASE,
)
_AI_CONTEXT_MAX_STEPS = 8
_AI_CONTEXT_MAX_SIGNALS = 12
_AI_CONTEXT_MAX_RUNTIME_METRICS = 8

_HEADER_ALIASES = {
    "ID": "id",
    "OPERATION": "operation",
    "OPTIONS": "options",
    "NAME": "object_name",
    "OBJECT_NAME": "object_name",
    "ROWS": "estimated_rows",
    "CARDINALITY": "estimated_rows",
    "E_ROWS": "estimated_rows",
    "A_ROWS": "actual_rows",
    "STARTS": "starts",
    "COST": "cost",
    "COST_CPU": "cost",
    "BUFFERS": "buffers",
    "READS": "reads",
    "A_TIME": "actual_time",
    "ACTUAL_TIME": "actual_time",
    "ACCESS_PREDICATES": "access_predicates",
    "FILTER_PREDICATES": "filter_predicates",
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

    options = (values.get("options") or "").strip() or None
    object_name = (values.get("object_name") or "").strip() or None
    access_predicate = (values.get("access_predicates") or "").strip()
    filter_predicate = (values.get("filter_predicates") or "").strip()
    return ExecutionPlanStep(
        id=step_id,
        operation=operation,
        options=options,
        object_name=object_name,
        estimated_rows=_parse_number(values.get("estimated_rows")),
        actual_rows=_parse_number(values.get("actual_rows")),
        starts=_parse_number(values.get("starts")),
        cost=_parse_number(values.get("cost")),
        buffers=_parse_number(values.get("buffers")),
        reads=_parse_number(values.get("reads")),
        actual_time=(values.get("actual_time") or "").strip() or None,
        access_predicates=[access_predicate] if access_predicate else [],
        filter_predicates=[filter_predicate] if filter_predicate else [],
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
        for predicate in item["access"]:
            if predicate not in step.access_predicates:
                step.access_predicates.append(predicate)
        for predicate in item["filter"]:
            if predicate not in step.filter_predicates:
                step.filter_predicates.append(predicate)


def _operation_label(step: ExecutionPlanStep) -> str:
    """Combine PLAN_TABLE OPERATION + OPTIONS as one observable operation."""
    return f"{step.operation} {step.options or ''}".strip()


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
        return "含實際執行統計的執行計畫"
    if source == "estimated":
        return "正式資料庫 F10 Explain Plan（估算）"
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
        operation_label = _operation_label(step)
        if "TABLE ACCESS FULL" in operation_label.upper():
            target = f" {step.object_name}" if step.object_name else ""
            observations.append(
                ExecutionPlanObservation(
                    code="TABLE_ACCESS_FULL",
                    level="fact",
                    title="測試計畫包含 TABLE ACCESS FULL",
                    detail=(
                        f"Step {step.id}{target} 使用 {operation_label}。"
                        "這是提供的 Plan 事實，本身不代表一定需要改成索引存取。"
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
                                "這可作為後續確認統計資訊或條件選擇性的證據。"
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
                    title="已有可確認改寫，也有正式 Plan 證據可對照",
                    detail=(
                        f"SQLCheck 已能確認 SUBSTR→LIKE 的等價改寫；提供的 Plan Step {substr_step.id} "
                        "同時顯示 SUBSTR 出現在 Filter Predicate。若依中心流程在正式資料庫以 F10 "
                        "比較改寫前後 Explain Plan，可再對照 COST 與 access path；F10 仍是估算，"
                        "不能直接推定實際執行一定變快。"
                    ),
                    step_id=substr_step.id,
                )
            )

    return observations


def _normalized_object_name(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().upper().split(".")[-1]


def build_ai_context(
    plan: ExecutionPlanAnalysis | None,
    *,
    allowed_tables: Iterable[str] = (),
) -> dict[str, object] | None:
    """Return a bounded, literal-free plan summary for the AI.

    The LLM gets enough deterministic facts to prioritize advice (costly
    operations, full-table reads, function-bearing filters, cardinality gaps)
    but never receives the raw plan, predicates, SQL_ID, Plan Hash, or object
    names that are not already present in the submitted SQL.
    """

    if plan is None or not plan.recognized:
        return None

    allowed = {
        normalized
        for table in allowed_tables
        if (normalized := _normalized_object_name(table)) is not None
    }

    ranked_steps = sorted(
        (step for step in plan.steps if step.cost is not None),
        key=lambda step: (-(step.cost or 0), step.id),
    )[:_AI_CONTEXT_MAX_STEPS]

    priority_steps: list[dict[str, object]] = []
    for step in ranked_steps:
        normalized_object = _normalized_object_name(step.object_name)
        safe_object_name = step.object_name if normalized_object in allowed else None
        functions = sorted(
            {
                match.group(1).upper()
                for predicate in step.filter_predicates
                for match in _AI_FILTER_FUNCTION_RE.finditer(predicate)
            }
        )
        priority_steps.append(
            {
                "id": step.id,
                "operation": step.operation,
                "options": step.options,
                "object_name": safe_object_name,
                "cost": step.cost,
                "estimated_rows": step.estimated_rows,
                "actual_rows": step.actual_rows,
                "starts": step.starts,
                "filter_functions": functions,
            }
        )

    signals = [
        {
            "code": item.code,
            "level": item.level,
            "step_id": item.step_id,
        }
        for item in plan.observations[:_AI_CONTEXT_MAX_SIGNALS]
    ]

    runtime_metrics = [
        {
            "key": metric.key,
            "value": metric.value,
        }
        for metric in plan.runtime_metrics[:_AI_CONTEXT_MAX_RUNTIME_METRICS]
    ]

    return {
        "source": plan.source,
        "plan_cost": plan.plan_cost,
        "cost_matches_input": plan.cost_matches_input,
        "step_count": plan.step_count,
        "has_runtime_stats": plan.has_runtime_stats,
        "priority_steps": priority_steps,
        "signals": signals,
        "runtime_metrics": runtime_metrics,
    }


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
            "已辨識含實際執行統計的 Plan。SQLCheck 會把 runtime 欄位當作實際證據使用；"
            "來源環境仍以使用者的作業紀錄為準。"
        )
    else:
        message = (
            "已辨識正式資料庫 F10 Explain Plan（估算）。這反映正式庫 Optimizer 在 Explain 當下"
            "選出的預估路徑；F10 不代表 SQL 已實際執行，因此不能把預估 COST／Rows 當成實際耗時、"
            "實際列數或 I/O。"
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
