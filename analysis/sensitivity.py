"""How much of the headline result is the method, and how much is one lucky seed?

    python analysis/sensitivity.py            # 20 seeds, the published sweep
    python analysis/sensitivity.py --seeds 5  # quicker, while developing

THE PROBLEM THIS EXISTS TO ANSWER

The README reports precision 100% and recall 100% at officer level. Both numbers
come from a single portfolio containing exactly two fraudulent officers. With
n = 2, "100% recall" means "we found both of them", and the honest reading of
that is much weaker than the number looks: one different draw of victims, one
slightly more careful officer, and it is 50%.

So this script does the only thing that settles it. It regenerates the entire
portfolio from scratch under many different seeds, each with different officers
stealing from different borrowers, and scores the SAME ranking every time. The
output is a distribution rather than a point estimate.

WHAT IS HELD FIXED, AND WHY THAT MATTERS

The seed changes. Nothing else does. Every detection parameter, every cutoff,
every rule stays exactly as published. If the rules had been tuned to this
portfolio, that tuning would not survive here, and the sweep would show it.

This script also imports the ranking from build_dashboard rather than
reimplementing it. A sweep that scores its own private copy of the ranking logic
proves nothing about the published one.

WHAT IT CANNOT DO

Each seed still contains only two fraudulent officers, because that is what the
real case had. The sweep gives a distribution over portfolios; it does not turn
n = 2 into a large sample within any one portfolio. It answers "does the method
hold up across fraud scenarios", not "how precise is this estimate".
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

import build_dashboard as BD          # noqa: E402  the published ranking
import evaluate_tier1 as E1           # noqa: E402  the published 2-of-3 vote

# Seeds are not random. They are a fixed, published list, so that this sweep is
# as reproducible as the single run it is testing. A sweep over seeds chosen at
# runtime would give a different answer every time it ran, which defeats it.
SEEDS = [20260830 + i * 101 for i in range(20)]

AT_K = (1, 2, 3, 5)


def generate(seed, db_path):
    """Run the real generator in a subprocess, with the seed overridden."""
    env = dict(os.environ)
    env["MFD_SEED"] = str(seed)
    env["MFD_DB_PATH"] = db_path
    proc = subprocess.run([sys.executable, "generate.py"], cwd=SRC, env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("generate.py failed for seed %d:\n%s"
                           % (seed, proc.stderr[-2000:]))


def score_one(db_path):
    """Everything measured on one portfolio. Returns a dict of metrics."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    cases = BD.build_cases(con)                      # the published ranking
    labels = E1.truth(con)
    frauds = {o for o, f in labels.items() if f}
    ranked = [c["officer_id"] for c in cases]

    out = {"n_frauds": len(frauds), "fraud_officers": sorted(frauds)}

    # Precision and recall as an investigator walks down the queue.
    for k in AT_K:
        caught = len(set(ranked[:k]) & frauds)
        out["p_at_%d" % k] = 100.0 * caught / k
        out["r_at_%d" % k] = 100.0 * caught / len(frauds)

    # The 2-of-3 agreement rule, which is what the README's headline rests on.
    r1 = BD.run_sql(con, "01_officer_peer_gap.sql")
    r2 = BD.run_sql(con, "02_delinquency_contradiction.sql")
    r3 = BD.run_sql(con, "03_short_payment_concentration.sql")
    votes = {}
    for rows, key, higher_is_worse in ((r1, "mean_gap_pp", False),
                                       (r2, "pct_of_book", True),
                                       (r3, "excess_pp", True)):
        usable = [r for r in rows if r.get(key) is not None]
        for r in sorted(usable, key=lambda r: r[key], reverse=higher_is_worse)[:3]:
            votes[r["officer_id"]] = votes.get(r["officer_id"], 0) + 1
    flagged = {o for o, v in votes.items() if v >= 2}
    caught = len(flagged & frauds)
    out["vote_flagged"] = len(flagged)
    out["vote_precision"] = 100.0 * caught / len(flagged) if flagged else 0.0
    out["vote_recall"] = 100.0 * caught / len(frauds)

    # Where in the queue did each fraudster actually land? This is the number a
    # mean hides: "recall 50%" says one was missed, not how nearly it was caught.
    out["fraud_positions"] = sorted(ranked.index(o) + 1 for o in frauds
                                    if o in ranked)
    con.close()
    return out


def describe(values):
    """mean, standard deviation, min, max. Written out rather than imported,
    because this script must run on a bare standard library like the rest of
    the SQL tier."""
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n if n > 1 else 0.0
    return mean, var ** 0.5, min(values), max(values)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=len(SEEDS),
                    help="how many of the published seed list to run")
    args = ap.parse_args()
    seeds = SEEDS[:max(1, args.seeds)]

    tmp = tempfile.mkdtemp(prefix="mfd_sweep_")
    started = time.time()
    runs = []
    try:
        for i, seed in enumerate(seeds, 1):
            db = os.path.join(tmp, "seed_%d.db" % seed)
            print("[%2d/%d] seed %d ..." % (i, len(seeds), seed), end=" ", flush=True)
            generate(seed, db)
            r = score_one(db)
            r["seed"] = seed
            runs.append(r)
            print("fraudsters %s at queue positions %s   P@2 %3.0f%%  R@2 %3.0f%%"
                  % (r["fraud_officers"], r["fraud_positions"],
                     r["p_at_2"], r["r_at_2"]))
            os.remove(db)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 78)
    print("  SENSITIVITY OVER %d SEEDS       (%.0fs)" % (len(runs), time.time() - started))
    print("=" * 78)
    print("\n  Walking down the case queue:\n")
    print("  %-26s %8s %8s %8s %8s" % ("", "mean", "sd", "min", "max"))
    for k in AT_K:
        for metric, label in (("p_at_%d" % k, "precision @ top %d" % k),
                              ("r_at_%d" % k, "recall @ top %d" % k)):
            m, sd, lo, hi = describe([r[metric] for r in runs])
            print("  %-26s %7.1f%% %7.1f%% %7.0f%% %7.0f%%" % (label, m, sd, lo, hi))
        print()

    print("  The 2-of-3 agreement rule:\n")
    for metric, label in (("vote_precision", "precision"),
                          ("vote_recall", "recall"),
                          ("vote_flagged", "officers flagged")):
        m, sd, lo, hi = describe([r[metric] for r in runs])
        unit = "" if metric == "vote_flagged" else "%"
        print("  %-26s %7.1f%s %7.1f%s %7.0f%s %7.0f%s"
              % (label, m, unit, sd, unit, lo, unit, hi, unit))

    # The distribution that matters most: how often is a fraudster missed
    # entirely from the top of the queue?
    print("\n  Both fraudsters in the top 2: %d of %d seeds"
          % (sum(1 for r in runs if r["r_at_2"] == 100.0), len(runs)))
    print("  Both fraudsters in the top 3: %d of %d seeds"
          % (sum(1 for r in runs if r["r_at_3"] == 100.0), len(runs)))
    print("  Worst queue position of any fraudster across all seeds: %d"
          % max(max(r["fraud_positions"]) for r in runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
