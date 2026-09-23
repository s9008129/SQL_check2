"""Deterministic detectors for recurring Oracle SQL optimization patterns.

These detectors were added after reviewing de-identified recurring structures
from owner-provided local-tax SQL (land tax and vehicle-license tax). They
detect shapes, never business meaning or measured performance.

Important boundaries:
- Returned flags are advisory facts only. They do not change compliance or
  the existing 改善指數.
- A detected pattern is not permission to auto-rewrite it. Only
  rewrite_rules.py may prove result-preserving rewrites.
- No detector claims index usage, execution plan behavior, production
  cardinality, or measured speedup.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from sqlglot import exp

DIALECT = "oracle"

_COMPARISON_TYPES = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
_CONCAT_TYPES = tuple(
    cls
    for cls in (getattr(exp, "DPipe", None), getattr(exp, "Concat", None))
    if isinstance(cls, type)
)


def _nearest_select(node: exp.Expression) -> exp.Select | None:
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.Select):
            return parent
        parent = parent.parent
    return None


def _direct_tables(select: exp.Select) -> list[exp.Table]:
    """Tables whose nearest SELECT ancestor is exactly this SELECT."""
    return [table for table in select.find_all(exp.Table) if _nearest_select(table) is select]


def _direct_columns(select: exp.Select) -> list[exp.Column]:
    """Columns whose nearest SELECT ancestor is exactly this SELECT."""
    return [column for column in select.find_all(exp.Column) if _nearest_select(column) is select]


def _table_aliases(select: exp.Select) -> set[str]:
    return {
        table.alias_or_name.upper()
        for table in _direct_tables(select)
        if table.alias_or_name
    }


def _table_names(select: exp.Select) -> tuple[str, ...]:
    return tuple(sorted({table.name.upper() for table in _direct_tables(select) if table.name}))


def _ancestor_aliases(select: exp.Select) -> set[str]:
    aliases: set[str] = set()
    parent = select.parent
    while parent is not None:
        if isinstance(parent, exp.Select):
            aliases.update(_table_aliases(parent))
        parent = parent.parent
    return aliases


def _is_correlated(select: exp.Select) -> bool:
    own_aliases = _table_aliases(select)
    outer_aliases = _ancestor_aliases(select)
    if not outer_aliases:
        return False
    for column in _direct_columns(select):
        table = (column.table or "").upper()
        if table and table not in own_aliases and table in outer_aliases:
            return True
    return False


def _condition_roots(select: exp.Select) -> list[exp.Expression]:
    roots: list[exp.Expression] = []
    where = select.args.get("where")
    if where is not None:
        roots.append(where.this)
    having = select.args.get("having")
    if having is not None:
        roots.append(having.this)
    for join in select.args.get("joins") or ():
        on = join.args.get("on")
        if on is not None:
            roots.append(on)
    return roots


def _maximal_or_nodes(root: exp.Expression):
    for node in root.find_all(exp.Or):
        parent = node.parent
        while isinstance(parent, exp.Paren):
            parent = parent.parent
        if not isinstance(parent, exp.Or):
            yield node


def _column_key(column: exp.Column) -> str:
    table = (column.table or "").upper()
    name = (column.name or "").upper()
    return f"{table}.{name}" if table else name


def _has_cross_column_or(tree: exp.Expression) -> bool:
    for select in tree.find_all(exp.Select):
        for root in _condition_roots(select):
            for or_node in _maximal_or_nodes(root):
                columns = {_column_key(column) for column in or_node.find_all(exp.Column)}
                if len(columns) > 1:
                    return True
    return False


def _contains_concat(expr: exp.Expression) -> bool:
    return bool(_CONCAT_TYPES) and any(isinstance(node, _CONCAT_TYPES) for node in expr.walk())


def _has_string_concat_predicate(tree: exp.Expression) -> bool:
    """Condition uses string concatenation with at least one real column."""
    for select in tree.find_all(exp.Select):
        for root in _condition_roots(select):
            for node in root.walk():
                if not isinstance(node, _COMPARISON_TYPES):
                    continue
                for side in (node.this, node.expression):
                    if side is not None and _contains_concat(side) and side.find(exp.Column) is not None:
                        return True
    return False


def _column_tables(expr: exp.Expression | None) -> set[str]:
    if expr is None:
        return set()
    return {(column.table or "").upper() for column in expr.find_all(exp.Column) if column.table}


def _is_plain_column(expr: exp.Expression | None) -> bool:
    return isinstance(expr, exp.Column)


def _has_column_expression_join(tree: exp.Expression) -> bool:
    """Two table aliases are compared and at least one side transforms a column."""
    for select in tree.find_all(exp.Select):
        for root in _condition_roots(select):
            for node in root.find_all(exp.EQ):
                left = node.this
                right = node.expression
                left_tables = _column_tables(left)
                right_tables = _column_tables(right)
                if not left_tables or not right_tables:
                    continue
                if not any(a != b for a in left_tables for b in right_tables):
                    continue
                if not (_is_plain_column(left) and _is_plain_column(right)):
                    return True
    return False


def _aggregate_names(select: exp.Select) -> set[str]:
    names: set[str] = set()
    agg_type = getattr(exp, "AggFunc", ())
    for expression in select.expressions:
        for func in expression.find_all(exp.Func):
            if isinstance(func, agg_type):
                names.add(type(func).__name__.upper())
    return names


def _is_scalar_subquery(select: exp.Select) -> bool:
    """Best-effort: exclude inline views and CTEs from scalar-subquery patterns."""
    parent = select.parent
    while parent is not None and not isinstance(parent, exp.Select):
        if isinstance(parent, (exp.From, exp.Join, exp.CTE)):
            return False
        parent = parent.parent
    return parent is not None


def _has_repeated_correlated_max_subquery(tree: exp.Expression) -> bool:
    by_source: Counter[tuple[str, ...]] = Counter()
    for select in tree.find_all(exp.Select):
        if not _is_scalar_subquery(select) or select.args.get("group") is not None:
            continue
        if _aggregate_names(select) != {"MAX"} or not _is_correlated(select):
            continue
        source = _table_names(select)
        if source:
            by_source[source] += 1
    return any(count >= 2 for count in by_source.values())


def _has_repeated_scalar_aggregate(tree: exp.Expression) -> bool:
    by_source: defaultdict[tuple[str, ...], list[set[str]]] = defaultdict(list)
    for select in tree.find_all(exp.Select):
        if not _is_scalar_subquery(select) or select.args.get("group") is not None:
            continue
        aggregate_names = _aggregate_names(select)
        if not aggregate_names:
            continue
        if aggregate_names == {"MAX"} and _is_correlated(select):
            continue
        source = _table_names(select)
        if source:
            by_source[source].append(aggregate_names)
    return any(len(items) >= 2 for items in by_source.values())


def _flatten_set_branches(node: exp.Expression) -> list[exp.Select]:
    if isinstance(node, (exp.Union, exp.Except, exp.Intersect)):
        return _flatten_set_branches(node.this) + _flatten_set_branches(node.expression)
    return [node] if isinstance(node, exp.Select) else []


def _has_repeated_source_set_operation(tree: exp.Expression) -> bool:
    branches = _flatten_set_branches(tree)
    if len(branches) < 2:
        return False
    sources = [_table_names(branch) for branch in branches]
    counts = Counter(source for source in sources if source)
    return any(count >= 2 for count in counts.values())


def detect_optimization_patterns(tree: exp.Expression, statement_type: str) -> set[str]:
    """Return precise advisory pattern flags derived only from the SQL AST."""
    if statement_type != "SELECT":
        return set()

    flags: set[str] = set()
    if _has_cross_column_or(tree):
        flags.add("cross_column_or")
    if _has_string_concat_predicate(tree):
        flags.add("string_concat_predicate")
    if _has_column_expression_join(tree):
        flags.add("column_expression_join")
    if _has_repeated_correlated_max_subquery(tree):
        flags.add("repeated_correlated_max_subquery")
    if _has_repeated_scalar_aggregate(tree):
        flags.add("repeated_scalar_aggregate")
    if _has_repeated_source_set_operation(tree):
        flags.add("repeated_source_set_operation")
    return flags
