"""Score every Tier 1 rule against the ground-truth labels.

This is the ONLY module allowed to read the ground_truth_* tables. The rules in
sql/ never see them, which is what makes the precision and recall numbers below
mean anything.

Precision: of the officers this rule flagged, what share were actually stealing.
           Low precision costs investigator time and wrongly suspects staff.
Recall:    of the officers actually stealing, what share did this rule flag.
           Low recall means the money keeps walking.
"""

import io
import math
import os
import sqlite3

import config as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENFORD = [math.log10(1 + 1.0 / d) for d in range(1, 10)]


def connect():
    con = sqlite3.connect(os.path.join(ROOT, C.DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def run(con, filename):
    sql = io.open(os.path.join(ROOT, "sql", filename), encoding="utf-8").read()
    return con.execute(sql).fetchall()


def truth(con):
    return {r["officer_id"]: r["is_fraudulent"]
            for r in con.execute("SELECT officer_id, is_fraudulent FROM ground_truth_officers")}


def score(flagged, labels):
    flagged = set(flagged)
    frauds = {o for o, f in labels.items() if f}
    tp = len(flagged & frauds)
    precision = tp / len(flagged) if flagged else 0.0
    recall = tp / len(frauds) if frauds else 0.0
    return tp, len(flagged), precision, recall


def report(name, rows, key, cutoff, labels, higher_is_worse=True):
    flagged = [r["officer_id"] for r in rows
               if (r[key] is not None) and
               ((r[key] >= cutoff) if higher_is_worse else (r[key] <= cutoff))]
    tp, n, p, rec = score(flagged, labels)
    print("  %-34s flagged %2d  caught %d/%d  precision %4.0f%%  recall %4.0f%%"
          % (name, n, tp, sum(labels.values()), p * 100, rec * 100))
    return flagged


def main():
    con = connect()
    labels = truth(con)
    frauds = sorted(o for o, f in labels.items() if f)
    print("fraudulent officers (ground truth):", frauds)
    print()

    # ---------------------------------------------------------------- rule 1
    print("RULE 1  collection rate vs branch peers")
    r1 = run(con, "01_officer_peer_gap.sql")
    for r in r1[:4]:
        print("   officer %2d  mean gap %6.2f pp  %2d/%2d months below%s"
              % (r["officer_id"], r["mean_gap_pp"], r["months_below_peers"],
                 r["months_observed"], "   <-- FRAUD" if labels[r["officer_id"]] else ""))
    report("cutoff mean gap <= -3.5pp", r1, "mean_gap_pp", -3.5, labels, False)

    # ---------------------------------------------------------------- rule 2
    print()
    print("RULE 2  borrowers contradicting their own history")
    r2 = run(con, "02_delinquency_contradiction.sql")
    for r in r2[:4]:
        print("   officer %2d  %5.2f%% of book contradicts (%d borrowers)%s"
              % (r["officer_id"], r["pct_of_book"], r["contradicting_borrowers"],
                 "   <-- FRAUD" if labels[r["officer_id"]] else ""))
    report("cutoff >= 4% of book", r2, "pct_of_book", 4.0, labels)

    # ---------------------------------------------------------------- rule 3
    print()
    print("RULE 3  short payments in excess of branch peers")
    r3 = run(con, "03_short_payment_concentration.sql")
    for r in r3[:4]:
        print("   officer %2d  short %5.2f%%  peers %5.2f%%  excess %+5.2f pp%s"
              % (r["officer_id"], r["pct_short"], r["peer_pct_short"], r["excess_pp"],
                 "   <-- FRAUD" if labels[r["officer_id"]] else ""))
    report("cutoff excess >= 1.0pp", r3, "excess_pp", 1.0, labels)

    # ---------------------------------------------------------------- rule 4
    print()
    print("RULE 4  Benford first-digit deviation")
    r4 = run(con, "04_benford_first_digit.sql")
    mads = []
    for r in r4:
        n = r["n"]
        obs = [r["d%d" % d] / n for d in range(1, 10)]
        mad = sum(abs(o - e) for o, e in zip(obs, BENFORD)) / 9.0
        mads.append((mad, r["officer_id"]))
    mads.sort(reverse=True)
    for mad, oid in mads[:4]:
        print("   officer %2d  MAD %.4f%s"
              % (oid, mad, "   <-- FRAUD" if labels[oid] else ""))
    flagged = [oid for mad, oid in mads[:3]]
    tp, n, p, rec = score(flagged, labels)
    print("  %-34s flagged %2d  caught %d/%d  precision %4.0f%%  recall %4.0f%%"
          % ("top 3 by deviation", n, tp, len(frauds), p * 100, rec * 100))
    print("  NOTE: Benford does not apply to formulaic installment amounts.")
    print("        Reported for completeness, not used in the combined score.")

    # ---------------------------------------------------------------- combined
    print()
    print("COMBINED  rank-based vote: top 3 on each of rules 1-3")
    # Ranking rather than absolute cutoffs. A threshold tuned until it works is
    # a threshold fitted to labels we would not have in production; a rank says
    # "these are the three worst on this measure", which needs no tuning.
    votes = {}
    for rows, key, hiw in ((r1, "mean_gap_pp", False),
                           (r2, "pct_of_book", True),
                           (r3, "excess_pp", True)):
        ranked = sorted((r for r in rows if r[key] is not None),
                        key=lambda r: r[key], reverse=hiw)
        for r in ranked[:3]:
            votes[r["officer_id"]] = votes.get(r["officer_id"], 0) + 1
    for oid, v in sorted(votes.items(), key=lambda kv: -kv[1]):
        print("   officer %2d  %d votes%s"
              % (oid, v, "   <-- FRAUD" if labels[oid] else ""))
    flagged = [o for o, v in votes.items() if v >= 2]
    tp, n, p, rec = score(flagged, labels)
    print("  %-34s flagged %2d  caught %d/%d  precision %4.0f%%  recall %4.0f%%"
          % ("2 or more votes", n, tp, len(frauds), p * 100, rec * 100))

    con.close()


if __name__ == "__main__":
    main()
