"""Run every test in one command.

    python tests/run_tests.py
    python tests/run_tests.py --fast     # skip the ones that rebuild portfolios

There is no pytest here, and no test framework at all, for the same reason the
SQL tier needs only the standard library: a reviewer should be able to clone
this repository and run everything without installing anything first.

Three tests, in increasing cost:

    layer_separation   reads the source. Instant. The most important one, because
                       the failure it guards against is silent.
    edge_cases         builds a tiny awkward portfolio in memory. About a second.
    reproducibility    rebuilds three full portfolios. About 25 seconds.
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

TESTS = [
    ("layer_separation", "test_layer_separation.py",
     "detection code is blind to ground truth", False),
    ("edge_cases", "test_edge_cases.py",
     "the SQL survives an empty peer group", False),
    ("reproducibility", "test_reproducibility.py",
     "same seed reproduces, different seed differs", True),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true",
                    help="skip tests that rebuild portfolios")
    args = ap.parse_args()

    started = time.time()
    results = []
    for name, script, blurb, slow in TESTS:
        if slow and args.fast:
            print("\n--- %s: SKIPPED (--fast) ---" % name)
            continue
        print("\n" + "=" * 72)
        print("  %s  -  %s" % (name, blurb))
        print("=" * 72)
        code = subprocess.call([sys.executable, os.path.join(HERE, script)])
        results.append((name, code))

    print("\n" + "=" * 72)
    failed = [n for n, c in results if c != 0]
    for name, code in results:
        print("  %-20s %s" % (name, "PASSED" if code == 0 else "FAILED"))
    print("  %.1fs" % (time.time() - started))
    if failed:
        print("\nFAILED: %s" % ", ".join(failed))
        return 1
    print("\nAll tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
