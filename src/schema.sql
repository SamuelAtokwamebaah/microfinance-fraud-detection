-- Microfinance portfolio schema.
--
-- The whole project turns on one separation:
--
--   repayment_schedule    what the borrower was CONTRACTED to pay
--   repayments_recorded   what the BOOKS say arrived
--   ground_truth_*        what ACTUALLY happened at the doorstep
--
-- Detection code may read the first two. It must never read the third.
-- In real life nobody can see the third either, until somebody asks a borrower.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS ground_truth_repayments;
DROP TABLE IF EXISTS ground_truth_officers;
DROP TABLE IF EXISTS repayments_recorded;
DROP TABLE IF EXISTS repayment_schedule;
DROP TABLE IF EXISTS loans;
DROP TABLE IF EXISTS borrowers;
DROP TABLE IF EXISTS credit_officers;
DROP TABLE IF EXISTS branches;

-- ---------------------------------------------------------------- structure

CREATE TABLE branches (
    branch_id     INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    region        TEXT NOT NULL,
    opened_date   TEXT NOT NULL
);

CREATE TABLE credit_officers (
    officer_id    INTEGER PRIMARY KEY,
    branch_id     INTEGER NOT NULL REFERENCES branches(branch_id),
    name          TEXT NOT NULL,          -- synthetic
    hired_date    TEXT NOT NULL,
    -- TRUE when this officer also owns delinquency follow-up on his own book.
    -- That is the control failure the real case turned on: no independent party
    -- ever spoke to a borrower the officer had marked delinquent.
    owns_followup INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE borrowers (
    borrower_id      INTEGER PRIMARY KEY,
    officer_id       INTEGER NOT NULL REFERENCES credit_officers(officer_id),
    branch_id        INTEGER NOT NULL REFERENCES branches(branch_id),
    name             TEXT NOT NULL,       -- synthetic
    enrolled_date    TEXT NOT NULL,
    occupation       TEXT NOT NULL,
    income_band      TEXT NOT NULL,
    is_market_trader INTEGER NOT NULL     -- weekly cash cycle, lumpier repayment
);

-- ---------------------------------------------------------------- lending

CREATE TABLE loans (
    loan_id               INTEGER PRIMARY KEY,
    borrower_id           INTEGER NOT NULL REFERENCES borrowers(borrower_id),
    officer_id            INTEGER NOT NULL REFERENCES credit_officers(officer_id),
    principal_ghs         REAL NOT NULL,
    interest_method       TEXT NOT NULL,  -- 'flat' | 'declining'
    annual_rate           REAL NOT NULL,
    term_months           INTEGER NOT NULL,
    frequency             TEXT NOT NULL,  -- 'weekly' | 'monthly'
    disbursed_date        TEXT NOT NULL,
    status                TEXT NOT NULL,  -- 'active' | 'closed' | 'defaulted' | 'restructured'
    restructured_from_loan_id INTEGER REFERENCES loans(loan_id)
);

CREATE TABLE repayment_schedule (
    schedule_id    INTEGER PRIMARY KEY,
    loan_id        INTEGER NOT NULL REFERENCES loans(loan_id),
    installment_no INTEGER NOT NULL,
    due_date       TEXT NOT NULL,
    amount_due_ghs REAL NOT NULL
);

CREATE TABLE repayments_recorded (
    repayment_id        INTEGER PRIMARY KEY,
    loan_id             INTEGER NOT NULL REFERENCES loans(loan_id),
    schedule_id         INTEGER NOT NULL REFERENCES repayment_schedule(schedule_id),
    officer_id          INTEGER NOT NULL REFERENCES credit_officers(officer_id),
    recorded_date       TEXT NOT NULL,
    amount_recorded_ghs REAL NOT NULL,
    channel             TEXT NOT NULL   -- 'cash_to_officer' | 'branch_counter' | 'mobile_money'
);

-- ---------------------------------------------------------------- ground truth
-- EVALUATION ONLY. Detection must never join to these tables.

CREATE TABLE ground_truth_officers (
    officer_id       INTEGER PRIMARY KEY REFERENCES credit_officers(officer_id),
    is_fraudulent    INTEGER NOT NULL,
    scheme_type      TEXT,
    active_from      TEXT,
    active_to        TEXT,
    peak_intensity   REAL
);

CREATE TABLE ground_truth_repayments (
    schedule_id        INTEGER PRIMARY KEY REFERENCES repayment_schedule(schedule_id),
    loan_id            INTEGER NOT NULL REFERENCES loans(loan_id),
    actually_paid_ghs  REAL NOT NULL,
    actually_paid_date TEXT,
    was_skimmed        INTEGER NOT NULL DEFAULT 0,
    skimmed_amount_ghs REAL NOT NULL DEFAULT 0.0
);

-- ---------------------------------------------------------------- indexes
-- Index what you filter and join on. Detection aggregates by officer and by
-- period, and joins repayments back to their schedule, so those are the columns
-- that earn an index.

CREATE INDEX idx_borrowers_officer   ON borrowers(officer_id);
CREATE INDEX idx_loans_officer       ON loans(officer_id);
CREATE INDEX idx_loans_borrower      ON loans(borrower_id);
CREATE INDEX idx_sched_loan          ON repayment_schedule(loan_id);
CREATE INDEX idx_sched_due           ON repayment_schedule(due_date);
CREATE INDEX idx_rec_loan            ON repayments_recorded(loan_id);
CREATE INDEX idx_rec_schedule        ON repayments_recorded(schedule_id);
CREATE INDEX idx_rec_officer_date    ON repayments_recorded(officer_id, recorded_date);
CREATE INDEX idx_gt_rep_loan         ON ground_truth_repayments(loan_id);
