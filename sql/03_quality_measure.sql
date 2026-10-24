/* 03_quality_measure.sql: PCR-style (HEDIS Plan All-Cause Readmissions, adapted) views for Power BI.
   Observed rate needs only mart.index_stay. Risk-adjusted O/E needs mart.index_stay_score from Python.
   Adapted, not certified: no planned-readmission exclusion, no HEDIS value sets, synthetic providers. */

CREATE OR ALTER VIEW mart.v_monthly_readmission AS
SELECT i.split,
       DATEFROMPARTS(YEAR(i.discharge_dt), MONTH(i.discharge_dt), 1) AS discharge_month,
       COUNT(*)                                        AS index_stays,
       SUM(CAST(i.readmit_30 AS INT))                  AS readmits,
       AVG(CAST(i.readmit_30 AS FLOAT))                AS observed_rate,
       SUM(s.p_glm)                                    AS expected_readmits
FROM mart.index_stay i
LEFT JOIN mart.index_stay_score s ON s.desynpuf_id = i.desynpuf_id AND s.stay_seq = i.stay_seq
GROUP BY i.split, DATEFROMPARTS(YEAR(i.discharge_dt), MONTH(i.discharge_dt), 1);
GO

-- O/E by discharging hospital, test year only, hospitals with 25+ index stays.
-- 95% CI on O uses Byar's approximation to the exact Poisson interval (Python uses the exact one).
CREATE OR ALTER VIEW mart.v_provider_oe AS
WITH t AS (
    SELECT i.prvdr_num,
           COUNT(*) AS index_stays,
           CAST(SUM(CAST(i.readmit_30 AS INT)) AS FLOAT) AS o,
           SUM(s.p_glm) AS e
    FROM mart.index_stay i
    JOIN mart.index_stay_score s ON s.desynpuf_id = i.desynpuf_id AND s.stay_seq = i.stay_seq
    WHERE i.split = 'test'
    GROUP BY i.prvdr_num
    HAVING COUNT(*) >= 25
), ci AS (
    SELECT *, o / e AS oe_ratio,
           CASE WHEN o = 0 THEN 0
                ELSE o * POWER(1 - 1 / (9 * o) - 1.96 / (3 * SQRT(o)), 3) END / e AS oe_lo95,
           (o + 1) * POWER(1 - 1 / (9 * (o + 1)) + 1.96 / (3 * SQRT(o + 1)), 3) / e AS oe_hi95
    FROM t
)
SELECT *, CASE WHEN oe_lo95 > 1 THEN 'worse than expected'
               WHEN oe_hi95 < 1 THEN 'better than expected'
               ELSE 'as expected' END AS flag
FROM ci;
GO
