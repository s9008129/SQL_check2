"""Follow-up spike: resolve function-on-column ambiguity, error_level=RAISE
behavior on garbage SQL, hint support on DELETE/INSERT/MERGE, and
INSERT/MERGE WHERE-detection shape.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError


def line(title: str) -> None:
    print(f"\n=== {title} ===")


# A. Resolve the "func matches whole AND clause" mystery
line("A: explicit type name for every exp.Func match in a WHERE with AND")
t = sqlglot.parse_one(
    "SELECT * FROM T A WHERE A.STATUS = :S AND A.CREATED >= TRUNC(SYSDATE, 'DD')",
    read="oracle",
)
where = t.find(exp.Where)
for f in where.find_all(exp.Func):
    cols = [c.sql(dialect="oracle") for c in f.find_all(exp.Column)]
    print("  type:", type(f).__name__, "| sql:", f.sql(dialect="oracle"), "| cols inside:", cols)

line("A-bis: resolve whether And/Or/EQ/GTE are really exp.Func subclasses")
print("  issubclass(And, Func):", issubclass(exp.And, exp.Func))
print("  issubclass(Or, Func):", issubclass(exp.Or, exp.Func))
print("  issubclass(EQ, Func):", issubclass(exp.EQ, exp.Func))
print("  issubclass(GTE, Func):", issubclass(exp.GTE, exp.Func))
print("  issubclass(Connector, Func):", issubclass(exp.Connector, exp.Func))
print("  isinstance(where.this, Func) [the And node itself]:", isinstance(where.this, exp.Func))
print("  where.this type:", type(where.this).__name__, "mro:", [c.__name__ for c in type(where.this).__mro__])

line("A2: same but only direct comparison operands, via exp.Predicate walk")
for cond in where.find_all(exp.Binary):
    print("  binary:", type(cond).__name__, "->", cond.sql(dialect="oracle"))
    for side_name in ("this", "expression"):
        side = cond.args.get(side_name)
        if isinstance(side, exp.Func):
            cols = [c.sql(dialect="oracle") for c in side.find_all(exp.Column)]
            print(f"    side={side_name} is Func: {type(side).__name__} cols={cols}")

# B. error_level=RAISE on garbage SQL - what actually happens?
line("B: error_level RAISE on 'SELEKT * FRM T' - inspect result")
try:
    result = sqlglot.parse_one("SELEKT * FRM T", read="oracle", error_level=ErrorLevel.RAISE)
    print("  no exception; type:", type(result).__name__)
    print("  rendered sql:", result.sql(dialect="oracle"))
    print("  repr:", repr(result)[:400])
except ParseError as e:
    print("  ParseError:", str(e)[:200])

line("B2: error_level RAISE on truly broken syntax (mismatched paren)")
try:
    result = sqlglot.parse_one(
        "SELECT * FROM T WHERE (A = 1", read="oracle", error_level=ErrorLevel.RAISE
    )
    print("  no exception; type:", type(result).__name__, result.sql(dialect="oracle"))
except ParseError as e:
    print("  ParseError:", str(e)[:200])

line("B3: sqlglot.parse (plural) with error_level RAISE on garbage")
try:
    stmts = sqlglot.parse("SELEKT * FRM T", read="oracle", error_level=ErrorLevel.RAISE)
    print("  statements:", [type(s).__name__ if s else None for s in stmts])
except ParseError as e:
    print("  ParseError:", str(e)[:200])

line("B4: does the malformed SQL round-trip back to something sane, or keep 'SELEKT'?")
try:
    result = sqlglot.parse_one("SELEKT * FRM T", read="oracle")
    print("  top type:", type(result).__name__)
    print("  is Select/Update/Delete/Insert/Merge/Command:", isinstance(result, (exp.Select, exp.Update, exp.Delete, exp.Insert, exp.Merge)))
    print("  is exp.Command (catch-all)?", isinstance(result, exp.Command))
except Exception as e:  # noqa: BLE001
    print("  raised:", type(e).__name__, e)

line("B5: totally nonsense token soup")
for bad in ["asdkjfh asldkjf", "SELECT FROM WHERE", "1 2 3 4"]:
    try:
        result = sqlglot.parse_one(bad, read="oracle", error_level=ErrorLevel.RAISE)
        print(f"  {bad!r} -> no exception, top type: {type(result).__name__}, is Command: {isinstance(result, exp.Command)}")
    except ParseError as e:
        print(f"  {bad!r} -> ParseError: {str(e)[:120]}")

# C. Hint support on DELETE / INSERT / MERGE
line("C: hint on DELETE")
t = sqlglot.parse_one("DELETE /*+ PARALLEL(A,4) */ FROM T A WHERE A.X=1", read="oracle")
print("  top type:", type(t).__name__, "hint:", t.args.get("hint"))

line("C2: hint on INSERT")
t = sqlglot.parse_one(
    "INSERT /*+ APPEND PARALLEL(A,4) */ INTO T A (X) SELECT Y FROM T2", read="oracle"
)
print("  top type:", type(t).__name__, "hint:", t.args.get("hint"))
if t.args.get("hint"):
    for item in t.args["hint"].expressions:
        text = item.sql(dialect="oracle") if isinstance(item, exp.Expression) else str(item)
        print("    hint item:", type(item).__name__, text)

line("C3: hint on MERGE")
t = sqlglot.parse_one(
    "MERGE /*+ PARALLEL(T,4) */ INTO T A USING T2 B ON (A.ID=B.ID) "
    "WHEN MATCHED THEN UPDATE SET A.X=B.X",
    read="oracle",
)
print("  top type:", type(t).__name__, "hint:", t.args.get("hint"))

# D. INSERT ... SELECT / MERGE structure for WHERE detection
line("D: INSERT ... SELECT structure")
t = sqlglot.parse_one("INSERT INTO T A (X) SELECT Y FROM T2 B WHERE B.Z=1", read="oracle")
print("  top type:", type(t).__name__)
inner_select = t.find(exp.Select)
print("  inner select has where:", inner_select.find(exp.Where) is not None if inner_select else None)

line("D2: MERGE structure - where is the join condition / update where?")
t = sqlglot.parse_one(
    "MERGE INTO T A USING T2 B ON (A.ID=B.ID) WHEN MATCHED THEN UPDATE SET A.X=B.X",
    read="oracle",
)
print("  repr:", repr(t)[:500])

# E. Hint expression item text for a variety of hints incl PARALLEL_INDEX, USE_HASH
line("E: hint item text variety")
for hint_sql in [
    "SELECT /*+ PARALLEL_INDEX(A, IDX1, 4) */ * FROM T A",
    "SELECT /*+ USE_HASH(A B) */ * FROM T A, T2 B",
    "SELECT /*+ FULL(A) PARALLEL(A,4) */ * FROM T A",
]:
    t = sqlglot.parse_one(hint_sql, read="oracle")
    h = t.args.get("hint")
    items = [
        (it.sql(dialect="oracle") if isinstance(it, exp.Expression) else str(it)) for it in h.expressions
    ] if h else []
    print(f"  {hint_sql!r} -> hint items: {items}")

# F. exp.Merge WHEN clauses class name (for R002/complexity flag purposes)
line("F: exp.Merge attribute names")
t = sqlglot.parse_one(
    "MERGE INTO T A USING T2 B ON (A.ID=B.ID) WHEN MATCHED THEN UPDATE SET A.X=B.X "
    "WHEN NOT MATCHED THEN INSERT (X) VALUES (B.X)",
    read="oracle",
)
print("  args keys:", list(t.args.keys()))

print("\nSPIKE 2 COMPLETE")
