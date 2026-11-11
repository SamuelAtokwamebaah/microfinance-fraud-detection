# Verification: what went wrong here, and what caught it

This project ranks loan officers by how likely their collection records are to
be fraudulent. A detection system that reports its own precision is making a
claim about its own correctness, and that claim is only as good as the record of
how it was tested.

This file is that record: every error found, what it would have cost, and the
thing that found it. It is organised by **what caught it** rather than by who
caused it. The project was built with heavy use of an AI assistant and the
history does not record which lines came from which of us, so blame would be
unverifiable in most of these entries. The mechanism is recoverable in all of
them.

Two entries here are the strongest in any of these five repositories, for
opposite reasons. One is a headline that was true and meaningless. The other is
a circularity that would have invalidated every figure in the project **and
crashed nothing**, caught by a test written before it happened.

| caught by | entries |
|---|---:|
| rebuilding under many random seeds instead of one | 1 |
| writing a test for a failure that had not happened | 1 |
| a pre-publication audit of the partition logic | 1 |
| reading the code against the claim made about it | 1 |
| an edge-case test | 1 |
| recount | 1 |
| checking a review's claims against the file | 1 |

---

## Caught by rebuilding under many random seeds instead of one

### 1. Precision 100% and recall 100%, from a single portfolio with two fraudsters

The headline was **precision 100% and recall 100%**. Both figures were correct.
Both were close to meaningless, because they were measured on one synthetic
portfolio containing exactly two fraudulent officers. With two positives in the
population, "caught both, flagged nobody else" is a far weaker statement than
two perfect percentages make it sound, and the percentages are what a reader
remembers.

`analysis/sensitivity.py` now rebuilds the entire portfolio under **20 published
seeds** and scores the identical ranking, importing it from the dashboard
builder rather than reimplementing it. The result:

- the top of the queue was a fraudster in **all 20** portfolios
- both fraudsters sat inside the top three in **all 20**
- but **only 18 of 20** had both inside the top two

The README headline is now that weaker claim, which is what the evidence
carries.

**What it would have cost.** Nothing in the code. Everything in credibility. A
practitioner reading "100% precision" on a two-positive sample knows
immediately that the author either has not thought about it or is hoping the
reader will not. The figure was an invitation to be dismissed.

**The lesson.** A perfect score on a small sample is a statement about the
sample. The fix was not a better model, it was a harder question asked of the
same model.

---

## Caught by writing a test for a failure that had not happened

### 2. The circularity that would have invalidated everything and broken nothing

If the detection layer had ever read the ground-truth tables, every precision
figure in the project would have become circular. The system would have been
reporting that it could find the fraudsters it had been told about.

**Nothing would have crashed.** Nothing would have looked wrong. The numbers
would have improved.

A test now parses every module with Python's `ast` and fails if any function
outside an explicit evaluation allowlist so much as mentions a ground-truth
table. It was verified twice over: by **injecting a leak** into the case builder
to confirm the test fires, and by **renaming the test function** to confirm it
cannot pass vacuously.

This entry records a failure that did not occur. It is here because the test is
the most valuable thing in the repository and the reasoning behind it is worth
more than the code: the faults that matter most are the ones with no symptom,
and the only defence against a fault with no symptom is a check written in
advance of it.

---

## Caught by a pre-publication audit of the partition logic

### 3. A window partitioned by loan when it should have been by borrower

**This one changed a published result.**

Rule 2 asks whether a borrower's recent payment behaviour contradicts their own
earlier history. The early and later windows were partitioned **by loan** rather
than **by borrower**. Twenty-nine per cent of borrowers take a second loan, so
that second loan's first eight instalments were scored as "early history"
despite falling late in time, inside the fraud window.

The fix changed what the project reports: rule 2 now catches **both** fraudulent
officers rather than one, and requiring two of three rules to agree flags exactly
two officers, both guilty.

Fixed in `sql/02` and in the same victim-profile filter used by the tier-2 model
and the dashboard builder, so the three places that had to agree now do.

---

## Caught by reading the code against the claim made about it

### 4. A README sentence that was false about correct code

The README stated that the dashboard never reads ground truth. It does, in
`build_evaluation`, for the scoreboard panel.

The code was always correct, and the panel cannot influence the ranking. The
**sentence** was false. Corrected.

Worth recording as its own class. There was no bug. A reader auditing the
circularity question would have read that sentence, believed it, and been
misled about the one property the project most needs to be trusted on.

---

## Caught by an edge-case test

### 5. A lone officer scores as the least suspicious person in the book

An officer who is the only one in their branch has no peer benchmark. Their
score is NULL, and a NULL is then sorted to the **worst rank**, which makes them
look *less* suspicious rather than more.

The direction is safe in the sense that it does not generate a false accusation.
It is unsafe in the sense that two of the three rules cannot see such a person at
all, so a fraudulent sole officer is close to invisible to this system. Now
documented in the limitations rather than left as a property of the sort order.

---

## Caught by a recount

### 6. Borrowers selected against borrowers touched

The README said 164 borrowers were skimmed. **164 were selected and 126 were
actually touched** by the injection. Corrected.

---

## Caught by checking a review's claims against the file

### 7. A review that was itself wrong, five times

An AI-assisted review of this repository proposed around thirty additions. Five
of its "missing from the README" items **were already in the README**.

Four of its suggestions were real and were implemented. Four more were declined
on the record: a shared SQL CTE library, a dashboard payload schema, step-level
logging, and a contamination ablation for a model already reported as losing to
a plain z-score. None of them would have changed a published number.

Recorded because it is the cleanest example in this body of work of why a
reviewer's output is a hypothesis rather than a finding. Taken at face value,
five of those thirty items would have produced edits adding things that were
already there, and the declined four would have added work with no effect on any
result. Checking the review cost less than implementing it.

---

## What this record does not cover

It does not cover errors nobody has found.

It is also worth noting what this project got right that the others did not:
entry 2 is the only check in any of these five repositories that was written for
a failure that had not yet occurred, and it is the only one verified by
deliberately breaking the thing it protects. Every other guard in this body of
work was built after the fault it prevents.

This repository is closed to further review. The ledger stands as the record.

Related ledgers. Two of these repositories are private while the work in them is unfinished, so they are named rather than linked:

- `thin-file-credit-risk` (private): a train/test split that was never reproducible although every seed was fixed, a refuted prediction, a feature built on a false premise, and an exit code swallowed by a pipe.
- `act-930-resolution-timelines` (private): an abstract that contradicted the method section, twice, and a paper that misdescribed its own companion dataset.
- [`related-party-lending-network`](https://github.com/SamuelAtokwamebaah/related-party-lending-network/blob/main/docs/verification.md)
- [`ghana-banking-collapse`](https://github.com/SamuelAtokwamebaah/ghana-banking-collapse/blob/main/docs/verification.md)
