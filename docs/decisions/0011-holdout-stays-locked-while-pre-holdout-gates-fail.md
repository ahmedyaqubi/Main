# ADR-0011 — The final holdout stays locked while pre-holdout gates fail

- Status: **ACCEPTED** (owner, 2026-10-08, option B)
- Date: 2026-10-08
- Milestone: M19 (criterion 1)
- Amends: MILESTONES M19 criterion 1 ("final holdout opened exactly once") and the use of spec §8's final holdout. It does not change the holdout's definition (the last 6 calendar months, sessions after 2026-04-02), its lock, or its single-access rule.

## Context
M19 evaluates gates 1–18. The walk-forward evidence (M7–M18, all pre-holdout) already fails several
performance gates for the pre-declared decision configuration (`gbm_m2`, ADR-0010):

- gate 6: Brier skill vs Model 0 for C_call / C_put has a CI that includes 0;
- gate 12: calibration fails for both C targets;
- gate 15: 0 trades;
- gates 10, 11, 13, 14 and the DSR part of 16 cannot be evaluated without trades.

Every performance gate must pass on the walk-forward evidence and be confirmed on the holdout. With
the walk-forward failing, opening the holdout cannot change the verdict from FAIL. It would still
spend the holdout: the spec allows one access, so any later configuration would need new data after
2026-10-02 as its holdout.

## Decision
- M19 is run as a single registered `final_validation` run over the walk-forward evidence. Gates
  1–18 are evaluated with numbers, CIs, sample sizes, `n_trials`, DSR and PBO, with an explicit
  PASS / FAIL per gate. FAIL on any gate stops progression to M20, as M19 already requires.
- The final holdout is **not** opened. `final_test_access_log` stays empty.
- The holdout is opened, exactly once and logged, only for the first configuration that passes
  every pre-holdout gate. Its holdout evaluation then follows the frozen recipe with one extra fold
  ("fold H": train through the embargo before a 2-month calibration block ending 2026-04-02, test =
  the holdout), and each performance gate must pass on both the walk-forward and the holdout.

## Consequences
- M19 delivers a complete, honest gate verdict without consuming the holdout.
- Progression to M20 (paper mode) is blocked by the failing gates unless the owner records an ADR
  accepting a limitation.
- Changing this needs a new ADR.
