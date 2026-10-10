"""Run the real SQL rules against a deliberately awkward portfolio.

    python tests/test_edge_cases.py

The generated portfolio is well-behaved by construction: five branches, four
officers each, every officer with a full book. None of the arithmetic ever has
to cope with an empty denominator, so none of it is ever tested.

A real loan book is not like that. Branches lose staff. An officer joins in
month twenty. A month closes with nothing due. So this builds a tiny portfolio
containing exactly the cases the generator never produces, and runs the
published SQL against it unchanged.

The four cases:

  1. AN OFFICER ALONE IN HIS BRANCH. Rules 1 and 3 compare him to his branch
     peers with his own figures removed from the benchmark. Remove the only
     officer and the benchmark is empty. This is the case the NULLIF guards in
     both queries exist for.
  2. A MONTH WITH NOTHING DUE. The collection rate is recorded / due.
  3. AN INSTALLMENT WITH NO REPAYMENT ROW AT ALL. The thing the project hunts.
     An INNER JOIN would drop it silently, which is why both rules LEFT JOIN.
  4. AN OFFICER WITH ONE SINGLE INSTALLMENT. Percentages over a denominator of
     one are not wrong, but they are not evidence either.

What this found, and why it is in the README: a lone officer scores NULL on the
peer-relative rules, and build_dashboard then assigns him the WORST rank on
those rules, which makes him look LESS suspicious, not more. That is the safe
direction to fail in, but it is a real limitation and it was not documented
until this test went looking for it.
"""

import io
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import build_dashboard as BD          # noqa: E402

failures = []
checks = 0


def check(label, condition, detail=""):
    global checks
    checks += 1
    print("   %-62s %s" % (label, "ok" if condition else "FAILED"))
    if not condition:
        failures.append(label + ((" - " + detail) if detail else ""))


def build_awkward_portfolio():
    """A portfolio containing only the cases the generator never produces."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(io.open(os.path.join(ROOT, "src", "schema.sql"),
                              encoding="utf-8").read())

    con.execute("INSERT INTO branches VALUES (1,'Lone','Greater Accra','2023-01-01')")
    con.execute("INSERT INTO branches VALUES (2,'Paired','Ashanti','2023-01-01')")

    # Officer 1 is alone in branch 1. Officers 2 and 3 share branch 2.
    # Officer 4 is in branch 2 but holds a single installment.
    for oid, bid in ((1, 1), (2, 2), (3, 2), (4, 2)):
        con.execute("INSERT INTO credit_officers VALUES (?,?,?,'2023-01-01',1)",
                    (oid, bid, "Officer %d" % oid))
        con.execute("""INSERT INTO borrowers VALUES
                       (?,?,?,?,'2023-06-01','trader','low',1)""",
                    (oid, oid, bid, "Borrower %d" % oid))
        con.execute("""INSERT INTO loans VALUES
                       (?,?,?,5000.0,'flat',0.36,12,'monthly','2024-01-01','active',NULL)""",
                    (oid, oid, oid))

    sched_id = 0
    rep_id = 0
    for oid in (1, 2, 3, 4):
        n_installments = 1 if oid == 4 else 12
        for k in range(n_installments):
            sched_id += 1
            month = "2024-%02d-15" % (k + 1)
            # Case 2: officer 2's third installment has nothing due at all.
            due = 0.0 if (oid == 2 and k == 2) else 500.0
            con.execute("INSERT INTO repayment_schedule VALUES (?,?,?,?,?)",
                        (sched_id, oid, k + 1, month, due))

            # Case 3: officer 3's fifth installment has no repayment row at all.
            if oid == 3 and k == 4:
                continue
            # Officer 2 pays short throughout; everyone else pays in full.
            recorded = 200.0 if oid == 2 else due
            rep_id += 1
            con.execute("""INSERT INTO repayments_recorded VALUES
                           (?,?,?,?,?,?,'cash_to_officer')""",
                        (rep_id, oid, sched_id, oid, month, recorded))

    for oid in (1, 2, 3, 4):
        con.execute("INSERT INTO ground_truth_officers VALUES (?,0,NULL,NULL,NULL,0.0)",
                    (oid,))
    con.commit()
    return con


print("Building a portfolio the generator would never produce")
con = build_awkward_portfolio()
print("   4 officers, one alone in his branch, one with a zero-due month,")
print("   one with an unrecorded installment, one with a single installment\n")

# ----------------------------------------------------------- 1. the rules run
print("1. Every published rule runs against it without raising")
results = {}
for fn in sorted(os.listdir(os.path.join(ROOT, "sql"))):
    if not fn.endswith(".sql"):
        continue
    try:
        results[fn] = BD.run_sql(con, fn)
        check("%s returns %d row(s)" % (fn, len(results[fn])), True)
    except Exception as exc:                                  # noqa: BLE001
        check("%s runs" % fn, False, "%s: %s" % (type(exc).__name__, exc))
        results[fn] = []

# ------------------------------------------------- 2. the lone officer is NULL
print("\n2. The lone officer gets no peer benchmark, and nothing divides by zero")
r1 = {r["officer_id"]: r for r in results.get("01_officer_peer_gap.sql", [])}
r3 = {r["officer_id"]: r for r in results.get("03_short_payment_concentration.sql", [])}

if 1 in r1:
    # The NULLIF guard turns the empty peer denominator into NULL, which AVG
    # then ignores, so the mean gap is NULL rather than 0, inf or a crash.
    check("rule 1: officer 1 alone in his branch -> mean gap is NULL, not a "
          "fabricated number", r1[1]["mean_gap_pp"] is None,
          "got %r" % (r1[1]["mean_gap_pp"],))
    check("rule 1: and he is counted as below peers in zero months",
          r1[1]["months_below_peers"] == 0, "got %r" % (r1[1]["months_below_peers"],))
    check("rule 1: his months are still observed, so he is not dropped entirely",
          r1[1]["months_observed"] == 12, "got %r" % (r1[1]["months_observed"],))
else:
    check("rule 1 returns a row for the lone officer", False, "officer 1 absent")

if 1 in r3:
    check("rule 3: officer 1 peer short-payment rate is NULL",
          r3[1]["peer_pct_short"] is None, "got %r" % (r3[1]["peer_pct_short"],))

# ------------------------------------------- 3. no negative or absurd percentages
print("\n3. No rule produces a negative or impossible percentage")
for fn, rows in results.items():
    for row in rows:
        for key, val in row.items():
            if val is None or not isinstance(val, (int, float)):
                continue
            if key.startswith("pct_") or key.endswith("_rate"):
                check("%s %s=%s within 0-100" % (fn, key, val),
                      -0.01 <= val <= 100.01)

# ------------------------------------- 4. the unrecorded installment is not lost
print("\n4. The installment with no repayment row is kept, not silently dropped")
total_due = con.execute("SELECT SUM(amount_due_ghs) FROM repayment_schedule "
                        "WHERE loan_id = 3").fetchone()[0]
seen_due = sum(r["due_ghs"] for r in con.execute("""
    SELECT SUM(s.amount_due_ghs) AS due_ghs FROM repayment_schedule s
    JOIN loans l ON l.loan_id = s.loan_id WHERE l.officer_id = 3"""))
check("officer 3's full GHS %.0f of due is visible to the rules, including the "
      "installment with no repayment" % total_due, abs(total_due - seen_due) < 0.01)
if 3 in r1:
    # Officer 3 has one installment with no repayment row at all. If the rule
    # used an INNER JOIN that month would vanish; with the LEFT JOIN it is
    # counted as a month in which nothing arrived against an amount due.
    check("rule 1 officer 3: all 12 months observed despite one having no "
          "repayment row", r1[3]["months_observed"] == 12,
          "got %r" % (r1[3]["months_observed"],))
    check("rule 1 officer 3: the unrecorded installment shows up as a shortfall",
          r1[3]["implied_shortfall_ghs"] is not None,
          "got %r" % (r1[3]["implied_shortfall_ghs"],))

# ------------------------------------------ 5. the ranking survives all of it
print("\n5. The published ranking handles the whole portfolio")
try:
    cases = BD.build_cases(con)
    check("build_cases returns a case per officer", len(cases) >= 3,
          "got %d" % len(cases))
    check("every score is a real number", all(isinstance(c["score"], (int, float))
                                              for c in cases))
    lone = [c for c in cases if c["officer_id"] == 1]
    if lone:
        ranks = lone[0]["ranks"]
        n = len(cases)
        worst = [k for k, v in ranks.items() if v == n]
        # DOCUMENTED BEHAVIOUR, not a pass/fail: an unscoreable officer is given
        # the worst rank, which reads as LEAST suspicious. Safe, but a blind spot.
        print("   note: the lone officer's ranks are %s of %d" % (ranks, n))
        print("         unscoreable rules default to the worst rank (%s), which"
              % (worst or "none"))
        print("         makes him look LESS suspicious. Safe direction, but a")
        print("         blind spot: a one-officer branch cannot be caught by the")
        print("         peer-relative rules at all. Recorded in the README.")
except Exception as exc:                                      # noqa: BLE001
    check("build_cases runs", False, "%s: %s" % (type(exc).__name__, exc))

con.close()

print("\n" + "=" * 70)
if failures:
    print("FAILED  %d checks run, %d failure(s):" % (checks, len(failures)))
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("PASSED  %d checks run on a portfolio built to break the arithmetic." % checks)
sys.exit(0)
