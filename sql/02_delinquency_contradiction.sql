-- Tier 1, rule 2: borrowers whose recorded delinquency contradicts their own history.
--
-- The intuition comes straight from the real case. A borrower who paid thirty
-- installments on time and then goes patchy is a different animal from one who
-- was always erratic. The first is a question; the second is just a bad payer.
--
-- Crucially this compares each borrower against HIMSELF, so it is immune to the
-- problem that sank rule 1 for officer 14: an officer with many market traders
-- is not penalised, because traders are compared against their own baseline.

WITH paid AS (
    SELECT schedule_id, SUM(amount_recorded_ghs) AS recorded_ghs
    FROM repayments_recorded
    GROUP BY schedule_id
),

installments AS (
    -- ROW_NUMBER numbers the installments inside each loan, oldest first, so
    -- "early in the relationship" and "later" are well defined even though
    -- loans start on different dates and run for different terms.
    SELECT l.borrower_id,
           l.officer_id,
           s.loan_id,
           s.due_date,
           s.amount_due_ghs,
           COALESCE(p.recorded_ghs, 0)                AS recorded_ghs,
           ROW_NUMBER() OVER (PARTITION BY s.loan_id
                              ORDER BY s.due_date)    AS installment_seq
    FROM repayment_schedule s
    JOIN loans     l ON l.loan_id = s.loan_id
    LEFT JOIN paid p ON p.schedule_id = s.schedule_id
    WHERE s.due_date <= '2025-12-31'
),

phased AS (
    SELECT borrower_id,
           officer_id,
           CASE WHEN installment_seq <= 8 THEN 'early' ELSE 'later' END AS phase,
           -- "Settled" allows a 5% tolerance for rounding on the last installment.
           CASE WHEN recorded_ghs >= 0.95 * amount_due_ghs THEN 1.0 ELSE 0.0 END AS settled
    FROM installments
),

borrower_profile AS (
    SELECT borrower_id,
           officer_id,
           AVG(CASE WHEN phase = 'early' THEN settled END)      AS early_rate,
           AVG(CASE WHEN phase = 'later' THEN settled END)      AS later_rate,
           SUM(CASE WHEN phase = 'later' THEN 1 ELSE 0 END)     AS later_n
    FROM phased
    GROUP BY borrower_id, officer_id
),

contradictions AS (
    SELECT *,
           CASE WHEN early_rate  >= 0.90        -- was a clean payer
                 AND later_n     >= 8           -- enough later history to judge
                 AND later_rate IS NOT NULL
                 AND (early_rate - later_rate) >= 0.25   -- then dropped sharply
                THEN 1 ELSE 0 END AS contradicts
    FROM borrower_profile
)

SELECT officer_id,
       COUNT(*)                                                  AS borrowers_assessed,
       SUM(contradicts)                                          AS contradicting_borrowers,
       ROUND(100.0 * SUM(contradicts) / COUNT(*), 2)             AS pct_of_book,
       ROUND(AVG(CASE WHEN contradicts = 1
                      THEN early_rate - later_rate END) * 100, 1) AS mean_drop_pp
FROM contradictions
GROUP BY officer_id
ORDER BY pct_of_book DESC;
