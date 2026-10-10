"""The README promises anyone can reproduce every number. Check that it is true.

    python tests/test_reproducibility.py

Two directions, and both matter:

  SAME SEED -> IDENTICAL PORTFOLIO. This is the claim the README makes, and it
  is what makes every figure in the project checkable by a stranger. If one
  unseeded call to `random` crept into the generator, the portfolio would drift
  slightly on every run, the README's numbers would slowly stop matching, and
  nothing would announce it.

  DIFFERENT SEED -> GENUINELY DIFFERENT PORTFOLIO. Different officers stealing
  from different borrowers. Without this, the sensitivity sweep in
  analysis/sensitivity.py would be twenty copies of the same portfolio and its
  confidence figures would be worthless.

The portfolio is compared by hashing the tables, not by eyeballing a total.
Equal row counts and equal sums can hide a reordering or a swap.

Takes about 25 seconds: it builds three portfolios from scratch.
"""

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

PUBLISHED_SEED = 20260830
OTHER_SEED = 19990101

# Hashing every table would also hash the schema and the indexes. These are the
# four that carry the simulation's content: what was owed, what the books say
# arrived, who was stealing, and what actually happened.
TABLES = ("repayment_schedule", "repayments_recorded",
          "ground_truth_officers", "ground_truth_repayments")

failures = []


def generate(seed, db_path):
    env = dict(os.environ)
    env["MFD_SEED"] = str(seed)
    env["MFD_DB_PATH"] = db_path
    proc = subprocess.run([sys.executable, "generate.py"], cwd=SRC, env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("generate.py failed for seed %d:\n%s"
                           % (seed, proc.stderr[-2000:]))


def fingerprint(db_path):
    """One hash per table, over every row in a deterministic order."""
    con = sqlite3.connect(db_path)
    out = {}
    for table in TABLES:
        h = hashlib.sha256()
        # ORDER BY the primary key, so the hash reflects content and not the
        # order sqlite happened to return rows in.
        for row in con.execute("SELECT * FROM %s ORDER BY 1" % table):
            h.update(repr(row).encode("utf-8"))
        out[table] = h.hexdigest()[:16]
    out["_frauds"] = tuple(sorted(
        r[0] for r in con.execute("SELECT officer_id FROM ground_truth_officers "
                                  "WHERE is_fraudulent = 1")))
    con.close()
    return out


tmp = tempfile.mkdtemp(prefix="mfd_repro_")
try:
    print("Building three portfolios: the published seed twice, then a different one\n")
    paths = {}
    for label, seed in (("a", PUBLISHED_SEED), ("b", PUBLISHED_SEED), ("c", OTHER_SEED)):
        paths[label] = os.path.join(tmp, "%s.db" % label)
        print("   seed %d -> %s.db ..." % (seed, label), end=" ", flush=True)
        generate(seed, paths[label])
        print("built")

    fp = {k: fingerprint(v) for k, v in paths.items()}

    print("\n1. The same seed must give a byte-identical portfolio")
    for table in TABLES:
        same = fp["a"][table] == fp["b"][table]
        print("   %-26s %s  %s" % (table, fp["a"][table],
                                   "identical" if same else "DIFFERS"))
        if not same:
            failures.append("%s differs between two runs of seed %d"
                            % (table, PUBLISHED_SEED))

    print("\n2. A different seed must give a genuinely different portfolio")
    differing = [t for t in TABLES if fp["a"][t] != fp["c"][t]]
    for table in TABLES:
        print("   %-26s %s  %s" % (table, fp["c"][table],
                                   "differs" if table in differing else "IDENTICAL"))
    if len(differing) < len(TABLES):
        failures.append("seed %d produced some tables identical to seed %d: %s"
                        % (OTHER_SEED, PUBLISHED_SEED,
                           set(TABLES) - set(differing)))

    print("\n3. And a different seed must move the fraud to different officers")
    print("   seed %d: officers %s" % (PUBLISHED_SEED, list(fp["a"]["_frauds"])))
    print("   seed %d: officers %s" % (OTHER_SEED, list(fp["c"]["_frauds"])))
    if fp["a"]["_frauds"] == fp["c"]["_frauds"]:
        failures.append("both seeds made the same officers fraudulent, so the "
                        "sensitivity sweep is not testing different scenarios")
    else:
        print("   different, so the sweep varies the scenario and not just the noise")

    print("\n4. The published seed is still the default in src/config.py")
    sys.path.insert(0, SRC)
    env_backup = os.environ.pop("MFD_SEED", None)
    import config as C
    if C.SEED != PUBLISHED_SEED:
        failures.append("src/config.py default SEED is %r, not the published %d. "
                        "Every number in the README was computed with the latter."
                        % (C.SEED, PUBLISHED_SEED))
        print("   DEFAULT CHANGED: %r" % (C.SEED,))
    else:
        print("   SEED = %d, unchanged" % C.SEED)
    if env_backup is not None:
        os.environ["MFD_SEED"] = env_backup
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + "=" * 70)
if failures:
    print("FAILED  %d problem(s):" % len(failures))
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("PASSED  Same seed reproduces exactly; a different seed changes the case.")
sys.exit(0)
