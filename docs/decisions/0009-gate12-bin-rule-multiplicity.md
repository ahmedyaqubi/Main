# ADR-0009 — Gate 12 bin rule: adjust the per-bin level for the number of bins

- Status: **ACCEPTED** (owner, 2026-10-07, option A; drafted the same day at the owner's request)
- Date: 2026-10-07
- Milestone: M13 (criterion 4); applies to the gate-12 verdict at M19
- Amends: PHASE_1_SPEC §11 gate 12 (the bin condition only; the ECE and slope conditions are unchanged)

## Context
Gate 12 requires: held-out ECE ≤ 0.03 (10 equal-count bins); calibration slope in [0.8, 1.2];
and "every bin with n ≥ 200 has its observed rate inside the 95% Wilson CI of its mean predicted
value". The last condition tests 10 bins, each at 95%, and requires all of them to pass. Even for a
**perfectly calibrated** model, the chance that at least one bin falls outside its own 95% interval
is about 1 − 0.95^10 ≈ 40%.

Simulation (perfectly calibrated synthetic data, p ~ U(0.1, 0.9), y ~ Bernoulli(p), 400 seeds;
`tests/test_calibration.py::test_gate12_bin_rule_false_fail_rate_is_documented` checks the same
property with 100 seeds):

| rows | P(≥ 1 bin fails), 95% per bin (current) | P(≥ 2 bins fail), 95% | P(≥ 1 bin fails), 99.5% per bin |
|---|---|---|---|
| 4,000 (≈ one test block) | 0.40 | 0.09 | 0.045 |
| 27,000 (≈ pooled test blocks) | 0.37 | 0.075 | 0.043 |

So the current rule rejects a correct model 37–40% of the time. That is not the intended 5%.

## Disclosure
This ADR is drafted **after** the M13 results were seen (runs `calibration-799352d4eabb`,
`calibration-06a056389e36`). Under the current rule all 20 model × target combinations would fail
gate 12. Under option A below, 1 of 20 would pass: Model 2 B_up 0.25% (ECE 0.012, slope 0.999;
5 bins fail at 95%, 0 at 99.5%). That is a move-size target, not a decision (C) target. Every C target
would still fail (slope and/or bins). The proposal is motivated by the false-fail rate above, which is
a property of the rule, not of these results.

## Options
- **A (recommended): Bonferroni per bin.** Each checked bin must have its observed rate inside the
  (1 − 0.05/k) Wilson CI of its mean predicted value, where k = number of bins with n ≥ 200 (99.5% for
  k = 10). The family-wise false-fail rate is ≈ 5% (simulated 4.3–4.5%). Simple, conservative, and keeps
  the "every bin" wording.
- **B: allow a binomial number of failures.** Keep 95% per bin but pass if the number of failing bins is
  ≤ the 95th percentile of Binomial(k, 0.05) (= 1 for k = 10). Family-wise false-fail ≈ 7.5–9%, and it
  tolerates one badly miscalibrated bin, which is worse for a trading decision that may sit in that bin.
- **C: keep the rule as written.** It is then a ~40% coin flip against a correct model, which makes
  gate 12 mostly a test of luck when the other two conditions pass.

## Decision
Option A. `calibration.gate12.wilson_level` stays the family-wise level (0.95); the per-bin level becomes
`1 − (1 − wilson_level) / k`. Reports show the per-bin level used and keep the unadjusted 95% count for
reference.

## Consequences
- `calibration.metrics.gate12` / `reliability` take the adjusted level; tests add the family-wise
  false-fail check (≈ 5% ± simulation error) and keep the 40% test as documentation of the old rule.
- The M13 report is regenerated with both counts. Nothing is re-fit and no model is chosen from the
  change; the gate-12 verdict is still only formal at M19.
- Changing the rule again needs a new ADR.
