# ADR-0012 — Phase 1b: pre-registered trade-definition study (long premium)

- Status: **ACCEPTED** (owner, 2026-10-08: inputs 1(i) and 2(i); redraft 2 of the owner's draft
  `ADR Adjustment.md`; change log at the end)
- Date: 2026-10-08
- Milestone: M19S (new; the name is a placeholder). It follows M19R, which closed with no validated
  edge (`reports/research/m19r_closing.md`).
- Amends, **for this study only**: PHASE_1_SPEC §2 (max holding), §3 (C labels), §4.7–4.8 (exits)
  and §5 (selection). The Phase 1 definitions stay in force for everything else.
- Disclosure: drafted after the M19R results were seen. The candidates are motivated by M19R D1/D3
  and the descriptive label statistics (`scripts/m19r_label_stats.py`), not by any model run on
  them.
- Registry at drafting: **n_trials = 35** distinct config hashes (59 runs) in `validation_runs`.
  At acceptance (2026-10-08): **n_trials = 35**, unchanged.

## Context
- **M19 verdict: FAIL.** M19R found no configuration passing gates 6 and 12 for the C bracket. The
  score-tail rules (E5/E6) showed no cost-adjusted edge: mean-net CIs included 0.
- **Descriptive, pre-holdout, no model:**
  - the current trade wins 25–28% against a breakeven of about 0.41;
  - mean net is −$5.05 to −$5.27 per trade;
  - friction is about $3.40 per trade (median entry spread $0.02, which is 0.8% of premium).
  - The main obstacle is the bracket's geometry plus time decay, not friction.
- **D3:** there is real but small direction information for the underlying's 90-min move (A
  targets), and none for C_put. The C bracket appears to discard it.
- **Burnt test blocks:** the walk-forward test blocks have been evaluated by 35+ configurations
  and can no longer serve as an out-of-sample test.

## Decision

### D0. Data roles
1. All pre-holdout sessions (2023-03-28 → 2026-04-02) are **development data** for this study. No
   result on them is reported as out-of-sample.
2. Confirmation uses only data that no decision has touched:
   - the locked holdout (ADR-0011 procedure: one logged access, fold H);
   - **and** a second confirmation source chosen under D5.
   - Both are required, not optional (see D5: the holdout alone cannot satisfy gate 15).
3. Every run is registered and counted in n_trials, continuing from M19R's count.
4. Step 1 is one registered run, but it compares about 14 definition × side cells at 3 coverages.
   The screen is itself a selection on development data, and its effective number of comparisons
   is larger than its single registry entry. Reports state this.

### D1. Candidate definitions (frozen; nothing is added after any result)
Common to all:
- entries on the §2 schedule (09:45–15:00, every 5 min), with §6 latency and the conservative fill
  for screening;
- stop/target triggers on the bid; forced flat at 15:50;
- §4.8 costs; 1 contract; calls and puts both evaluated;
- §4.9 liquidity gates unchanged, with rejection rates reported per definition;
- same-bar ambiguity follows PHASE_1_SPEC §3: the stop is assumed first and the bar is flagged
  `AMBIGUOUS_BAR`.

| id  | contract (§5)                    | exit                                                        |
|-----|----------------------------------|-------------------------------------------------------------|
| T0  | frozen ATM/first-OTM             | +30% / −20% option bracket, cap 90 min (control, unchanged) |
| T1a | frozen ATM/first-OTM             | time exit at T+45                                           |
| T1b | frozen ATM/first-OTM             | time exit at T+90                                           |
| T2  | frozen ATM/first-OTM             | QQQ bracket −0.19% / +0.30% (ADR-0007 D labels), cap 90     |
| T3  | 2 strikes ITM of the frozen pick | time exit at T+90                                           |
| T4  | frozen ATM/first-OTM             | ±30% option bracket, cap 90                                 |
| T5  | frozen ATM/first-OTM             | +30% / −20% option bracket, cap **150** min                 |

Notes:
- **T2 triggers** come from QQQ 1-min bars. If one bar breaches both sides, the stop is assumed
  first (§3). The option exit fills at the bid of the option quote in force at the trigger minute
  (§6 exit rule, conservative fill).
- **T3** uses a fixed strike offset (no model-computed delta), so selection stays point-in-time and
  model-free.
- **T5:** only entries at or before 13:20 are a true 150-min definition. Later entries get a
  shorter, mixed cap from the forced-flat time.
  - Step 1 reports T5, and T0 for comparison, separately for entries ≤ 13:20 and > 13:20.
  - **Only the ≤ 13:20 cell of T5 can advance**, and if it does, Step 2 trades T5 only for entries
    ≤ 13:20.
- **Direction horizon:** each definition's direction horizon h is its holding cap: 45 for T1a, 90
  for T0, T1b, T2, T3 and T4, and 150 for T5. Direction is the A-label direction over (T, T + h]: the
  §3 reference price P_T (`qqq_reference`, bars known at T) vs the window's end, with the frozen
  ±5 bp deadband (`labels.direction.deadband`). Only h changes.

### D2. Step 1 — model-free screen plus achievable accuracy (one registered run)

**Direction scores and Â.**
- **Score source:** walk-forward **test-block** scores of Model 2's A_up / A_dn models.
  - These models were fit on train and selected by calibration-block log loss, so their
    calibration-block scores are selection-biased.
  - D0 already declares the test blocks to be development data.
  - *Owner input 2 below; the alternative is calibration blocks with the bias disclosed.*
- **Horizons:**
  - At h = 90, the existing M9 scores are used.
  - At h = 45 and h = 150, Model 2 is **refit with the frozen M9 grid point per fold (no grid
    search)** on A labels at that horizon. Each refit is registered and counted (D-Budget).
  - A model trained for 90 minutes is never used to score another horizon.
- **Side rule:** at each timestamp the predicted side is CALL if p_up > p_dn, otherwise PUT. The
  direction score is s = max(p_up, p_dn).
- **Coverage c:** the c ∈ {100%, 20%, 5%} of timestamps with the highest s, ranked within each
  fold.
- **Accuracy Â(c):** the share of correct sides among the covered timestamps that are outside the
  deadband.

**Required accuracy a*(c), conditioned on the same population.**
- For each definition and coverage, using only the covered timestamps and trading the *predicted*
  side's contract:
  - C(c) = mean net P&L when the predicted side was correct;
  - W(c) = mean net P&L when it was wrong;
  - D(c) = mean net P&L on deadband timestamps;
  - p_D(c) = the deadband share.
- a*(c) = (−p_D(c)·D(c)/(1−p_D(c)) − W(c)) / (C(c) − W(c)).
- The full-tape (c = 100%) a* is also reported per side (CALL, PUT) for the outcome mix.
- **Time-of-day view:** Step 2 trades at most 3 entries per day (the first qualifying signals), so
  Step 1 also reports a*(c) and Â(c) by entry bucket (09:45–11:00, 11:00–13:20, 13:20–15:00).

**Uncertainty.** Session-block bootstrap (2,000 reps). Δ(c) = Â(c) − a*(c) is bootstrapped
**paired**: Â and a* are recomputed on the same resampled sessions.

**Reported for every definition × coverage (and side at c = 100%):**
- the outcome mix;
- mean net with CI; median net; losing-trade share;
- C, W, C − W, D and p_D;
- a* with CI, Â with CI, Δ with CI;
- the number of trades and of distinct sessions;
- §4.9 rejection rates.

For anything that advances, also report a session-bootstrap maximum-drawdown distribution under
`max_entries_per_day = 3`. Medians, loss shares and drawdown are reported only; they do not enter
the advance rule. Long premium has a convex payoff, so its median is negative almost by
construction.

**Sensitivity (reported only, never used to choose):**
- a* under deadband 3 / 5 / 10 bp: does the definition ranking change?
- implied coverage and trade count under edge margins 0.01 / 0.03 / 0.05.

**Guards (a cell can never advance if any applies):**
- C(c) ≤ W(c): a* is undefined. The cell is reported and barred.
- Fewer than 300 trades or fewer than 150 distinct sessions at that coverage (the gate-15 floors,
  applied to development data).
- T5 entries after 13:20.

**Advance rule.**
- A definition qualifies at coverage c if the paired-bootstrap **one-sided 95% lower bound of Δ(c)
  is > 0** and no guard applies.
- Qualification at any of the 3 coverages counts; this multiplicity is disclosed per D0.4.
- At most **2** definitions advance: those with the largest Δ(c) lower bound, each at its best
  qualifying coverage.
- **Ties:** lower bounds within 0.005 of each other are broken by the larger number of distinct
  sessions, then by the simpler definition in the order T1b, T1a, T2, T0, T4, T5, T3.
- The 95% level is strict for a screen, given overlapping labels and only about 2 years of
  development data. That is accepted: a definition that cannot clear it on development data is
  unlikely to clear the holdout.

**Kill rule:** if no definition qualifies, the long-premium direction line is closed and recorded in
MILESTONES.

### D3. Step 2 — model test (≤ 4 configurations)
For each advanced definition:
- **Trade rule:** Model 2 (and Model 1 as a second configuration only if the budget remains) trades
  the side whose **calibrated** direction probability exceeds that definition's a*(c) + edge_margin.
  - edge_margin = 0.03, carried over from PHASE_1_SPEC §4.1 (`decision.edge_margin`). There it is a
    margin on the C-label probability; here it is a margin of 3 accuracy points. The 0.01 / 0.05
    sensitivity is reported only.
- **Calibration:** the M13 recipe on calibration blocks for the needed A target and horizon. A
  missing calibration is added under the same recipe. Calibrators are not counted as separate
  trials; the underlying model refits are (D2, Budget).
- **Live-like limits:** max_entries_per_day = 3, max_open_positions = 1 (the existing config
  values).
- **Evaluation on development data:**
  - **6** (beats baseline);
  - **9** (costs);
  - **10** (walk-forward expectancy > 0, CI lower bound > 0, positive in ≥ 60% of folds);
  - **11** (execution robustness: positive under conservative fills; sign stable for
    α ∈ [0.25, 0.75]);
  - **12** (calibration);
  - **13** (regime cells);
  - **14** (NO_TRADE validated);
  - **15** (≥ 300 trades and ≥ 150 sessions);
  - **16** (PBO ≤ 0.20; DSR ≥ 0.95 using the full n_trials).
- **Reporting:** also report median net, losing-trade share and the drawdown distribution.
- **Freeze rule:** only a configuration passing all of these on development data can be frozen
  for confirmation. If none passes, the line is closed as under the kill rule.

### D4. Power analysis and pre-committed readings (before any confirmation access)
1. From development data, for the frozen configuration:
   - the SD of per-session net P&L under `max_entries_per_day = 3`;
   - the expected number of trading sessions in the holdout.
2. **Edge used for power:** the **lower bound of the 95% CI** of the frozen configuration's
   development-data mean edge per session. This is not the point estimate, which is the winner of
   a selection and biased upward.
3. Report the minimum detectable edge (one-sided α = 0.05, power 0.8) and the **power at that edge**
   for:
   - the holdout alone;
   - the holdout plus the second source.
4. **Frozen expectations:** before the holdout access, record in this ADR's milestone, with CIs:
   - the predicted Â;
   - the predicted win rate;
   - the predicted mean net per trade and per session;
   - the predicted number of trades and of trading sessions.
5. **Pre-committed reading of each confirmation source** (each judged on gate 10's expectancy
   criterion, adapted to one block: mean net > 0 with CI lower bound > 0):
   - **pass** → that source supports the edge;
   - **fail with power ≥ 0.8** → that source refutes it;
   - **fail with power < 0.5** → inconclusive; that source's result does not count either way;
   - power between 0.5 and 0.8 → reported as weak evidence against; it does not refute on its own.

### D5. Confirmation
- **Holdout:** one frozen configuration goes to the holdout (ADR-0011 procedure, one logged
  access).
- **Gate 15 cannot pass on the holdout alone.** The holdout has about 125 sessions, so fewer than
  150 sessions can have a trade. Gate 15 is evaluated on the holdout plus the second source
  combined, so the second source is **mandatory** before M20.
- **The owner chooses the second source before Step 2:**
  - (a) forward data collection after 2026-10-02 (data only, no orders), run until the combined
    sessions satisfy gate 15 and the D4 power target; or
  - (b) OPRA history from before 2022-11.
    - Verify coverage and cost first.
    - The underlying and futures feeds would also need older equivalents.
    - Before 2022-11, QQQ had only Mon/Wed/Fri expirations, so 1DTE exists on a subset of sessions.
- **Pre-committed combined verdict:**

| holdout | second source | verdict |
|---|---|---|
| supports | supports | candidate for M20 (paper only), after an adoption ADR |
| supports | refutes | **regime-fragile → rejected** (or NO_TRADE-by-regime, only through a new ADR) |
| refutes | supports | rejected: the holdout is the only untouched in-period test |
| refutes | refutes | rejected; the line is closed |
| any | inconclusive | collect more forward data under (a) before any verdict; no other change |

### Budget
- Step 1: 1 run, plus **2 refits** (h = 45 and h = 150, D2).
- Step 2: ≤ 4 configurations.
- **Total: ≤ 7 new trials** (*owner input 1 below*). No extensions without a new ADR.
- n_trials is checked at each registration against 35 + 7 = 42.

### Owner inputs (resolved at acceptance unless marked open)
- Resolved 2026-10-08:
  - 1(i): keep T1a and T5, with 2 counted refits; ≤ 7 trials.
  - 2(i): Â comes from test-block scores.
  - 3: T3 stays as drafted (2 strikes ITM); the owner did not change it.
  - 4: T+45 and T+90 (implied by 1(i)).
- Open: 5 (D5 second source), due before Step 2.

As drafted:
1. **Budget and horizons:** either
   - (i) keep T1a and T5 with the 2 counted refits, ≤ 7 trials (as drafted); or
   - (ii) drop T1a and T5, so only 90-min models are needed, no refits and ≤ 5 trials.
2. **Â source:** either
   - (i) test-block scores (as drafted); or
   - (ii) calibration-block scores, with the selection bias disclosed.
3. **T3 capital:** an ITM contract costs about 2× the ATM premium (about $400 or more vs about
   $200). If that is too much, replace it with 1 strike ITM.
4. **T1 horizons:** confirm T+45 and T+90 (if 1(ii), T+90 only).
5. **D5 second source:** (a) or (b); this can be deferred until before Step 2.

## Consequences
- The selection rule (T3) and the exit rules (T1–T5) are study-only until a single configuration
  passes confirmation. Adopting one into Phase 1 needs its own ADR.
- If the kill rule fires, the long-premium direction approach is closed. The options remaining:
  - new data;
  - **defined-risk structures** (for example, debit verticals), which reduce time decay and
    implied-volatility exposure at about double the friction and a capped payoff. They are
    explicitly not covered here and need their own ADR;
  - a different strategy class (premium selling is out of scope for now, at the owner's choice).
- Changing any definition, rule, threshold or budget here needs a new ADR.

## Change log vs the owner's draft (`ADR Adjustment.md`)
1. **Coverage-conditional a\*:** a*(c) is computed on the same covered timestamps as Â(c), using
   the predicted side, with a time-of-day view (D2).
2. **CI in the rule:** the advance rule uses the one-sided paired-bootstrap lower bound of
   Â(c) − a*(c) (not CI overlap, which is far stricter than intended). Tie handling and the
   multiplicity disclosure are added (D2, D0.4).
3. **Â defined:** from Model 2's A_up / A_dn scores, with an explicit side rule. The source is test
   blocks, because the calibration blocks were used for hyperparameter selection (D2, owner
   input 2).
4. **Â at other horizons:** comes from refits with the frozen M9 grid point at 45 and 150 min,
   counted as trials. The budget is 5 → 7 (owner input 1).
5. **Step 2 gates:** now include 10, 11, 13 and 14. Previously 6, 9, 12, 15 and 16 only, which
   never required a positive net expectancy.
6. **Gate 15 vs the holdout:** with about 125 sessions it cannot pass alone, so the second
   confirmation source is mandatory, not dependent on power (D5).
7. **Reporting and guards:**
   - distribution reporting (median, loss share, drawdown) is added, report-only (D2);
   - guards: C ≤ W, the gate-15 trade/session floors, T5 > 13:20 cells barred (D2).
8. **Provenance:** edge_margin and the deadband are cited from the spec; sensitivity at
   0.01 / 0.03 / 0.05 and at 3 / 5 / 10 bp is reported only.
9. **D4 pre-commitments:** power is computed at the development-data CI lower bound; readings of a
   pass, a fail and an inconclusive result; frozen expectations before the holdout.
10. **D5:** the combined-verdict table, including split verdicts.
11. **T2 and same-bar order:** T2's intrabar order and the option exit fill are specified (§3
    same-bar rule, §6).
12. **Records:** n_trials at drafting (35) is recorded, with a blank for acceptance.
13. **Debit verticals:** named in Consequences as a deferred, defined-risk path.
