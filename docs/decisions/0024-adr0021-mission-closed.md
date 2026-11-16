# ADR-0024: The ADR-0021 mission is closed; no setup advanced

- Status: **ACCEPTED** 2026-11-16 by the owner ("Accept and open PR"). Drafted by the assistant
  at the owner's request ("Do the tidy-up after the merge").
- Closes: ADR-0021 (autonomous options day-trading agent), as its Consequences section
  requires. Does not change ADR-0021's text, any of its amendments, or any result.
- Changes no definition in `docs/PHASE_1_SPEC.md`. Changes no rule, threshold or config value.

## Why
ADR-0021 allowed three pre-registered tests and states: "If nothing advances within the 3 tests,
this mission stops and is not extended without a new ADR." All three are used:

| test | setup | milestone | run | outcome |
|---|---|---|---|---|
| 1 | S1, first 5-minute candle (amendment A1) | M29 | `screen_orb-7c87b7281f30` | AMBIGUOUS |
| 2 | S2, first half-hour predicts the last (D3) | M30 | `screen_half_hour-ffe57c6e1184` | KILL |
| 3 | S3, noise-area breakout (amendment A3) | M33 | `screen_noise_area-861c924a1cfc` | AMBIGUOUS |

The owner accepted each outcome (M29 "Accept, S2 next"; M30 "Accept"; M33 "Accept and merge").
In each, the option trades lost money on average at ask and bid fills, after costs. Details:
`reports/research/m29_s1_screen.md`, `m30_s2_screen.md`, `m33_s3_screen.md`.

## Decision
- **C1. The ADR-0021 mission is CLOSED.** No further setup, variant or re-run is made under it.
- **C2. No holdout is read.** QQQ 2026-04-03 → 2026-10-02 and the other tickers'
  2025-10-03 → 2026-10-02 stay unread. M31 (D11: holdout ADR and access, only if a setup
  advances) does not happen.
- **C3. No later D9 stage is started.** The data-only recorder (stage 1b), paper, monitor and
  live stages are not built under ADR-0021. Hard rule 1 is unchanged.
- **C4. The code stays, tested and unused:** the S1, S2 and S3 rules and screens, the cost map,
  and the `study_options_day` config block. Removing any of it is a separate decision.
- **C5. The data stay** on the owner's machine (`data/`, not in the repository).
- **C6. New work needs a new owner ADR.** The 2023-03-28 → 2026-04-02 development sessions have
  now been examined by many recorded trials, so a new idea tested on them carries that history.
  A new ADR should say which data it uses and why, and should be written before any data are
  examined for it.

## Budget and counts
- Trial count: **45** (M33 was the 45th).
- ADR-0015 ledger: 6 of 10 tests used (3 under ADR-0016–0018, 3 under ADR-0021); $36.17 of
  $100 spent on data. Any use of the remaining tests needs a new owner ADR.

## Consequences
- `CLAUDE.md` and `docs/ROADMAP.md` no longer name ADR-0021 as the current mission; they point
  here. No current mission is named until the owner accepts a new ADR.
