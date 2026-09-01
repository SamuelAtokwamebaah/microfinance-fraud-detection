"""Generate a synthetic microfinance portfolio, then inject a skimming scheme.

Run:  python src/generate.py

Everything here is synthetic. No real borrower, officer, branch or institution
is represented, and no data from any real engagement was used.

The generator produces three layers:

  1. what was CONTRACTED   -> repayment_schedule
  2. what the BOOKS say    -> repayments_recorded
  3. what ACTUALLY happened -> ground_truth_repayments   (evaluation only)

Detection code in Phase 2 reads layers 1 and 2. It never reads layer 3.
"""

import os
import random
import sqlite3
from datetime import date, timedelta

import config as C

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# One seeded generator, threaded through every random decision below. Passing it
# explicitly (rather than calling the global random module) keeps the randomness
# auditable: nothing else in the process can perturb this sequence.
RNG = random.Random(C.SEED)


# ----------------------------------------------------------------- small helpers

FIRST_NAMES = [
    "Kwame", "Ama", "Kofi", "Akosua", "Yaw", "Abena", "Kwesi", "Adwoa",
    "Kwabena", "Afua", "Kojo", "Esi", "Yaa", "Fiifi", "Araba", "Nana",
    "Kwaku", "Efua", "Atsu", "Dzifa", "Selorm", "Mawuli", "Akua", "Kobby",
]
SURNAME_INITIALS = list("ABDEFGKMNOPSTW")

OCCUPATIONS = [
    ("market trader", "low"), ("market trader", "medium"),
    ("seamstress", "low"), ("carpenter", "medium"), ("farmer", "low"),
    ("hairdresser", "low"), ("shop owner", "medium"), ("mason", "medium"),
    ("food vendor", "low"), ("mechanic", "medium"), ("teacher", "medium"),
    ("transport operator", "high"), ("wholesaler", "high"),
]

REGIONS = ["Greater Accra", "Greater Accra", "Volta", "Eastern", "Eastern"]
BRANCH_NAMES = ["Adabraka", "Madina", "Ho", "Koforidua", "Nsawam"]


def synthetic_name():
    """A plausible but non-identifying name: given name plus a single initial."""
    return "%s %s." % (RNG.choice(FIRST_NAMES), RNG.choice(SURNAME_INITIALS))


def iso(d):
    return d.isoformat()


def add_months(d, n):
    """Month arithmetic without pulling in a dependency."""
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def weighted_choice(weights):
    """weights is {value: probability}; probabilities should sum to 1."""
    r = RNG.random()
    cum = 0.0
    for value, p in weights.items():
        cum += p
        if r <= cum:
            return value
    return list(weights)[-1]


def months_between(a, b):
    return (b.year - a.year) * 12 + (b.month - a.month)


# ----------------------------------------------------------------- structure

def build_structure():
    """Branches, officers, borrowers. Deterministic shape, random detail."""
    sim_start = date.fromisoformat(C.SIM_START)

    branches, officers, borrowers = [], [], []
    officer_id = 0
    borrower_id = 0

    for b in range(C.N_BRANCHES):
        branch_id = b + 1
        branches.append((
            branch_id, BRANCH_NAMES[b], REGIONS[b],
            iso(add_months(sim_start, -RNG.randint(36, 120))),
        ))

        for _ in range(C.OFFICERS_PER_BRANCH):
            officer_id += 1
            officers.append((
                officer_id, branch_id, synthetic_name(),
                iso(add_months(sim_start, -RNG.randint(6, 60))),
                1 if not C.INDEPENDENT_FOLLOWUP else 0,
            ))

            for _ in range(C.BORROWERS_PER_OFFICER):
                borrower_id += 1
                occupation, income_band = RNG.choice(OCCUPATIONS)
                is_trader = 1 if occupation == "market trader" else (
                    1 if RNG.random() < C.MARKET_TRADER_SHARE * 0.5 else 0)
                # Enrolment spread across the two years before and during the window,
                # so tenure varies. Victim selection depends on tenure.
                enrolled = add_months(sim_start, -RNG.randint(0, 20))
                borrowers.append((
                    borrower_id, officer_id, branch_id, synthetic_name(),
                    iso(enrolled), occupation, income_band, is_trader,
                ))

    return branches, officers, borrowers


# ----------------------------------------------------------------- lending

def installment_amount(principal, annual_rate, term_months, n_periods, method):
    """Flat interest spreads a fixed charge; declining amortises over the balance.

    Flat is the common microfinance product and the more expensive one: interest
    is charged on the original principal for the whole term, regardless of what
    has been repaid.
    """
    if method == "flat":
        total = principal * (1.0 + annual_rate * term_months / 12.0)
        return total / n_periods
    periodic = annual_rate / (52.0 if n_periods > term_months else 12.0)
    if periodic == 0:
        return principal / n_periods
    return principal * periodic / (1.0 - (1.0 + periodic) ** (-n_periods))


def build_loans(borrowers):
    """One or two loans per borrower inside the observation window."""
    sim_start = date.fromisoformat(C.SIM_START)
    sim_end = add_months(sim_start, C.SIM_MONTHS)

    loans, schedule = [], []
    loan_id = 0
    schedule_id = 0

    for (borrower_id, officer_id, _branch, _name, enrolled, _occ, income, _tr) in borrowers:
        n_loans = 2 if RNG.random() < C.REPEAT_LOAN_PROB else 1
        cursor = max(date.fromisoformat(enrolled), sim_start)

        for _ in range(n_loans):
            if cursor >= sim_end:
                break
            loan_id += 1

            cap = {"low": 6000, "medium": 12000, "high": C.PRINCIPAL_MAX_GHS}[income]
            principal = round(RNG.uniform(C.PRINCIPAL_MIN_GHS, cap), -1)
            term = RNG.choice(C.TERM_MONTHS_CHOICES)
            freq = weighted_choice(C.FREQUENCY_WEIGHTS)
            method = weighted_choice(C.INTEREST_METHOD_WEIGHTS)
            rate = round(RNG.uniform(C.ANNUAL_RATE_MIN, C.ANNUAL_RATE_MAX), 3)

            n_periods = term if freq == "monthly" else int(round(term * 52 / 12.0))
            amount = round(installment_amount(principal, rate, term, n_periods, method), 2)

            disbursed = cursor + timedelta(days=RNG.randint(0, 45))
            if disbursed >= sim_end:
                break

            loans.append([loan_id, borrower_id, officer_id, principal, method, rate,
                          term, freq, iso(disbursed), "active", None])

            for i in range(1, n_periods + 1):
                due = (disbursed + timedelta(days=7 * i) if freq == "weekly"
                       else add_months(disbursed, i))
                schedule_id += 1
                schedule.append((schedule_id, loan_id, i, iso(due), amount))

            cursor = add_months(disbursed, term + RNG.randint(1, 3))

    return loans, schedule


# ----------------------------------------------------------------- honest behaviour

def simulate_truth(loans, schedule, borrower_index):
    """What actually happened at the doorstep, before any fraud.

    This is the noise floor. Late payers, defaulters, early payoffs and traders
    having a bad market week all live here, and detection has to beat this, not
    a clean ledger.
    """
    by_loan = {}
    for row in schedule:
        by_loan.setdefault(row[1], []).append(row)

    truth = {}          # schedule_id -> [paid_amount, paid_date or None]
    loan_status = {}

    for loan in loans:
        loan_id, borrower_id = loan[0], loan[1]
        rows = by_loan.get(loan_id, [])
        if not rows:
            continue

        is_trader = borrower_index[borrower_id]["is_market_trader"]
        will_default = RNG.random() < C.DEFAULT_PROB
        default_at = RNG.randint(2, len(rows)) if will_default else None
        pays_early = (not will_default) and RNG.random() < C.EARLY_PAYOFF_PROB
        payoff_at = RNG.randint(max(2, len(rows) // 3), len(rows)) if pays_early else None

        status = "active"
        for (schedule_id, _lid, inst_no, due_iso, amount) in rows:
            due = date.fromisoformat(due_iso)

            if default_at and inst_no >= default_at:
                truth[schedule_id] = [0.0, None]
                status = "defaulted"
                continue

            if payoff_at and inst_no >= payoff_at:
                # Cleared in a lump on the payoff date: every remaining installment
                # is satisfied at once.
                truth[schedule_id] = [amount, iso(date.fromisoformat(rows[payoff_at - 1][3]))]
                status = "closed"
                continue

            p_late = C.P_LATE * (C.TRADER_LATE_MULTIPLIER if is_trader else 1.0)
            if due.month in C.LEAN_MONTHS:
                p_late *= 1.4
            p_missed = C.P_MISSED
            p_partial = C.P_PARTIAL * (C.TRADER_LATE_MULTIPLIER if is_trader else 1.0)
            r = RNG.random()

            if r < p_missed:
                truth[schedule_id] = [0.0, None]
            elif r < p_missed + p_partial:
                # Came up short. Honest, common, and the reason a short-payment
                # rule cannot simply flag every under-recorded installment.
                part = round(amount * RNG.uniform(C.PARTIAL_PAY_MIN, C.PARTIAL_PAY_MAX), 2)
                truth[schedule_id] = [part, iso(due + timedelta(days=RNG.randint(0, 5)))]
            elif r < p_missed + p_partial + p_late:
                delay = RNG.randint(1, C.LATE_DAYS_MAX)
                truth[schedule_id] = [amount, iso(due + timedelta(days=delay))]
            else:
                jitter = RNG.randint(-2, 1)
                truth[schedule_id] = [amount, iso(due + timedelta(days=max(jitter, -2)))]

        loan_status[loan_id] = status

    return truth, loan_status


# ----------------------------------------------------------------- the fraud

def ramp_factor(period_index):
    """Intensity 0 -> 1 as the scheme finds its confidence.

    A fraud running flat out for 24 months is caught by any average. Real ones
    start cautious. The useful question then becomes "in which month would we
    have caught him", not "did we".
    """
    if period_index < C.FRAUD_START_MONTH:
        return 0.0
    progress = (period_index - C.FRAUD_START_MONTH) / float(C.RAMP_MONTHS)
    return min(1.0, max(0.0, progress))


def inject_fraud(loans, schedule, truth, borrowers, officers):
    """Skim MANY borrowers LIGHTLY: invisible per borrower, visible in aggregate.

    That is the shape of the real case. Each victim looks like an ordinary late
    payer; the signal only exists once you aggregate to the officer.
    """
    sim_start = date.fromisoformat(C.SIM_START)
    officer_ids = [o[0] for o in officers]
    fraudulent = RNG.sample(officer_ids, C.N_FRAUDULENT_OFFICERS)

    # Victims: long-tenured borrowers with clean records, who trust the officer
    # and do not check their statements.
    victims = set()
    for officer_id in fraudulent:
        book = [b for b in borrowers if b[1] == officer_id
                and months_between(date.fromisoformat(b[4]), sim_start) >= 0
                and months_between(date.fromisoformat(b[4]), sim_start) >= C.VICTIM_MIN_TENURE_MONTHS - 4]
        book.sort(key=lambda b: b[4])                      # longest tenure first
        take = int(len(book) * C.VICTIM_SHARE)
        victims.update(b[0] for b in book[:take])

    loan_officer = {l[0]: l[2] for l in loans}
    loan_borrower = {l[0]: l[1] for l in loans}

    skims = {}          # schedule_id -> skimmed amount
    for (schedule_id, loan_id, _inst, due_iso, _amount) in schedule:
        officer_id = loan_officer.get(loan_id)
        if officer_id not in fraudulent:
            continue
        if loan_borrower.get(loan_id) not in victims:
            continue

        paid, paid_date = truth.get(schedule_id, [0.0, None])
        if paid <= 0:
            continue                                       # nothing to steal

        period = months_between(sim_start, date.fromisoformat(due_iso))
        intensity = ramp_factor(period)
        if intensity <= 0:
            continue
        if RNG.random() >= C.SKIM_PROBABILITY * intensity:
            continue

        if RNG.random() < C.FULL_SKIM_RATIO:
            skims[schedule_id] = paid                      # recorded as nothing
        else:
            share = RNG.uniform(C.PARTIAL_SKIM_MIN, C.PARTIAL_SKIM_MAX)
            skims[schedule_id] = round(paid * share, 2)

    return fraudulent, victims, skims


def build_recorded(schedule, truth, skims, loans):
    """The books. Recorded = actually paid, minus whatever was skimmed.

    Note there is no separate "inflated balance" table. Outstanding balance is
    derived from schedule minus recorded, so withholding a payment inflates the
    balance automatically, exactly as it did in the real ledger.
    """
    loan_officer = {l[0]: l[2] for l in loans}
    recorded = []
    repayment_id = 0

    for (schedule_id, loan_id, _inst, due_iso, _amount) in schedule:
        paid, paid_date = truth.get(schedule_id, [0.0, None])
        if paid <= 0:
            continue

        amount = round(paid - skims.get(schedule_id, 0.0), 2)
        if amount <= 0.005:
            continue                                       # full skim: no entry at all

        repayment_id += 1
        channel = weighted_choice({
            "cash_to_officer": 0.78, "branch_counter": 0.15, "mobile_money": 0.07})
        recorded.append((repayment_id, loan_id, schedule_id, loan_officer[loan_id],
                         paid_date or due_iso, amount, channel))

    return recorded


# ----------------------------------------------------------------- persistence

def write_db(branches, officers, borrowers, loans, schedule, recorded,
             truth, skims, fraudulent, loan_status):
    out = os.path.join(ROOT, C.DB_PATH)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)

    con = sqlite3.connect(out)
    with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as fh:
        con.executescript(fh.read())

    for loan in loans:
        loan[9] = loan_status.get(loan[0], "active")

    con.executemany("INSERT INTO branches VALUES (?,?,?,?)", branches)
    con.executemany("INSERT INTO credit_officers VALUES (?,?,?,?,?)", officers)
    con.executemany("INSERT INTO borrowers VALUES (?,?,?,?,?,?,?,?)", borrowers)
    con.executemany("INSERT INTO loans VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(l) for l in loans])
    con.executemany("INSERT INTO repayment_schedule VALUES (?,?,?,?,?)", schedule)
    con.executemany("INSERT INTO repayments_recorded VALUES (?,?,?,?,?,?,?)", recorded)

    sim_start = date.fromisoformat(C.SIM_START)
    con.executemany(
        "INSERT INTO ground_truth_officers VALUES (?,?,?,?,?,?)",
        [(o[0], 1 if o[0] in fraudulent else 0,
          "unrecorded_repayment_skimming" if o[0] in fraudulent else None,
          iso(add_months(sim_start, C.FRAUD_START_MONTH)) if o[0] in fraudulent else None,
          iso(add_months(sim_start, C.SIM_MONTHS)) if o[0] in fraudulent else None,
          C.SKIM_PROBABILITY if o[0] in fraudulent else None) for o in officers])

    gt_rows = []
    for (schedule_id, loan_id, _i, _due, _amt) in schedule:
        paid, paid_date = truth.get(schedule_id, [0.0, None])
        skimmed = skims.get(schedule_id, 0.0)
        gt_rows.append((schedule_id, loan_id, paid, paid_date,
                        1 if skimmed > 0 else 0, skimmed))
    con.executemany("INSERT INTO ground_truth_repayments VALUES (?,?,?,?,?,?)", gt_rows)

    con.commit()
    return con, out


def main():
    print("seed:", C.SEED)
    branches, officers, borrowers = build_structure()
    borrower_index = {b[0]: {"is_market_trader": b[7], "officer_id": b[1]} for b in borrowers}

    loans, schedule = build_loans(borrowers)
    truth, loan_status = simulate_truth(loans, schedule, borrower_index)
    fraudulent, victims, skims = inject_fraud(loans, schedule, truth, borrowers, officers)
    recorded = build_recorded(schedule, truth, skims, loans)
    loan_borrower_of = {row[0]: row[1] for row in schedule}
    loan_borrower = {l[0]: l[1] for l in loans}

    con, path = write_db(branches, officers, borrowers, loans, schedule, recorded,
                         truth, skims, fraudulent, loan_status)

    stolen = sum(skims.values())
    print("branches            %6d" % len(branches))
    print("credit officers     %6d" % len(officers))
    print("borrowers           %6d" % len(borrowers))
    print("loans               %6d" % len(loans))
    print("scheduled payments  %6d" % len(schedule))
    print("recorded payments   %6d" % len(recorded))
    print("fraudulent officers %6s" % sorted(fraudulent))
    skimmed_borrowers = len({loan_borrower[l]
                             for sid, l in ((k, loan_borrower_of[k]) for k in skims)})
    print("victims selected    %6d borrowers" % len(victims))
    # Selected and skimmed are different counts: a selected borrower with no
    # eligible payment during the ramp is never actually touched.
    print("victims skimmed     %6d borrowers" % skimmed_borrowers)
    print("skimmed installments%6d" % len(skims))
    print("amount skimmed      GHS {:,.2f}".format(stolen))
    print("written to", path)
    con.close()


if __name__ == "__main__":
    main()
