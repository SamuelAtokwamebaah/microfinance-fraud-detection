"""Tier 2: statistical anomaly detection on officer-period features.

Tier 1 asked fixed questions ("is this officer below his peers?"). Tier 2 asks
an open one: "which officer-months do not look like the rest of the portfolio?"
It needs no threshold chosen in advance, which is its advantage, and it cannot
explain itself in a sentence, which is its cost.

Two methods:

  z-score          how many standard deviations from the peer mean. Simple,
                   explainable to an audit committee, one feature at a time.
  Isolation Forest unsupervised, multivariate. Isolates points that are easy to
                   separate from the rest; easy separation means unusual.

Reported at BOTH levels, because they answer different questions:

  officer level      did we catch the right people?
  transaction level  did we identify the right money?

Only the evaluation section reads ground truth. Feature building and detection
never do.
"""

import os
import sqlite3

import numpy as np
import pandas as pd

import config as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from sklearn.ensemble import IsolationForest
    HAVE_SKLEARN = True
except ImportError:
    HAVE_SKLEARN = False


# ----------------------------------------------------------------- features

FEATURE_SQL = """
WITH paid AS (
    SELECT schedule_id, SUM(amount_recorded_ghs) AS recorded_ghs
    FROM repayments_recorded GROUP BY schedule_id
),
inst AS (
    SELECT l.officer_id,
           o.branch_id,
           l.borrower_id,
           substr(s.due_date, 1, 7)              AS period,
           s.amount_due_ghs,
           COALESCE(p.recorded_ghs, 0)           AS recorded_ghs
    FROM repayment_schedule s
    JOIN loans           l ON l.loan_id    = s.loan_id
    JOIN credit_officers o ON o.officer_id = l.officer_id
    LEFT JOIN paid       p ON p.schedule_id = s.schedule_id
    WHERE s.due_date BETWEEN '2024-01-01' AND '2025-12-31'
      AND s.amount_due_ghs > 0
)
SELECT officer_id, branch_id, period,
       COUNT(*)                                                    AS n_due,
       SUM(amount_due_ghs)                                         AS due_ghs,
       SUM(recorded_ghs)                                           AS recorded_ghs,
       SUM(CASE WHEN recorded_ghs = 0 THEN 1 ELSE 0 END)           AS n_missing,
       SUM(CASE WHEN recorded_ghs > 0
                 AND recorded_ghs < 0.95 * amount_due_ghs
                THEN 1 ELSE 0 END)                                 AS n_short,
       SUM(CASE WHEN recorded_ghs > 0 THEN 1 ELSE 0 END)           AS n_recorded,
       AVG(CASE WHEN recorded_ghs > 0
                THEN recorded_ghs / amount_due_ghs END)            AS mean_settle_ratio,
       COUNT(DISTINCT borrower_id)                                 AS n_borrowers
FROM inst
GROUP BY officer_id, branch_id, period
"""


def build_features(con):
    """One row per officer-month, then made peer-relative.

    The peer-relative step is what carried Tier 1: subtracting the branch-month
    mean removes branch quality and seasonality, so what remains is the officer.
    Feeding raw rates to an anomaly detector would mostly discover that January
    is different from June.
    """
    df = pd.read_sql_query(FEATURE_SQL, con)

    df["collection_rate"] = df["recorded_ghs"] / df["due_ghs"]
    df["short_rate"] = df["n_short"] / df["n_recorded"].replace(0, np.nan)
    df["missing_rate"] = df["n_missing"] / df["n_due"]
    df["mean_settle_ratio"] = df["mean_settle_ratio"].fillna(1.0)

    raw = ["collection_rate", "short_rate", "missing_rate", "mean_settle_ratio"]
    df[raw] = df[raw].fillna(df[raw].mean())

    # Peer-relative: this officer minus the branch-month mean of everyone else.
    out = []
    for feature in raw:
        grp = df.groupby(["branch_id", "period"])[feature]
        peer_sum, peer_n = grp.transform("sum"), grp.transform("count")
        peer_mean = (peer_sum - df[feature]) / (peer_n - 1).replace(0, np.nan)
        df[feature + "_rel"] = df[feature] - peer_mean
        out.append(feature + "_rel")

    df[out] = df[out].fillna(0.0)
    return df, out


# ----------------------------------------------------------------- detection

def zscore_scores(df, features):
    """Standardise each feature across the whole portfolio, then combine.

    A z-score says "how many standard deviations from the mean". Two sigma is
    roughly the top 2.5% of a normal distribution, which is the conventional
    place to start looking. Signs are flipped so that HIGHER always means MORE
    suspicious: low collection is bad, high short-payment rate is bad.
    """
    signs = {"collection_rate_rel": -1.0, "mean_settle_ratio_rel": -1.0,
             "short_rate_rel": 1.0, "missing_rate_rel": 1.0}
    z = pd.DataFrame(index=df.index)
    for f in features:
        mu, sd = df[f].mean(), df[f].std(ddof=0)
        z[f] = signs.get(f, 1.0) * (df[f] - mu) / (sd if sd else 1.0)
    df = df.copy()
    df["z_combined"] = z.mean(axis=1)
    return df


def isolation_forest_scores(df, features, seed):
    """Unsupervised: no labels, no thresholds, just "which points stand apart".

    contamination is the share of rows we expect to be anomalous. Set from the
    injected fraud rate rather than tuned, so this is not fitted to the answer.
    """
    if not HAVE_SKLEARN:
        df = df.copy()
        df["iforest_score"] = np.nan
        return df
    model = IsolationForest(n_estimators=300, contamination=0.06,
                            random_state=seed, n_jobs=1)
    model.fit(df[features].values)
    df = df.copy()
    # decision_function: higher is more normal. Negate so higher = more suspicious.
    df["iforest_score"] = -model.decision_function(df[features].values)
    return df


# ----------------------------------------------------------------- evaluation

def officer_level(df, labels, score_col, top_n=3):
    per_officer = df.groupby("officer_id")[score_col].mean().sort_values(ascending=False)
    flagged = list(per_officer.index[:top_n])
    frauds = {o for o, f in labels.items() if f}
    tp = len(set(flagged) & frauds)
    return per_officer, flagged, tp / len(flagged), tp / len(frauds)


def transaction_level(con, flagged_officers):
    """Which specific installments do we accuse?

    Officer-level detection names a person. An investigator then needs the
    transactions: which payments, which borrowers, how much money. We accuse
    short-paid installments belonging to a flagged officer, on borrowers whose
    earlier history was clean, which is the victim profile the scheme selects.
    """
    if not flagged_officers:
        return 0, 0, 0.0, 0.0
    placeholders = ",".join("?" for _ in flagged_officers)
    sql = """
    WITH paid AS (
        SELECT schedule_id, SUM(amount_recorded_ghs) AS recorded_ghs
        FROM repayments_recorded GROUP BY schedule_id
    ),
    inst AS (
        SELECT s.schedule_id, l.officer_id, l.borrower_id,
               s.amount_due_ghs, COALESCE(p.recorded_ghs, 0) AS recorded_ghs,
               ROW_NUMBER() OVER (PARTITION BY s.loan_id ORDER BY s.due_date) AS seq
        FROM repayment_schedule s
        JOIN loans l ON l.loan_id = s.loan_id
        LEFT JOIN paid p ON p.schedule_id = s.schedule_id
        WHERE s.due_date BETWEEN '2024-01-01' AND '2025-12-31'
          AND s.amount_due_ghs > 0
    ),
    clean_start AS (
        SELECT borrower_id
        FROM inst WHERE seq <= 8
        GROUP BY borrower_id
        HAVING AVG(CASE WHEN recorded_ghs >= 0.95 * amount_due_ghs THEN 1.0 ELSE 0.0 END) >= 0.90
    )
    SELECT i.schedule_id
    FROM inst i
    JOIN clean_start c ON c.borrower_id = i.borrower_id
    WHERE i.officer_id IN (%s)
      AND i.recorded_ghs < 0.95 * i.amount_due_ghs
    """ % placeholders
    accused = {r[0] for r in con.execute(sql, list(flagged_officers))}
    actual = {r[0] for r in con.execute(
        "SELECT schedule_id FROM ground_truth_repayments WHERE was_skimmed = 1")}
    tp = len(accused & actual)
    precision = tp / len(accused) if accused else 0.0
    recall = tp / len(actual) if actual else 0.0
    return tp, len(accused), precision, recall


# ----------------------------------------------------------------- main

def main():
    con = sqlite3.connect(os.path.join(ROOT, C.DB_PATH))
    labels = {r[0]: r[1] for r in con.execute(
        "SELECT officer_id, is_fraudulent FROM ground_truth_officers")}
    frauds = sorted(o for o, f in labels.items() if f)

    df, features = build_features(con)
    print("feature matrix: %d officer-months x %d features" % (len(df), len(features)))
    print("fraudulent officers (ground truth):", frauds)
    print("scikit-learn available:", HAVE_SKLEARN)

    df = zscore_scores(df, features)
    df = isolation_forest_scores(df, features, C.SEED)

    for label, col in (("Z-SCORE", "z_combined"), ("ISOLATION FOREST", "iforest_score")):
        if df[col].isna().all():
            print("\n%s  skipped (scikit-learn not installed)" % label)
            continue
        print("\n" + "=" * 70)
        print("%s  officer level" % label)
        print("=" * 70)
        per_officer, flagged, prec, rec = officer_level(df, labels, col)
        for oid, score in per_officer.head(5).items():
            print("   officer %2d  score %+7.3f%s"
                  % (oid, score, "   <-- FRAUD" if labels[oid] else ""))
        print("  top 3 flagged: caught %d/%d   precision %3.0f%%   recall %3.0f%%"
              % (int(prec * 3), len(frauds), prec * 100, rec * 100))

        tp, n, tprec, trec = transaction_level(con, flagged)
        print("  transaction level: accused %d installments, %d truly skimmed"
              % (n, tp))
        print("                     precision %3.0f%%   recall %3.0f%%"
              % (tprec * 100, trec * 100))

    con.close()


if __name__ == "__main__":
    main()
