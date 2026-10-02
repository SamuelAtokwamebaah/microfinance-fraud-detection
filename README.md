# microfinance-fraud-detection

Catching a loan-repayment skimming scheme in a synthetic microfinance portfolio, with SQL
rules and Python anomaly detection — and measuring honestly how much it misses.

> **Every record in this repository is synthetic.** No real borrower, credit officer, branch
> or institution appears here, and no data from any real engagement has been used. The
> portfolio is generated from a fixed random seed, so anyone can reproduce it exactly.

---

## The case this rebuilds

In a Ghanaian microfinance receivership I found **GHS 58,600** that a credit officer had taken
from **27 borrowers**.

The scheme was simple. He collected repayments and did not record them. The borrowers believed
they were up to date, because they were — they had the receipts. The books showed them falling
behind, so their balances grew, and he could press them for more. Nobody caught the gap because
the officer who recorded the payments was also the officer who chased the arrears.

I found it by hand, reading reconciliations, because his collection figures were out of line
with the rest of the portfolio.

**This project asks the question the manual method could not: at scale, how much would we catch,
and how much would we miss?**

---

## What it does

It builds a 24-month microfinance loan book of 3,000 borrowers, injects a skimming scheme of the
same shape, and then tries to find it — using only what an auditor would actually have.

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
three and you also pull in officer 19, who has done nothing wrong — the cost of one more step
down the queue is one innocent colleague under suspicion.

Ranking beat every individual rule, and beat thresholds. A cutoff tuned until it works is a
cutoff fitted to labels you would not have in production; a rank needs no tuning.

### What each rule found on its own

| Rule | Precision | Recall | |
|---|---|---|---|
| Collection rate vs branch peers | 100% | 50% | catches the bold one, misses the careful one |
| Borrowers contradicting own history | 67% | 100% | compares each borrower to themselves, so a book full of market traders is not penalised |
| Short payments vs branch peers | 67% | 100% | targets the mechanism rather than the symptom |
| Benford first-digit test | 0% | 0% | **does not apply here — see below** |

Rule 1 alone misses the careful officer entirely. Requiring **two of the three rules to agree**
flags exactly two officers, and both are guilty: precision 100%, recall 100%. That agreement,
not any single rule, is what the case queue is built on.

### Catching the right money is much harder

| | Precision | Recall |
|---|---|---|
| **Officer level** — did we name the right people? | 100% | 100% |
| **Transaction level** — did we identify the right money? | 33% | 29% |

We accused 1,121 installments; 370 had actually been skimmed. **We can name the culprit with
confidence and still identify only a quarter of the theft**, because an honest short payment and
a skimmed one look identical one row at a time. Measured on this portfolio, **6.4% of recorded
installments are honest shortfalls** — about one in sixteen — and the detector has to beat that
noise floor, not a clean ledger.

This is why the real case needed full documentary evidence before it could be escalated, and
not just a suspicious collection rate. Any project reporting one blended accuracy figure is
hiding this distinction.

### Two negative results, reported rather than buried

**Benford's law does not work here.** The first-digit test is the standard tool an auditor
reaches for, and it scored zero — the three officers it flagged are all honest. Benford needs
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

Detection never reads the third layer. Neither does the dashboard. Only the evaluation code
does, after the ranking is fixed — which is the only reason the precision figures above mean
anything. In real life nobody can see that layer either, until somebody asks a borrower.

Full column-by-column detail: **[docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md)**.

### Two detection tiers

**Tier 1 — SQL rules**, the queries an auditor would run. Written in raw SQL, using CTEs and
window functions. The key idea throughout is **peer-relative comparison**: every officer is
measured against colleagues in the same branch in the same month, with his own contribution
removed from the benchmark so he cannot hide inside an average he dominates. That cancels branch
quality and seasonality, which would otherwise generate false positives.

**Tier 2 — Python statistics.** Peer-relative officer-month features, scored by a combined
z-score and by Isolation Forest, reported at both officer and transaction level.

### The dashboard

`docs/index.html` — static, dependency-free, mirroring a real escalation:

1. **Case queue** — who to look at first, and which rules fired
2. **Officer detail** — rule scores and a collection trend against branch peers
3. **Evidence pack** — the borrowers and the individual installments, with amount due,
   amount recorded and shortfall, restricted to borrowers whose first eight installments were
   clean and who then went short. That restriction is what makes it an evidence pack rather
   than a list of every late payer.

---

## Reproducing it

```bash
python run_all.py
```

That regenerates the portfolio, scores both detection tiers and rebuilds the dashboard. About
30 seconds.

Generation, the SQL tier and the dashboard need **only the Python standard library**. The
statistical tier needs pandas, numpy and scikit-learn; without them `run_all.py` skips that step
and completes the rest.

```bash
pip install -r requirements.txt    # optional, for the statistical tier
```

To run a single rule against the database yourself:

```bash
sqlite3 data/generated/portfolio.db < sql/03_short_payment_concentration.sql
```

Change `SEED` in `src/config.py` and you get a different portfolio with different fraud in
different officers. The published seed is fixed so that every number in this README is checkable.

---

## Layout

```
run_all.py                 rebuild everything, one command
requirements.txt           pinned versions for the statistical tier
src/
  config.py                every parameter of the simulation, in one file
  schema.sql               eight tables, with the three-layer separation
  generate.py              synthetic portfolio + fraud injection
  evaluate_tier1.py        scores the SQL rules against ground truth
  tier2.py                 z-score and Isolation Forest, both levels
  build_dashboard.py       assembles docs/index.html
  dashboard_template.html
sql/
  01_officer_peer_gap.sql             collection rate vs branch peers
  02_delinquency_contradiction.sql    borrowers contradicting their own history
  03_short_payment_concentration.sql  short payments vs branch peers
  04_benford_first_digit.sql          Benford test, and why it fails here
docs/
  index.html               the evidence dashboard
  DATA_DICTIONARY.md       every table and column
```

---

## Limitations, and what would come next

**One fraud pattern.** Only unrecorded-repayment skimming is implemented. The generator is built
so more can be added as plugins — forged third-party claims, dormant-account claims, ghost
borrowers — and each would exercise different rules.

**Two fraudulent officers, one seed.** With n = 2 the precision figures are indicative, not
statistical. A fuller evaluation would sweep many seeds and report a distribution rather than a
point estimate.

**Synthetic data is tidier than real data.** No duplicate borrower records, no misspelled names,
no branch that stopped reporting for a month, no system migration mid-year. Real reconciliation
work is mostly spent on exactly those problems, and none of them are here.

**No supervised model, deliberately.** With labels available it would be easy to train a
classifier and report a flattering number. That would model the injection parameters rather than
fraud, and it would not transfer. The unsupervised framing is the honest one when real labels do
not exist — which, in a live portfolio, they do not.

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
