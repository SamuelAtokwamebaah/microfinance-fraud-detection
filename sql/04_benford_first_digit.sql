-- Tier 1, rule 4: Benford first-digit test on recorded repayment amounts.
--
-- Benford's law says that in many naturally occurring sets of numbers, the
-- leading digit is 1 about 30% of the time and 9 only about 4.6%. Fabricated
-- figures often come out too uniform, so auditors use the test as a smell check.
--
-- It is included here because it is the standard tool a reviewer expects to see,
-- and because this portfolio is a good example of WHERE IT DOES NOT APPLY.
-- Benford needs values spanning several orders of magnitude and arising from a
-- multiplicative process. Repayment installments are neither: they are a
-- formula (principal, rate, term) repeated identically week after week, so the
-- same leading digit recurs dozens of times for a single loan. The digit
-- distribution here describes the loan book, not the honesty of the officer.
--
-- The evaluation script reports the result rather than hiding it. Knowing when
-- a well-known technique does not fit is worth more than applying it anyway.

WITH first_digits AS (
    SELECT r.officer_id,
           CAST(substr(
               -- strip to the first non-zero digit of the integer part
               replace(printf('%.2f', r.amount_recorded_ghs), '.', ''),
               1, 1) AS INTEGER) AS lead_digit
    FROM repayments_recorded r
    WHERE r.amount_recorded_ghs >= 1.0
)

SELECT officer_id,
       COUNT(*)                                                       AS n,
       SUM(CASE WHEN lead_digit = 1 THEN 1 ELSE 0 END)                AS d1,
       SUM(CASE WHEN lead_digit = 2 THEN 1 ELSE 0 END)                AS d2,
       SUM(CASE WHEN lead_digit = 3 THEN 1 ELSE 0 END)                AS d3,
       SUM(CASE WHEN lead_digit = 4 THEN 1 ELSE 0 END)                AS d4,
       SUM(CASE WHEN lead_digit = 5 THEN 1 ELSE 0 END)                AS d5,
       SUM(CASE WHEN lead_digit = 6 THEN 1 ELSE 0 END)                AS d6,
       SUM(CASE WHEN lead_digit = 7 THEN 1 ELSE 0 END)                AS d7,
       SUM(CASE WHEN lead_digit = 8 THEN 1 ELSE 0 END)                AS d8,
       SUM(CASE WHEN lead_digit = 9 THEN 1 ELSE 0 END)                AS d9
FROM first_digits
WHERE lead_digit BETWEEN 1 AND 9
GROUP BY officer_id
ORDER BY officer_id;
