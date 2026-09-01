"""Rebuild everything, from an empty checkout to the finished dashboard.

    python run_all.py

Four steps, in order, each depending on the last:

    1. generate      synthetic portfolio -> data/generated/portfolio.db
    2. evaluate      the four SQL rules, scored against ground truth
    3. tier2         z-score and Isolation Forest, scored at both levels
    4. dashboard     docs/index.html

Steps 1, 2 and 4 need only the Python standard library. Step 3 needs pandas,
numpy and scikit-learn; if they are missing it is skipped with a clear message
rather than failing the run, so a reviewer can still reproduce the SQL tier and
the dashboard from a bare Python install.

Everything derives from the single seed in src/config.py. Same seed, same
portfolio, same fraud, same numbers.
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")

STEPS = [
    ("generate",  "generate.py",        "Build the synthetic portfolio",            True),
    ("evaluate",  "evaluate_tier1.py",  "Score the SQL detection rules",            True),
    ("tier2",     "tier2.py",           "Score the statistical tier",               False),
    ("dashboard", "build_dashboard.py", "Assemble docs/index.html",                 True),
]


def run(script):
    return subprocess.call([sys.executable, script], cwd=SRC)


def have_optional_deps():
    for mod in ("pandas", "numpy", "sklearn"):
        try:
            __import__(mod)
        except ImportError:
            return False, mod
    return True, None


def main():
    ok, missing = have_optional_deps()
    started = time.time()
    failures = []

    for i, (name, script, blurb, required) in enumerate(STEPS, 1):
        print("\n" + "=" * 72)
        print("[%d/%d] %s  -  %s" % (i, len(STEPS), name, blurb))
        print("=" * 72)

        if not required and not ok:
            print("SKIPPED: %s is not installed. Install the optional dependencies with"
                  "\n         pip install -r requirements.txt" % missing)
            continue

        code = run(script)
        if code != 0:
            failures.append(name)
            if required:
                print("\nFAILED at '%s'. Later steps depend on it, so stopping here." % name)
                return 1

    print("\n" + "=" * 72)
    print("done in %.1fs" % (time.time() - started))
    if failures:
        print("steps that failed: %s" % ", ".join(failures))
        return 1
    print("dashboard: docs/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
