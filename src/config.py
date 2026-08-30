"""Every knob for the simulation, in one place.

Two reasons this is a module rather than constants scattered through the
generator. First, a reviewer can read this file alone and know exactly what
world was simulated. Second, changing SEED changes the entire portfolio and the
fraud inside it, so reproducibility is a one-line guarantee.
"""

# ---------------------------------------------------------------- reproducibility
# Fixed for the published version. Anyone who clones this repo and runs it gets
# the identical portfolio, the identical fraud, and the identical results.
SEED = 20260830

# ---------------------------------------------------------------- portfolio shape
N_BRANCHES = 5
OFFICERS_PER_BRANCH = 4
BORROWERS_PER_OFFICER = 150          # 5 x 4 x 150 = 3,000 borrowers

SIM_START = "2024-01-01"             # 24-month observation window
SIM_MONTHS = 24

# ---------------------------------------------------------------- loan products
PRINCIPAL_MIN_GHS = 500
PRINCIPAL_MAX_GHS = 20000
TERM_MONTHS_CHOICES = [3, 6, 9, 12, 18, 24]
FREQUENCY_WEIGHTS = {"weekly": 0.65, "monthly": 0.35}   # weekly dominates in microfinance
INTEREST_METHOD_WEIGHTS = {"flat": 0.7, "declining": 0.3}
ANNUAL_RATE_MIN = 0.24
ANNUAL_RATE_MAX = 0.48

# Some borrowers take a second loan after clearing the first.
REPEAT_LOAN_PROB = 0.35

# ---------------------------------------------------------------- honest behaviour
# The noise floor. Detection has to beat THIS, not a clean ledger.
P_ON_TIME = 0.86
P_LATE = 0.11                        # paid, but after the due date
P_MISSED = 0.03                      # genuinely not paid
LATE_DAYS_MAX = 21
EARLY_PAYOFF_PROB = 0.06             # borrower clears the loan ahead of term
DEFAULT_PROB = 0.05                  # borrower stops paying entirely
RESTRUCTURE_PROB = 0.04

# Market traders run weekly cash cycles and repay unevenly. A detector that
# cannot tell "trader in a bad market week" from "officer skimming" will drown
# in false positives, so the noise has to be in the data from the start.
MARKET_TRADER_SHARE = 0.45
TRADER_LATE_MULTIPLIER = 1.8
LEAN_MONTHS = [1, 2, 8]              # Jan, Feb, Aug: post-festive and pre-harvest

# ---------------------------------------------------------------- the fraud
# Calibrated to Samuel's real case: MANY borrowers skimmed LIGHTLY, which is
# invisible per borrower and only shows up when you aggregate to the officer.
N_FRAUDULENT_OFFICERS = 2
VICTIM_SHARE = 0.55                  # share of the officer's book that is targeted
SKIM_PROBABILITY = 0.30              # chance a given victim installment is skimmed
FULL_SKIM_RATIO = 0.25               # of skims, the share recorded as nothing at all
PARTIAL_SKIM_MIN = 0.30              # partial skims withhold 30-60% of the payment
PARTIAL_SKIM_MAX = 0.60

# Victim selection: long-tenured borrowers with clean records. They trust the
# officer and do not check their statements.
VICTIM_MIN_TENURE_MONTHS = 4

# The ramp. A fraud running at constant intensity for 24 months is caught by any
# average. Real schemes start cautious and grow bold, so the honest question
# becomes "in which month would we have caught him?" rather than "did we?".
FRAUD_START_MONTH = 4                # months into the window before it begins
RAMP_MONTHS = 10                     # months to reach full intensity

# The control failure: the officer owned all delinquency follow-up on his own
# book, so no independent party ever spoke to a "delinquent" borrower.
INDEPENDENT_FOLLOWUP = False

# ---------------------------------------------------------------- output
DB_PATH = "data/generated/portfolio.db"
