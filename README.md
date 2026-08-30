# microfinance-fraud-detection

Catching a loan-repayment skimming scheme in a synthetic microfinance portfolio, using SQL rules and Python anomaly detection.

> 🚧 **Private — in development. Will be published at v1.**

## What this is

In a Ghanaian microfinance receivership I found GHS 58,600 that a credit officer had
taken from 27 borrowers, by noticing that one officer's collection figures were out of
line with the rest of the portfolio. I found it by hand, reading reconciliations.

This project rebuilds that detection computationally, on a synthetic portfolio of the
same shape, and asks the question the manual method could not: how much would we catch
at scale, and how much would we miss?

## Status

| Phase | State |
|---|---|
| 1. Synthetic data generator | **done** |
| 2a. Detection, Tier 1 (SQL rules) | **done** — 4 rules, evaluated |
| 2b. Detection, Tier 2 (statistical) | next |
| 3. Evidence dashboard | not started |
| 4. Repo polish | not started |

## Note on the data

**Every record in this repository is synthetic.** No real borrower, credit officer,
branch or institution appears here, and no data from any real engagement has been used.
The portfolio is generated from a fixed random seed so that anyone can reproduce it
exactly.
