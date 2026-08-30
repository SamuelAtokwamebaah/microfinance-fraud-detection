-- Tier 1, rule 1: officer collection rate against BRANCH PEERS, month by month.
--
-- The question an auditor actually asks is not "who collects least?" but
-- "who collects less than the colleagues working the same market in the same
-- month?". Comparing to branch peers cancels out two things that would
-- otherwise generate false positives:
--
--   branch effects  -- one branch may simply serve a poorer catchment
--   seasonality     -- January is lean for everyone; a portfolio-wide average
--                      punishes whoever happens to hold the most January paper
--
-- This query reads only the schedule and the recorded book. It never touches
-- the ground-truth tables.

WITH paid AS (
    -- Collapse the repayment ledger to one row per scheduled installment.
    -- Done once, up front, so the joins below stay cheap.
    SELECT schedule_id,
           SUM(amount_recorded_ghs) AS recorded_ghs
    FROM repayments_recorded
    GROUP BY schedule_id
),

officer_month AS (
    -- What each officer was owed, and what the book says arrived, per month.
    -- LEFT JOIN is essential: an installment with no matching repayment row is
    -- exactly the thing we are hunting, and an INNER JOIN would silently drop it.
    SELECT l.officer_id,
           o.branch_id,
           substr(s.due_date, 1, 7)                 AS period,       -- 'YYYY-MM'
           SUM(s.amount_due_ghs)                    AS due_ghs,
           SUM(COALESCE(p.recorded_ghs, 0))         AS recorded_ghs
    FROM repayment_schedule s
    JOIN loans           l ON l.loan_id    = s.loan_id
    JOIN credit_officers o ON o.officer_id = l.officer_id
    LEFT JOIN paid       p ON p.schedule_id = s.schedule_id
    WHERE s.due_date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY l.officer_id, o.branch_id, period
),

with_peers AS (
    -- The window function does the work. For each row, sum the branch's totals
    -- for that month, then SUBTRACT this officer's own contribution, so an
    -- officer is never compared against himself. Without that subtraction a
    -- large officer would drag his own benchmark down and hide inside it.
    SELECT om.*,
           100.0 * om.recorded_ghs / NULLIF(om.due_ghs, 0) AS officer_rate,
           100.0
             * (SUM(om.recorded_ghs) OVER (PARTITION BY om.branch_id, om.period)
                - om.recorded_ghs)
             / NULLIF(SUM(om.due_ghs) OVER (PARTITION BY om.branch_id, om.period)
                      - om.due_ghs, 0)              AS peer_rate
    FROM officer_month om
),

gaps AS (
    SELECT officer_id,
           branch_id,
           period,
           due_ghs,
           officer_rate,
           peer_rate,
           officer_rate - peer_rate                 AS gap_pp   -- percentage points
    FROM with_peers
    WHERE due_ghs > 0
)

-- One row per officer: how persistently did he sit below his own branch?
-- Persistence matters more than depth. Any officer can have one bad month;
-- an officer who is below his peers in fourteen separate months is a pattern.
SELECT officer_id,
       branch_id,
       COUNT(*)                                              AS months_observed,
       SUM(CASE WHEN gap_pp < -3.0 THEN 1 ELSE 0 END)        AS months_below_peers,
       ROUND(AVG(gap_pp), 2)                                 AS mean_gap_pp,
       ROUND(MIN(gap_pp), 2)                                 AS worst_gap_pp,
       ROUND(SUM(due_ghs * (peer_rate - officer_rate)) / 100.0, 2)
                                                             AS implied_shortfall_ghs
FROM gaps
GROUP BY officer_id, branch_id
ORDER BY mean_gap_pp ASC;
