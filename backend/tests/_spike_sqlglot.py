"""Throwaway spike to verify sqlglot 30.18 Oracle-dialect AST shapes before
sql_parser.py / rule_engine.py are implemented. Not a pytest test (prefixed
with _ and excluded); run directly: `uv run python tests/_spike_sqlglot.py`.
Delete once findings are captured in the plan/lessons if no longer needed.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp


def line(title: str) -> None:
    print(f"\n=== {title} ===")


def dump(sql: str, *, dialect: str = "oracle") -> exp.Expression:
    tree = sqlglot.parse_one(sql, read=dialect)
    print("repr:", repr(tree)[:300])
    print("sql :", tree.sql(dialect=dialect))
    return tree


# 1. Parallel hint directly after SELECT -> exp.Hint?
line("Hint after SELECT")
t = dump("SELECT /*+ PARALLEL(A, 4) */ A.X FROM T A WHERE A.X = 1")
hints = list(t.find_all(exp.Hint))
print("exp.Hint found:", len(hints), [h.sql(dialect="oracle") for h in hints])

# 2. Hint on UPDATE
line("Hint on UPDATE")
t = dump("UPDATE /*+ PARALLEL(A, 4) */ T A SET A.X = 1 WHERE A.Y = 2")
hints = list(t.find_all(exp.Hint))
print("exp.Hint found:", len(hints))
print("comments on root:", t.comments)
for node in t.walk():
    n = node[0] if isinstance(node, tuple) else node
    if getattr(n, "comments", None):
        print("  comment carrier:", type(n).__name__, n.comments)

# 3. --+ single line hint style
line("-- + line hint on SELECT")
t = dump("SELECT --+ PARALLEL(A 4)\nA.X FROM T A WHERE A.Y = 2")
print("comments on root:", t.comments)

# 4. NOPARALLEL should not match bare PARALLEL regex if we're careless
line("NOPARALLEL should not be treated as PARALLEL")
t = dump("SELECT /*+ NOPARALLEL(A) */ A.X FROM T A WHERE A.Y = 2")
hints = list(t.find_all(exp.Hint))
print("exp.Hint found:", len(hints), [h.sql(dialect="oracle") for h in hints])

# 5. TRUNC on a column in WHERE
line("TRUNC(col) in WHERE")
t = dump("SELECT * FROM T A WHERE TRUNC(A.TXN_DATE) = :DATE_001")
where = t.find(exp.Where)
print("where sql:", where.sql(dialect="oracle"))
for f in where.find_all(exp.Func):
    print("  func node:", type(f).__name__, "->", f.sql(dialect="oracle"), "is_func:", isinstance(f, exp.Func))
for c in where.find_all(exp.Column):
    anc = []
    p = c.parent
    while p is not None:
        anc.append(type(p).__name__)
        p = p.parent
    print("  column:", c.sql(dialect="oracle"), "ancestors:", anc)

# 5b. Confirm exp.Anonymous is-a exp.Func, and check dedicated class alternatives
line("Is exp.Anonymous a subclass of exp.Func? Any dedicated TRUNC class?")
print("Anonymous subclass of Func:", issubclass(exp.Anonymous, exp.Func))
print("hasattr exp.Trunc:", hasattr(exp, "Trunc"))
print("hasattr exp.DateTrunc:", hasattr(exp, "DateTrunc"))
t2 = sqlglot.parse_one("SELECT TRUNC(SYSDATE, 'MM') FROM DUAL", read="oracle")
f = next(t2.find_all(exp.Func))
print("TRUNC-with-format node type:", type(f).__name__, f.sql(dialect="oracle"))

# 6. TRUNC(SYSDATE) should NOT count as function-on-column (no Column inside)
line("TRUNC(SYSDATE) should not count (no column arg)")
t = dump("SELECT * FROM T A WHERE A.STATUS = :S AND A.CREATED >= TRUNC(SYSDATE)")
where = t.find(exp.Where)
for f in where.find_all(exp.Func):
    has_col = any(True for _ in f.find_all(exp.Column))
    print("  func:", f.sql(dialect="oracle"), "contains column:", has_col)

# 7. Function on RHS literal-only comparisons should also be caught the same way
line("Function on comparison where COLUMN is the func arg vs literal arg")
t = dump("SELECT * FROM T A WHERE A.AMT = ROUND(:X, 2)")
where = t.find(exp.Where)
for f in where.find_all(exp.Func):
    has_col = any(True for _ in f.find_all(exp.Column))
    print("  func:", f.sql(dialect="oracle"), "contains column:", has_col)

# 8. (+) outer join marker
line("(+) outer join marker representation")
t = dump("SELECT E.NAME, M.NAME FROM EMP E, EMP M WHERE E.MGR_ID = M.ID(+)")
for c in t.find_all(exp.Column):
    print("  column:", c.sql(dialect="oracle"), "join_mark attr:", c.args.get("join_mark"))

# 9. Bind variable representation
line("Bind variable :NAME representation")
t = dump("SELECT * FROM T A WHERE A.ID = :ID_001")
where = t.find(exp.Where)
print("where repr:", repr(where)[:300])
for node in where.walk():
    n = node[0] if isinstance(node, tuple) else node
    if isinstance(n, (exp.Placeholder, exp.Parameter, exp.Var)):
        print("  bind-like node:", type(n).__name__, n.sql(dialect="oracle"))

# 10. LIKE with bind on RHS should not be a Literal
line("LIKE with bind RHS")
t = dump("SELECT * FROM T A WHERE A.NAME LIKE :PATTERN")
for lk in t.find_all(exp.Like):
    print("  like this:", lk.this.sql(dialect="oracle"), "expr type:", type(lk.expression).__name__)

# 11. LIKE with leading wildcard literal
line("LIKE leading wildcard literal")
t = dump("SELECT * FROM T A WHERE A.NAME LIKE '%ABC'")
for lk in t.find_all(exp.Like):
    print("  like expr type:", type(lk.expression).__name__, "value:", getattr(lk.expression, "this", None))

# 12. LIKE with '%' || :bind concatenation
line("LIKE with concat leading wildcard")
t = dump("SELECT * FROM T A WHERE A.NAME LIKE '%' || :PATTERN")
for lk in t.find_all(exp.Like):
    print("  like expr type:", type(lk.expression).__name__, "sql:", lk.expression.sql(dialect="oracle"))

# 13. String literal containing 'OR' should not trigger OR-detection
line("String literal containing OR should not be exp.Or")
t = dump("SELECT * FROM T A WHERE A.NOTE = 'A OR B'")
print("exp.Or count:", len(list(t.find_all(exp.Or))))

# 14. Real OR condition
line("Real OR condition")
t = dump("SELECT * FROM T A WHERE A.X = 1 OR A.Y = 2")
print("exp.Or count:", len(list(t.find_all(exp.Or))))

# 15. Comment '-- avoid OR here' should not trigger OR detection
line("Leading comment mentioning OR should not trigger")
t = dump("-- avoid OR here\nSELECT * FROM T A WHERE A.X = 1")
print("exp.Or count:", len(list(t.find_all(exp.Or))))
print("root comments:", t.comments)

# 16. WHERE existence check helpers
line("WHERE existence: FROM DUAL, no FROM, UNION branch")
for sql in [
    "SELECT SYSDATE FROM DUAL",
    "SELECT 1",
    "SELECT * FROM T A WHERE A.X=1 UNION SELECT * FROM T2 B",
    "SELECT * FROM T A UNION SELECT * FROM T2 B WHERE B.X=1",
]:
    t = sqlglot.parse_one(sql, read="oracle")
    print(f"  sql={sql!r}")
    print("    top type:", type(t).__name__)
    if isinstance(t, (exp.Union, exp.Except, exp.Intersect)):
        print("    left has where:", t.left.find(exp.Where) is not None if hasattr(t, "left") else None)
        print("    right has where:", t.right.find(exp.Where) is not None if hasattr(t, "right") else None)
    else:
        print("    has where:", t.find(exp.Where) is not None)

# 17. Multi-statement split via tokenizer SEMICOLON
line("Tokenizer SEMICOLON-based split safety with string/comment containing ;")
from sqlglot.tokens import Tokenizer, TokenType

tk = Tokenizer(dialect="oracle")
sql = "SELECT ';' AS X FROM DUAL; -- comment; still one stmt\nSELECT 2 FROM DUAL;"
tokens = tk.tokenize(sql)
semi_positions = [(tok.start, tok.end) for tok in tokens if tok.token_type == TokenType.SEMICOLON]
print("token count:", len(tokens), "semicolons at:", semi_positions)
for tok in tokens[:6]:
    print("  ", tok.token_type, repr(tok.text))

# 18. PL/SQL block parse behavior
line("PL/SQL DECLARE block - does parse_one choke or succeed?")
plsql = "DECLARE\n  X NUMBER;\nBEGIN\n  X := 1;\nEND;"
try:
    t = sqlglot.parse_one(plsql, read="oracle")
    print("parsed ok:", type(t).__name__, t.sql(dialect="oracle")[:100])
except Exception as e:  # noqa: BLE001
    print("parse raised:", type(e).__name__, str(e)[:200])

# 19. error_level RAISE behavior on garbage input
line("error_level RAISE on malformed SQL")
from sqlglot.errors import ErrorLevel, ParseError

try:
    sqlglot.parse_one("SELEKT * FRM T", read="oracle", error_level=ErrorLevel.RAISE)
    print("no error raised (unexpected)")
except ParseError as e:
    print("ParseError raised as expected:", str(e)[:150])

# 20. Table extraction incl schema-qualified
line("Table extraction with schema qualifier")
t = dump("SELECT * FROM TAX.HOUT120 A WHERE A.X = 1")
for tbl in t.find_all(exp.Table):
    print("  table name:", tbl.name, "db:", tbl.db, "full:", tbl.sql(dialect="oracle"))

print("\nSPIKE COMPLETE")
