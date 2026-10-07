# ADR-0007 — D-label stop and target mirror the option bracket

- Status: **ACCEPTED** (owner, 2026-10-07, option "a")
- Date: 2026-10-07
- Milestone: M6 (criterion 4)
- Amends: PHASE_1_SPEC §3 (D_call / D_put defaults)

## Context
Spec §3 set D's stop at 0.15% and its target at the primary magnitude threshold (0.25%), on
the stated rationale that this "roughly matches the −20%/+30% option bracket for an ATM 1DTE
contract (to be checked empirically in M6)". M6 checked it on **pre-holdout** data only
(sessions through 2026-04-02; the final holdout stays locked, spec §8 / rule 5;
`reports/labels/d_stop_check.md`). For C trades that hit the option stop or target on the bid,
the median QQQ move from P_T to the exit time was:

| Option event | Calls | Puts |
|---|---|---|
| −20% stop | −0.202% (n = 22,918) | +0.181% (n = 24,672) |
| +30% target | +0.307% (n = 12,108) | −0.302% (n = 13,348) |

So the old D bracket (0.15% / 0.25%) is materially tighter than the bracket it was meant to mirror.

## Decision
- `labels.risk.stop = 0.0019` (≈ the mean of the two median stop moves, 0.19%).
- `labels.risk.target = 0.003` (≈ the median target moves, 0.30%). D now has its own target key
  and no longer reuses the B primary threshold (0.25%), which is unchanged.
- `labels.version` = **L2** (L1 superseded; its files and catalogue entry are kept).

## Consequences
- Same-bar ambiguity, UNRESOLVED handling and everything else in D are unchanged.
- The dispersion is wide (10th–90th percentile of stop moves ≈ 0.12%–0.34%) because the
  underlying move needed depends on moneyness, time of day and IV. D remains an approximation of
  the option outcome. C is the option outcome itself.
- The values were chosen from pre-holdout data only. They are now frozen; revisiting them needs a
  new ADR, and any such revisit counts as a tested configuration (spec §10).
