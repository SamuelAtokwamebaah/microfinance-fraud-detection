# microfinance-fraud-detection

Catching a loan-repayment skimming scheme in a synthetic microfinance portfolio, with SQL
rules and Python anomaly detection, then measuring honestly how much it misses.

**[Open the case dashboard](https://samuelatokwamebaah.github.io/microfinance-fraud-detection/)**,
the evidence laid out the way an investigator would work it, with nothing to install.

> **Every record in this repository is synthetic.** No real borrower, credit officer, branch
> or institution appears here, and no data from any real engagement has been used. The
> portfolio is generated from a fixed random seed, so anyone can reproduce it exactly.

---

## In short

- Rebuilds a **real GHS 58,600 skimming case** I found by hand in a Ghanaian microfinance
  receivership, as a detection problem on a 3,000-borrower synthetic portfolio.
- Three SQL rules, ranked rather than thresholded, put **both fraudulent officers first and
  second** out of 20.
- Across **20 independently generated portfolios** the top of the queue is a fraudster every
  time, and both fraudsters are in the top three every time. In the top *two*, 18 times out of 20.
- Naming the culprit is easy; naming the money is not. On the published portfolio, officer level
  runs at 100% precision against **33% at transaction level**, because an honest short payment
  and a skimmed one look identical one row at a time.
- Two tools that should have worked did not, and both are reported rather than dropped: the
  **Benford first-digit test scores zero**, and **Isolation Forest loses to a plain z-score**.
- The method has a structural blind spot it cannot fix: two officers skimming in the same branch
  **conceal each other**, because each sits in the benchmark the other is judged against.

Full method and measured accuracy below. For one officer explained in plain English, see
**[docs/CASE_MEMO.md](docs/CASE_MEMO.md)**.

---

## The case this rebuilds

In a Ghanaian microfinance receivership I found **GHS 58,600** that a credit officer had taken
from **27 borrowers**.

The scheme was simple. He collected repayments and did not record them. The borrowers believed
they were up to date, because they were. They had the receipts. The books showed them falling
behind, so their balances grew, and he could press them for more. Nobody caught the gap because
the officer who recorded the payments was also the officer who chased the arrears.

I found it by hand, reading reconciliations, because his collection figures were out of line
with the rest of the portfolio.

**This project asks the question the manual method could not: at scale, how much would we catch,
and how much would we miss?**

---

## What it does

It builds a 24-month microfinance loan book of 3,000 borrowers, injects a skimming scheme of the
same shape, and then tries to find it, using only what an auditor would actually have.

| | |
|---:|:---|
| **3,000** | borrowers, 20 credit officers, 5 branches |
| **144,542** | scheduled installments over 24 months |
| **2** | officers skimming, unknown to the detection code |
| **126** | borrowers actually skimmed, lightly, over 1,271 installments |
| **GHS 122,282** | taken |

The fraud is calibrated to the real case: **many borrowers, skimmed lightly.** Each victim looks
like an ordinary late payer. The signal exists only in aggregate, which is exactly why it was
caught at officer level and not borrower level.

It also **ramps**. The scheme starts cautiously in month four and grows bolder over ten months,
because a fraud running flat out for two years is caught by any average. That turns the question
from "did we catch him?" into "in which month would we have caught him?".

---

## Results

### Catching the right people

The dashboard ranks officers by their mean position across three independent rules:

| Rank | Officer | Score | Signals |
|---|---|---|---|
| 1 | 11 | 98 | below peers · contradicts own history · short payments |
| 2 | 9 | 97 | below peers · contradicts own history · short payments |
| 3 | 19 | 79 | below peers |
| 4 | 14 | 74 | short payments |

**Officers 11 and 9 are the two fraudsters, and they sit first and second.** Investigate the top
two and you catch both with no wasted effort: precision 100%, recall 100%. Investigate the top
three and you also pull in officer 19, who has done nothing wrong. The cost of one more step
down the queue is one innocent colleague under suspicion.

| Investigate the top | Precision | Recall | |
|---|---|---|---|
| 1 | 100% | 50% | one fraudster named, one still working |
| 2 | 100% | 100% | both, with nobody wrongly accused |
| 3 | 67% | 100% | one innocent colleague pulled in |
| 5 | 40% | 100% | three innocent colleagues pulled in |

The figure that matters is **precision at the top of the queue, not at the bottom.** An
investigator with time for one officer loses nothing by starting at the top; one who works five
deep spends 60% of the effort on innocent staff.

Ranking beat every individual rule, and beat thresholds. A cutoff tuned until it works is a
cutoff fitted to labels you would not have in production; a rank needs no tuning.

### Does it survive a different portfolio?

The figures above come from one portfolio with exactly two fraudsters. With n = 2, "100% recall"
only means "we found both", and that is a much weaker statement than it looks. So the whole
pipeline was rerun across **20 independently generated portfolios**, each with different officers
stealing from different borrowers, scoring the identical ranking with no parameter changed.

```bash
python analysis/sensitivity.py
```

| Across 20 seeds | mean | sd | min | max |
|---|---|---|---|---|
| precision, top 1 | **100%** | 0 | 100% | 100% |
| recall, top 2 | 95% | 15 | 50% | 100% |
| precision, top 2 | 95% | 15 | 50% | 100% |
| recall, top 3 | **100%** | 0 | 100% | 100% |
| 2-of-3 rule, recall | **100%** | 0 | 100% | 100% |
| 2-of-3 rule, precision | 90% | 15 | 67% | 100% |

**The top of the queue was a fraudster in all 20 portfolios, and both fraudsters were inside the
top three in all 20.** The worst any fraudster ever ranked was third.

Where it degrades is the top *two*: in 18 of 20 portfolios both fraudsters sat first and second,
and in the other two one of them slipped to third. So the honest version of the headline is not
"precision 100%, recall 100%" but this:

> Start at the top of the queue and the first officer is guilty. Work three deep and you will
> have both, every time, at the cost of one innocent colleague under suspicion.

That is a weaker claim than the single-seed numbers support, and it is the one the evidence
actually carries.

### The two fraudsters hide inside each other

Officers 11 and 9 are both in the Ho branch, and the peer benchmark removes only
the officer being scored, not the other one. So each fraudster's skimming is
sitting in the benchmark the other is judged against.

| Officer 11's short-payment rate against | Benchmark | He is |
|---|---|---|
| the branch, as the rule computes it | 8.44% | 1.59x his peers |
| the branch excluding officer 9 | 6.51% | **2.07x his peers** |

**Peer-relative detection understates collusion, and understates coincidence
too.** It does not need two officers to be working together, only to be in the
same branch at the same time. The more of a branch that is skimming, the more
normal skimming looks there, and a whole branch doing it would read as clean.
That is a structural limit of the method rather than a tuning problem, and it is
the main reason the rules are a queue for human review and not a verdict.

### What each rule found on its own

| Rule | Precision | Recall | |
|---|---|---|---|
| Collection rate vs branch peers | 100% | 50% | catches the bold one, misses the careful one |
| Borrowers contradicting own history | 67% | 100% | compares each borrower to themselves, so a book full of market traders is not penalised |
| Short payments vs branch peers | 67% | 100% | targets the mechanism rather than the symptom |
| Benford first-digit test | 0% | 0% | **does not apply here, see below** |

Rule 1 alone misses the careful officer entirely. Requiring **two of the three rules to agree**
flags exactly two officers, and both are guilty: precision 100%, recall 100%. That agreement,
not any single rule, is what the case queue is built on.

### Catching the right money is much harder

| | Precision | Recall |
|---|---|---|
| **Officer level**: did we name the right people? | 100% | 100% |
| **Transaction level**: did we identify the right money? | 33% | 29% |

We accused 1,121 installments; 370 had actually been skimmed. **We can name the culprit with
confidence and still identify only a quarter of the theft**, because an honest short payment and
a skimmed one look identical one row at a time. Measured on this portfolio, **6.4% of recorded
installments are honest shortfalls**, about one in sixteen, and the detector has to beat that
noise floor, not a clean ledger.

This is why the real case needed full documentary evidence before it could be escalated, and
not just a suspicious collection rate. Any project reporting one blended accuracy figure is
hiding this distinction.

### Two negative results, reported rather than buried

**Benford's law does not work here.** The first-digit test is the standard tool an auditor
reaches for, and it scored zero. The three officers it flagged are all honest. Benford needs
values spanning orders of magnitude from a multiplicative process. Repayment installments are a
formula repeated identically for 104 weeks, so the same leading digit recurs dozens of times per
loan. The digit distribution describes the loan book, not the officer.

**Isolation Forest lost to a z-score.** The simple combined z-score ranked both fraudsters first
and second (67% precision at a top-three cut, 100% recall). Isolation Forest ranked one of them *fourth* (33% / 50%).
Three reasons: only four features, where the method earns its keep in high dimensions; it scores
each month independently, so it has no concept of persistence; and the ramp means early fraud
months look normal and dilute the officer's average.

---

## How it works

### Three layers, and a wall between them

```
repayment_schedule      what the borrower was CONTRACTED to pay      detection ✓
repayments_recorded     what the BOOKS say arrived                   detection ✓
ground_truth_*          what ACTUALLY happened at the doorstep       evaluation only
```

Detection never reads the third layer. The ranking, the SQL rules and the evidence pack are
computed without it, and only the evaluation code reads it, after the ranking is already fixed.
That is the only reason the precision figures above mean anything. The dashboard shows
ground-truth figures in one clearly marked scoreboard panel, loaded separately from the case
queue and incapable of influencing it. In real life nobody can see that layer either, until
somebody asks a borrower.

This is the project's one silent failure mode: if the wall were ever breached, nothing would
crash and no number would look wrong, they would just all be circular. So it is checked by
machine rather than asserted here. `tests/test_layer_separation.py` parses every module and
every SQL file and fails if any function outside an explicit evaluation allowlist so much as
mentions a ground-truth table.

Full column-by-column detail: **[docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md)**.

### Two detection tiers

**Tier 1, the SQL rules.** These are the queries an auditor would run, written in raw SQL
using CTEs and window functions. The key idea throughout is **peer-relative comparison**:
every officer is measured against colleagues in the same branch in the same month, with his
own contribution removed from the benchmark so he cannot hide inside an average he dominates.
That cancels branch quality and seasonality, which would otherwise generate false positives.

**Tier 2, Python statistics.** Peer-relative officer-month features, scored by a combined
z-score and by Isolation Forest, reported at both officer and transaction level.

### The dashboard

[**Live at samuelatokwamebaah.github.io/microfinance-fraud-detection**](https://samuelatokwamebaah.github.io/microfinance-fraud-detection/),
built from `docs/index.html`. Static, dependency-free, mirroring a real escalation:

A worked example of reading the queue, written for a non-technical investigator
and using only figures from the run, is in
**[docs/CASE_MEMO.md](docs/CASE_MEMO.md)**.

1. **Case queue**: who to look at first, and which rules fired
2. **Officer detail**: rule scores and a collection trend against branch peers
3. **Evidence pack**: the borrowers and the individual installments, with amount due,
   amount recorded and shortfall, restricted to borrowers whose first eight installments were
   clean and who then went short. That restriction is what makes it an evidence pack rather
   than a list of every late payer.

---

## Reproducing it

```bash
python run_all.py                  # portfolio, both tiers, dashboard. About 30 seconds
python tests/run_tests.py          # four tests, no framework needed
python analysis/sensitivity.py     # the 20-seed sweep. About 3 minutes
```

Generation, the SQL tier, the dashboard and the tests need **only the Python standard library**.
The statistical tier needs pandas, numpy and scikit-learn (`pip install -r requirements.txt`);
without them `run_all.py` skips that step and completes the rest.

To run a single rule against the database yourself, or to generate a different portfolio without
editing any file:

```bash
sqlite3 data/generated/portfolio.db < sql/03_short_payment_concentration.sql
MFD_SEED=12345 MFD_DB_PATH=data/generated/scratch.db python src/generate.py
```

The published seed is fixed, so every number in this README is checkable.

The tests exist for failures that would not announce themselves: detection code reading the
ground-truth tables, which would make every precision figure circular while breaking nothing;
the SQL mishandling an empty peer group; an unseeded call to `random` making these numbers drift;
and the observation window in `sql/` falling out of step with `config.py`.

---

## Layout

```
run_all.py                 rebuild everything, one command
src/
  config.py                every parameter of the simulation, in one file
  schema.sql               eight tables, with the three-layer separation
  generate.py              synthetic portfolio + fraud injection
  evaluate_tier1.py        scores the SQL rules against ground truth
  tier2.py                 z-score and Isolation Forest, both levels
  build_dashboard.py       assembles docs/index.html
sql/
  01_officer_peer_gap.sql             collection rate vs branch peers
  02_delinquency_contradiction.sql    borrowers contradicting their own history
  03_short_payment_concentration.sql  short payments vs branch peers
  04_benford_first_digit.sql          Benford test, and why it fails here
tests/                     four tests, run_tests.py runs them all
analysis/sensitivity.py    the same ranking across 20 generated portfolios
docs/
  index.html               the evidence dashboard
  CASE_MEMO.md             the top-ranked officer explained in plain English
  DATA_DICTIONARY.md       every table and column
```

---

## Scope and limits

**What it catches.** Repayment skimming by a credit officer: money collected from the borrower
and not entered, or entered short. It catches it at officer level, from aggregate patterns,
without needing to know which installments were taken.

**What it misses, by design.** Each of these would need a different rule, and none would show up
in the three used here.

| Scheme | Why these rules cannot see it |
|---|---|
| Ghost loans | The money never reaches a borrower, so there is no repayment pattern to be out of line. Needs borrower-existence checks, not collection analysis. |
| Branch-manager collusion | The benchmark is the branch. Corrupt the branch and you corrupt the benchmark, as the Ho result above shows at a smaller scale. |
| Disbursement theft | Happens before the first installment is due. These rules read only the repayment side. |
| New-borrower schemes | Rule 2 compares a borrower to their own earlier history. A borrower with no history has nothing to contradict. |

**Where it fails outright: a one-officer branch.** Rules 1 and 3 compare an officer to his branch
colleagues with his own figures removed from the benchmark. Remove the only officer in a branch
and the benchmark is empty, so he scores nothing on both rules, and `build_dashboard.py` then
assigns him the worst rank, which makes him look **less** suspicious rather than more. That is
the safe direction to fail in, but an officer working a branch alone is invisible to two of the
three rules. With two officers the rules do run, on a peer group of one, which is noisy rather
than absent. The generated portfolio always has four officers per branch, so this never arises
there, which is exactly why it needed a test rather than a reading of the output:
`tests/test_edge_cases.py`.

**What it assumes about the data, and real data breaks all of it.** A clean officer-to-borrower
mapping, a complete repayment ledger, and branch assignments that hold still across the window.
The synthetic portfolio has no duplicate borrower records, no misspelled names, no branch that
stopped reporting for a month, no system migration mid-year. Real reconciliation work is mostly
spent on exactly those problems, and none of them are here.

**Two fraudulent officers per portfolio.** The seed sweep settles half of this, giving a
distribution across 20 portfolios instead of a point estimate. It does not settle the other
half: each portfolio still holds exactly two fraudsters, because that is what the real case had,
so within any one portfolio recall moves in steps of 50%. The sweep answers whether the method
holds up across fraud scenarios, not how precise any single estimate is.

**One fraud pattern.** Only unrecorded-repayment skimming is implemented. The generator takes
more as plugins: forged third-party claims, dormant-account claims, ghost borrowers.

**No supervised model, deliberately.** With labels available it would be easy to train a
classifier and report a flattering number. That would model the injection parameters rather than
fraud, and it would not transfer. The unsupervised framing is the honest one when real labels do
not exist, and in a live portfolio they do not.

**Detection is not proof.** Everything here produces a ranked suspicion and a documented
shortfall. In the real case that was the beginning of an investigation, not the end of one.

---

## Related work

This is the second of four repositories, each asking a different question about the same
subject: what failed in Ghana's deposit-taking sector, and what would have caught it.

| | repository | question |
|---|---|---|
| 1 | [`ghana-banking-collapse`](https://github.com/SamuelAtokwamebaah/ghana-banking-collapse) | *which* institutions failed, and why |
| 2 | **`microfinance-fraud-detection`** | how much of a repayment-skimming scheme detection would catch |
| 3 | `related-party-lending-network` (next in the series) | how insiders were structurally connected |
| 4 | `act-930-resolution-timelines` (published with the article) | how long the regulator left insolvent institutions licensed |

This one is the only project in the set built on synthetic data, because it is the only one
asking what a detection method would catch rather than what a published record shows.

---

## Licence

MIT. See [LICENSE](LICENSE).
