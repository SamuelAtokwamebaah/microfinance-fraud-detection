"""Assemble the evidence dashboard.

Run:  python src/build_dashboard.py   ->  docs/index.html

The dashboard mirrors an escalation workflow rather than presenting charts for
their own sake:

    case queue      who to look at first, and which rules fired
    officer detail  why them: rule scores, and collection trend against peers
    evidence pack   which borrowers, which installments, what is missing

WHAT THE DASHBOARD MAY SEE
Everything in the `cases` payload is derived from the schedule and the recorded
book only. An investigator does not know who is guilty; that is the problem the
tool exists to address, so the tool is not allowed to know either.

Ground truth is loaded separately into `evaluation`, which scores how the
ranking performed. It is rendered in its own clearly-marked panel and never
feeds the ranking.
"""

import io
import json
import os
import sqlite3

import config as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))

TOP_N = 5            # officers carried through to full evidence packs
MAX_ROWS = 150       # installments per evidence pack, worst shortfall first


def connect():
    con = sqlite3.connect(os.path.join(ROOT, C.DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def run_sql(con, filename):
    sql = io.open(os.path.join(ROOT, "sql", filename), encoding="utf-8").read()
    return [dict(r) for r in con.execute(sql).fetchall()]


# ----------------------------------------------------------------- scoring

def rank_map(rows, key, higher_is_worse):
    """Convert a rule's raw metric into a rank, 1 = most suspicious.

    Ranks rather than thresholds, for the reason set out in evaluate_tier1.py:
    a cutoff tuned until it works is a cutoff fitted to labels we would not have
    in production. A rank needs no tuning and survives a different portfolio.
    """
    usable = [r for r in rows if r.get(key) is not None]
    ordered = sorted(usable, key=lambda r: r[key], reverse=higher_is_worse)
    return {r["officer_id"]: i + 1 for i, r in enumerate(ordered)}


def build_cases(con):
    r1 = run_sql(con, "01_officer_peer_gap.sql")
    r2 = run_sql(con, "02_delinquency_contradiction.sql")
    r3 = run_sql(con, "03_short_payment_concentration.sql")

    by_id = {}
    for row in r1:
        by_id[row["officer_id"]] = {"peer_gap": row}
    for row in r2:
        by_id.setdefault(row["officer_id"], {})["contradiction"] = row
    for row in r3:
        by_id.setdefault(row["officer_id"], {})["short_pay"] = row

    ranks = {
        "peer_gap": rank_map(r1, "mean_gap_pp", False),
        "contradiction": rank_map(r2, "pct_of_book", True),
        "short_pay": rank_map(r3, "excess_pp", True),
    }
    n = len(by_id)

    officers = {r["officer_id"]: dict(r) for r in con.execute("""
        SELECT o.officer_id, o.name, o.branch_id, b.name AS branch, o.owns_followup,
               (SELECT COUNT(*) FROM borrowers bo WHERE bo.officer_id = o.officer_id) AS book_size
        FROM credit_officers o JOIN branches b ON b.branch_id = o.branch_id""")}

    cases = []
    for oid, parts in by_id.items():
        rr = {k: ranks[k].get(oid, n) for k in ranks}
        # Suspicion score: mean rank inverted onto 0-100. Three independent
        # signals agreeing is worth more than one extreme signal alone, which is
        # exactly the failure mode of a single-metric ranking.
        mean_rank = sum(rr.values()) / float(len(rr))
        score = round(100.0 * (n - mean_rank) / (n - 1), 1)
        fired = []
        if rr["peer_gap"] <= 3:
            fired.append("collects below branch peers")
        if rr["contradiction"] <= 3:
            fired.append("borrowers contradict their own history")
        if rr["short_pay"] <= 3:
            fired.append("short payments above peers")

        pg = parts.get("peer_gap", {})
        ct = parts.get("contradiction", {})
        sp = parts.get("short_pay", {})
        cases.append({
            "officer_id": oid,
            "name": officers[oid]["name"],
            "branch": officers[oid]["branch"],
            "book_size": officers[oid]["book_size"],
            "owns_followup": officers[oid]["owns_followup"],
            "score": score,
            "ranks": rr,
            "signals": fired,
            "metrics": {
                "mean_gap_pp": pg.get("mean_gap_pp"),
                "months_below_peers": pg.get("months_below_peers"),
                "months_observed": pg.get("months_observed"),
                "implied_shortfall_ghs": pg.get("implied_shortfall_ghs"),
                "contradicting_borrowers": ct.get("contradicting_borrowers"),
                "pct_of_book": ct.get("pct_of_book"),
                "pct_short": sp.get("pct_short"),
                "peer_pct_short": sp.get("peer_pct_short"),
                "excess_pp": sp.get("excess_pp"),
                "total_shortfall_ghs": sp.get("total_shortfall_ghs"),
                "borrowers_affected": sp.get("borrowers_affected"),
            },
        })

    cases.sort(key=lambda c: -c["score"])
    return cases


# ----------------------------------------------------------------- trend

TREND_SQL = """
WITH paid AS (
    SELECT schedule_id, SUM(amount_recorded_ghs) AS rec
    FROM repayments_recorded GROUP BY schedule_id
),
om AS (
    SELECT l.officer_id, o.branch_id, substr(s.due_date,1,7) AS period,
           SUM(s.amount_due_ghs) AS due, SUM(COALESCE(p.rec,0)) AS rec
    FROM repayment_schedule s
    JOIN loans l ON l.loan_id = s.loan_id
    JOIN credit_officers o ON o.officer_id = l.officer_id
    LEFT JOIN paid p ON p.schedule_id = s.schedule_id
    WHERE s.due_date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY l.officer_id, o.branch_id, period
)
SELECT officer_id, period,
       ROUND(100.0 * rec / NULLIF(due,0), 2) AS officer_rate,
       ROUND(100.0 * (SUM(rec) OVER (PARTITION BY branch_id, period) - rec)
             / NULLIF(SUM(due) OVER (PARTITION BY branch_id, period) - due, 0), 2) AS peer_rate
FROM om ORDER BY officer_id, period
"""


def build_trends(con):
    trends = {}
    for r in con.execute(TREND_SQL):
        trends.setdefault(str(r["officer_id"]), []).append(
            {"period": r["period"], "officer": r["officer_rate"], "peer": r["peer_rate"]})
    return trends


# ----------------------------------------------------------------- evidence

EVIDENCE_SQL = """
WITH paid AS (
    SELECT schedule_id, SUM(amount_recorded_ghs) AS rec, MIN(recorded_date) AS rec_date
    FROM repayments_recorded GROUP BY schedule_id
),
inst AS (
    SELECT s.schedule_id, s.due_date, s.amount_due_ghs, s.installment_no,
           l.loan_id, l.borrower_id, l.officer_id,
           COALESCE(p.rec, 0) AS recorded_ghs, p.rec_date,
           ROW_NUMBER() OVER (PARTITION BY s.loan_id ORDER BY s.due_date) AS seq
    FROM repayment_schedule s
    JOIN loans l ON l.loan_id = s.loan_id
    LEFT JOIN paid p ON p.schedule_id = s.schedule_id
    WHERE l.officer_id = ? AND s.due_date <= '2025-12-31' AND s.amount_due_ghs > 0
),
clean_start AS (
    SELECT borrower_id FROM inst WHERE seq <= 8 GROUP BY borrower_id
    HAVING AVG(CASE WHEN recorded_ghs >= 0.95 * amount_due_ghs THEN 1.0 ELSE 0.0 END) >= 0.90
)
SELECT i.schedule_id, i.due_date, i.borrower_id, bo.name AS borrower,
       i.loan_id, i.installment_no,
       ROUND(i.amount_due_ghs, 2) AS due_ghs,
       ROUND(i.recorded_ghs, 2)   AS recorded_ghs,
       ROUND(i.amount_due_ghs - i.recorded_ghs, 2) AS shortfall_ghs,
       i.rec_date
FROM inst i
JOIN clean_start c ON c.borrower_id = i.borrower_id
JOIN borrowers bo ON bo.borrower_id = i.borrower_id
WHERE i.recorded_ghs < 0.95 * i.amount_due_ghs
ORDER BY (i.amount_due_ghs - i.recorded_ghs) DESC
"""


def build_evidence(con, officer_id):
    """Installments that would go into an escalation pack.

    Scope: borrowers whose first eight installments were clean, then went short.
    That is the victim profile a skimming scheme selects, and restricting to it
    is what separates an evidence pack from a list of every late payer.
    """
    rows = [dict(r) for r in con.execute(EVIDENCE_SQL, (officer_id,))]
    total = round(sum(r["shortfall_ghs"] for r in rows), 2)
    borrowers = {}
    for r in rows:
        b = borrowers.setdefault(r["borrower_id"], {
            "borrower_id": r["borrower_id"], "name": r["borrower"],
            "installments": 0, "shortfall_ghs": 0.0, "first": r["due_date"], "last": r["due_date"]})
        b["installments"] += 1
        b["shortfall_ghs"] = round(b["shortfall_ghs"] + r["shortfall_ghs"], 2)
        b["first"] = min(b["first"], r["due_date"])
        b["last"] = max(b["last"], r["due_date"])
    top = sorted(borrowers.values(), key=lambda b: -b["shortfall_ghs"])
    return {
        "total_shortfall_ghs": total,
        "installments": len(rows),
        "borrowers": len(borrowers),
        "borrower_rows": top[:40],
        "rows": rows[:MAX_ROWS],
        "truncated": max(0, len(rows) - MAX_ROWS),
    }


# ----------------------------------------------------------------- evaluation

def build_evaluation(con, cases):
    """Scored AFTER the ranking is fixed. Never feeds it."""
    labels = {r["officer_id"]: r["is_fraudulent"]
              for r in con.execute("SELECT officer_id, is_fraudulent FROM ground_truth_officers")}
    frauds = {o for o, f in labels.items() if f}
    ranked = [c["officer_id"] for c in cases]

    rows = []
    for k in (1, 2, 3, 5):
        flagged = set(ranked[:k])
        tp = len(flagged & frauds)
        rows.append({"k": k, "caught": tp, "of": len(frauds),
                     "precision": round(100.0 * tp / k, 0),
                     "recall": round(100.0 * tp / len(frauds), 0)})

    actual = {r[0] for r in con.execute(
        "SELECT schedule_id FROM ground_truth_repayments WHERE was_skimmed = 1")}
    total_taken = con.execute(
        "SELECT ROUND(SUM(skimmed_amount_ghs),2) FROM ground_truth_repayments").fetchone()[0]

    return {"at_k": rows, "fraud_officers": sorted(frauds),
            "skimmed_installments": len(actual), "total_taken_ghs": total_taken,
            "labels": {str(k): v for k, v in labels.items()}}


# ----------------------------------------------------------------- assemble

def main():
    con = connect()
    cases = build_cases(con)
    trends = build_trends(con)

    evidence = {}
    for c in cases[:TOP_N]:
        evidence[str(c["officer_id"])] = build_evidence(con, c["officer_id"])

    payload = {
        "generated": "seed %s" % C.SEED,
        "portfolio": dict(con.execute("""
            SELECT (SELECT COUNT(*) FROM branches)            AS branches,
                   (SELECT COUNT(*) FROM credit_officers)     AS officers,
                   (SELECT COUNT(*) FROM borrowers)           AS borrowers,
                   (SELECT COUNT(*) FROM loans)               AS loans,
                   (SELECT COUNT(*) FROM repayment_schedule)  AS scheduled,
                   (SELECT COUNT(*) FROM repayments_recorded) AS recorded""").fetchone()),
        "cases": cases,
        "trends": trends,
        "evidence": evidence,
        "evaluation": build_evaluation(con, cases),
    }

    tpl = io.open(os.path.join(HERE, "dashboard_template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/", json.dumps(payload, separators=(",", ":")))

    out_dir = os.path.join(ROOT, "docs")
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    out = os.path.join(out_dir, "index.html")
    io.open(out, "w", encoding="utf-8", newline="\n").write(html)

    print("cases ranked      %d officers" % len(cases))
    print("evidence packs    %s" % ", ".join(str(c["officer_id"]) for c in cases[:TOP_N]))
    print("top of the queue  officer %d, score %.1f" % (cases[0]["officer_id"], cases[0]["score"]))
    print("written           %s  (%.0f KB)" % (out, os.path.getsize(out) / 1024.0))
    con.close()


if __name__ == "__main__":
    main()
