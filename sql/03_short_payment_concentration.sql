-- Tier 1, rule 3: balance movements inconsistent with the repayment schedule.
--
-- A partial skim leaves a specific fingerprint: an installment recorded for LESS
-- than the amount due, while the loan carries on. Not a missed payment, not a
-- late one. Money arrived, and less of it than the contract called for.
--
-- The catch, and the reason this rule is not free: honest borrowers come up
-- short too. Roughly one installment in twenty in this portfolio is an honest
-- part-payment. So the question is never "did short payments occur" but "does
-- THIS officer's book carry more of them than his peers', and are they
-- concentrated in borrowers who used to pay in full?".

WITH paid AS (
    SELECT schedule_id, SUM(amount_recorded_ghs) AS recorded_ghs
    FROM repayments_recorded
    GROUP BY schedule_id
),

matched AS (
    SELECT l.officer_id,
           o.branch_id,
           l.borrower_id,
           s.schedule_id,
           s.amount_due_ghs,
           p.recorded_ghs,
           p.recorded_ghs / NULLIF(s.amount_due_ghs, 0) AS settle_ratio
    FROM repayment_schedule s
    JOIN loans           l ON l.loan_id    = s.loan_id
    JOIN credit_officers o ON o.officer_id = l.officer_id
    JOIN paid            p ON p.schedule_id = s.schedule_id   -- INNER: money did arrive
    WHERE s.due_date <= '2025-12-31'
      AND s.amount_due_ghs > 0
),

classified AS (
    SELECT *,
           CASE WHEN settle_ratio < 0.95 THEN 1 ELSE 0 END AS is_short,
           -- The middle band is where a partial skim lands. An honest shortfall
           -- is more often a near miss or a token payment; withholding 30-60%
           -- of a collection puts the recorded figure squarely in the middle.
           CASE WHEN settle_ratio BETWEEN 0.35 AND 0.75 THEN 1 ELSE 0 END AS is_mid_band,
           CASE WHEN settle_ratio < 0.95
                THEN amount_due_ghs - recorded_ghs ELSE 0 END AS shortfall_ghs
    FROM matched
),

per_officer AS (
    SELECT officer_id,
           branch_id,
           COUNT(*)                                       AS recorded_installments,
           SUM(is_short)                                  AS short_installments,
           SUM(is_mid_band)                               AS mid_band_installments,
           ROUND(100.0 * SUM(is_short) / COUNT(*), 2)     AS pct_short,
           ROUND(100.0 * SUM(is_mid_band) / COUNT(*), 2)  AS pct_mid_band,
           ROUND(SUM(shortfall_ghs), 2)                   AS total_shortfall_ghs,
           COUNT(DISTINCT CASE WHEN is_short = 1 THEN borrower_id END)
                                                          AS borrowers_affected
    FROM classified
    GROUP BY officer_id, branch_id
)

-- Compare each officer's short-payment rate to his branch, excluding himself,
-- for the same reason as rule 1: an officer must not set his own benchmark.
SELECT officer_id,
       branch_id,
       recorded_installments,
       short_installments,
       pct_short,
       pct_mid_band,
       ROUND(100.0 * (SUM(short_installments) OVER (PARTITION BY branch_id) - short_installments)
             / NULLIF(SUM(recorded_installments) OVER (PARTITION BY branch_id)
                      - recorded_installments, 0), 2)      AS peer_pct_short,
       ROUND(pct_short
             - 100.0 * (SUM(short_installments) OVER (PARTITION BY branch_id) - short_installments)
               / NULLIF(SUM(recorded_installments) OVER (PARTITION BY branch_id)
                        - recorded_installments, 0), 2)    AS excess_pp,
       borrowers_affected,
       total_shortfall_ghs
FROM per_officer
ORDER BY excess_pp DESC;
