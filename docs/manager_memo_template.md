# Memo: 30-day readmissions, [period]

**To:** [Director, Care Management]  **From:** Tristan Kennedy  **Date:** [date]
**Data:** CMS DE-SynPUF Sample 1 (synthetic Medicare claims; method demonstration, not real patients)

## Bottom line
[One sentence: the decision and the recommendation. Example shape: "Calling the top [X]% of discharges by predicted risk would reach [Y]% of 30-day readmissions; recalibrate the model before using its counts for staffing."]

## What we found
1. **Rate:** [N] index stays in [test period]; [r]% returned within 30 days (expected by the model: [e]%).
2. **Targeting:** the top risk decile held [c]% of readmissions, against 10% at random.
3. **Hospitals:** [k] of [m] hospitals with 25+ stays were above expected with 95% confidence. [Name the flag rule in one line.]
4. **Model choice:** gradient boosting [did / did not] beat the logistic model (difference in AUC [d], 95% CI [lo, hi]). We use the [simpler] model.

## How much to trust it
- Tested on a later year than it was trained on (trained 2009, tested 2010).
- Calibration: [over / under]-predicts by [x] points on average; [recalibration plan].
- Not included: planned readmissions, deaths after discharge as a competing outcome, [other].

## Recommended next steps
1. [Action, owner, date]
2. [Action, owner, date]

## Appendix (one chart)
[Reliability diagram or decile capture chart from outputs/]
