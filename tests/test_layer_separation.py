"""Prove the wall between detection and ground truth, rather than asserting it.

    python tests/test_layer_separation.py

The README makes one claim that everything else depends on: detection code never
reads the ground_truth_* tables, so the precision and recall figures are not
circular. If that wall were ever breached, every number in the project would
become meaningless, and nothing would break, nothing would crash, and no output
would look wrong. It is the project's one silent failure mode.

So it is checked by reading the source, not by running it. A test that executes
the pipeline and inspects the answer cannot tell a clean result from a leaked
one. A test that parses the code can.

The method: parse each module with `ast`, walk the function definitions, and
check which functions mention a ground-truth table. Only an explicit allowlist
of evaluation functions may. Anything else is a leak, including a function added
next year by someone who has not read this file.
"""

import ast
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUND_TRUTH = ("ground_truth_officers", "ground_truth_repayments")

# Functions permitted to read the third layer. Each is scoring AFTER a ranking
# is fixed, never feeding one. Adding a name here should require an argument.
ALLOWED = {
    # The generator CREATES the third layer, so of course it writes to it.
    # It is the only module that may, and only in the function that persists.
    "src/generate.py": {"<module>", "write_db"},
    "src/evaluate_tier1.py": {"<module>", "truth"},
    "src/tier2.py": {"<module>", "main", "officer_level", "transaction_level"},
    # The dashboard reads ground truth in exactly one function, which renders a
    # separate, clearly-labelled scoreboard panel. build_cases must stay blind.
    "src/build_dashboard.py": {"<module>", "build_evaluation"},
}

DETECTION_MUST_BE_BLIND = ["src/build_dashboard.py"]
BLIND_FUNCTIONS = ["build_cases", "rank_map", "build_evidence"]

failures = []
checked = 0


def read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


def owner_of_line(tree, lineno):
    """Which function definition contains this line? '<module>' if none."""
    best = ("<module>", -1)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= lineno <= end and node.lineno > best[1]:
                best = (node.name, node.lineno)
    return best[0]


# ------------------------------------------------------------------ 1. SQL tier
# The rules an auditor runs. These must contain no reference at all.
print("1. The SQL rules must not mention ground truth")
for fn in sorted(os.listdir(os.path.join(ROOT, "sql"))):
    if not fn.endswith(".sql"):
        continue
    checked += 1
    body = read("sql/" + fn).lower()
    hits = [t for t in GROUND_TRUTH if t in body]
    if hits:
        failures.append("sql/%s reads %s" % (fn, ", ".join(hits)))
    print("   %-40s %s" % (fn, "LEAK: " + str(hits) if hits else "blind"))

# ------------------------------------------------- 2. Python, function by function
print("\n2. In Python, only allowlisted functions may read it")
for rel, allowed in sorted(ALLOWED.items()):
    src = read(rel)
    tree = ast.parse(src)
    offenders = {}
    for i, line in enumerate(src.splitlines(), 1):
        if any(t in line for t in GROUND_TRUTH):
            owner = owner_of_line(tree, i)
            if owner not in allowed:
                offenders.setdefault(owner, []).append(i)
    checked += 1
    if offenders:
        for owner, lines in offenders.items():
            failures.append("%s: %s() reads ground truth at line %s"
                            % (rel, owner, ", ".join(map(str, lines))))
        print("   %-26s LEAK in %s" % (rel, ", ".join(offenders)))
    else:
        print("   %-26s only %s" % (rel, ", ".join(sorted(allowed - {"<module>"}))))

# --------------------------------------------- 3. The ranking itself, explicitly
# Belt and braces. build_cases produces the case queue; if it ever sees a label,
# the ranking is fitted to the answer.
print("\n3. The ranking functions, named explicitly")
for rel in DETECTION_MUST_BE_BLIND:
    src = read(rel)
    tree = ast.parse(src)
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in BLIND_FUNCTIONS:
            continue
        checked += 1
        body = ast.get_source_segment(src, node) or ""
        hits = [t for t in GROUND_TRUTH if t in body]
        if hits:
            failures.append("%s: %s() must be blind but reads %s"
                            % (rel, node.name, hits))
        found.add(node.name)
        print("   %-26s %-18s %s"
              % (rel, node.name + "()", "LEAK" if hits else "blind"))
    # A renamed or deleted function would otherwise make this section pass
    # vacuously, which is worse than having no section at all.
    for missing in sorted(set(BLIND_FUNCTIONS) - found):
        failures.append("%s: expected a function named %s() to check, and found "
                        "none. If it was renamed, update BLIND_FUNCTIONS."
                        % (rel, missing))
        print("   %-26s %-18s NOT FOUND" % (rel, missing + "()"))

# ------------------------------------------- 4. The published payload, at runtime
# The dashboard ships a JSON blob to the browser. If a label reached it, anyone
# opening the page could read the answer out of the source.
print("\n4. The shipped dashboard must not contain the labels in its case queue")
page = os.path.join(ROOT, "docs", "index.html")
if os.path.exists(page):
    import json
    import re
    html = io.open(page, encoding="utf-8").read()
    m = re.search(r"const\s+DATA\s*=\s*(\{.*?\});", html, re.S)
    if m:
        checked += 1
        data = json.loads(m.group(1))
        leaked = [k for c in data.get("cases", [])
                  for k in c if "fraud" in k.lower() or "truth" in k.lower()]
        if leaked:
            failures.append("docs/index.html case queue carries %s" % set(leaked))
        print("   case queue keys carrying a label: %s"
              % (sorted(set(leaked)) if leaked else "none"))
        print("   (the evaluation panel may and does: %s)"
              % ("present" if "evaluation" in data else "absent"))
    else:
        print("   SKIPPED: could not locate the DATA payload")
else:
    print("   SKIPPED: docs/index.html not built")

# ------------------------------------------------------------------ verdict
print("\n" + "=" * 70)
if failures:
    print("FAILED  %d checks run, %d leak(s):" % (checked, len(failures)))
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("PASSED  %d checks run. Detection is blind to ground truth." % checked)
sys.exit(0)
