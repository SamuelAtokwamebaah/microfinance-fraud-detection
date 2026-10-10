"""The observation window must mean the same thing everywhere.

    python tests/test_window.py

`src/config.py` derives the window from SIM_START and SIM_MONTHS. The queries in
`sql/` still carry the dates written out, because the README tells a reader to
run them straight against the database:

    sqlite3 data/generated/portfolio.db < sql/03_short_payment_concentration.sql

A query holding an unbound parameter cannot be run that way, so the literals
stay and this test checks them instead. That turns the duplication from a silent
hazard into a loud one.

The hazard is specific and easy to walk into. Raise SIM_MONTHS from 24 to 36 and
the generator dutifully builds 36 months of portfolio, while every rule goes on
filtering `due_date <= '2025-12-31'` and quietly discards the last twelve. No
error, no warning, and a set of results that look entirely normal.
"""

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import config as C                                            # noqa: E402

DATE = re.compile(r"'(\d{4}-\d{2}-\d{2})'")
failures = []

print("The window derived in src/config.py")
print("   SIM_START  = %s" % C.SIM_START)
print("   SIM_MONTHS = %d" % C.SIM_MONTHS)
print("   WINDOW     = %s to %s\n" % (C.WINDOW_START, C.WINDOW_END))

allowed = {C.WINDOW_START, C.WINDOW_END}

# ------------------------------------------------- 1. the standalone SQL files
print("1. Every date literal in sql/ must be one of those two")
for fn in sorted(f for f in os.listdir(os.path.join(ROOT, "sql")) if f.endswith(".sql")):
    body = io.open(os.path.join(ROOT, "sql", fn), encoding="utf-8").read()
    found = set(DATE.findall(body))
    stray = found - allowed
    print("   %-40s %s" % (fn, sorted(found) if found else "no dates"))
    if stray:
        failures.append("sql/%s uses %s, which is not the configured window "
                        "(%s to %s). Either config.py changed and this query "
                        "was not updated, or the reverse."
                        % (fn, sorted(stray), C.WINDOW_START, C.WINDOW_END))

# --------------------------------------------- 2. no raw dates left in Python
print("\n2. No date literal may remain in Python, where a token should be used")
for rel in ("src/build_dashboard.py", "src/tier2.py", "src/evaluate_tier1.py"):
    body = io.open(os.path.join(ROOT, rel), encoding="utf-8").read()
    found = set(DATE.findall(body))
    print("   %-26s %s" % (rel, sorted(found) if found else "none, as intended"))
    if found:
        failures.append("%s hard-codes %s; use the {WINDOW_START}/{WINDOW_END} "
                        "tokens and C.apply_window() instead" % (rel, sorted(found)))

# ------------------------------------- 3. every token actually gets substituted
# A tokenised query that is executed without apply_window would compare
# due_date to the literal string '{WINDOW_END}', match nothing, and silently
# return an empty result. So check the substitution really happens.
print("\n3. Every tokenised query is executed through apply_window")
for rel in ("src/build_dashboard.py", "src/tier2.py"):
    body = io.open(os.path.join(ROOT, rel), encoding="utf-8").read()
    n_tokens = len(re.findall(r"\{WINDOW_(?:START|END)\}", body))
    n_calls = len(re.findall(r"apply_window\(", body))
    ok = n_calls > 0 and n_tokens > 0
    print("   %-26s %d token(s), %d apply_window call(s)  %s"
          % (rel, n_tokens, n_calls, "ok" if ok else "MISMATCH"))
    if not ok:
        failures.append("%s has %d window token(s) but %d apply_window call(s)"
                        % (rel, n_tokens, n_calls))

print("\n4. apply_window leaves no token behind")
sample = "WHERE d BETWEEN '{WINDOW_START}' AND '{WINDOW_END}'"
out = C.apply_window(sample)
print("   %s\n   -> %s" % (sample, out))
if "{WINDOW" in out:
    failures.append("apply_window left a token unsubstituted: %r" % out)
if C.WINDOW_START not in out or C.WINDOW_END not in out:
    failures.append("apply_window did not insert both dates: %r" % out)

# ------------------------------------------ 5. the derivation itself is right
print("\n5. The derived end date is the last day of the window")
expected = {("2024-01-01", 24): "2025-12-31",
            ("2024-01-01", 12): "2024-12-31",
            ("2024-01-01", 36): "2026-12-31",
            ("2023-07-01", 6): "2023-12-31"}
for (start, months), want in sorted(expected.items()):
    total = (int(start[:4]) * 12 + int(start[5:7]) - 1) + months
    import datetime as dt
    got = (dt.date(total // 12, total % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
    print("   %s + %2d months -> %s  %s" % (start, months, got,
                                            "ok" if got == want else "WRONG, want " + want))
    if got != want:
        failures.append("window derivation wrong for %s + %d: got %s, want %s"
                        % (start, months, got, want))

print("\n" + "=" * 70)
if failures:
    print("FAILED  %d problem(s):" % len(failures))
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("PASSED  The window is defined once and agrees everywhere.")
sys.exit(0)
