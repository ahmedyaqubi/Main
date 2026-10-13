# ADR-0020: Exception for Shiller's partial final month; the M27 holdout stays confirmatory

- Status: **ACCEPTED** 2026-10-13 by the owner ("approve, go ahead"). The owner chose this
  option ("option 2") **before any holdout strategy statistic was computed**.
- Amends: ADR-0019 H2, the clause "no exception may be granted afterwards without a new ADR that
  says the holdout result is then descriptive only". **This ADR explicitly overrides that
  clause** for the one finding below.

## What happened
- **Run `screen_pullback_holdout-b47cc1560348`** (code 59882ec) logged the one access under
  ADR-0019, read the holdout rows, and stopped at the H2 data checks. Its status is FAILED.
- **The only failure:** check (e), SPY vs Shiller prices, in month **2023-09**. The ratio was
  2.5% off its median (limit ±1%).
- **Everything else passed:**
  - 2,701 holdout sessions, with 0 missing, 0 adjustment, 0 jump, 0 open-ratio and 0 open-gap
    findings;
  - 4 dividends in each year 2016–2025;
  - the other 92 Shiller price months and all 90 Shiller dividend months.
- **No strategy statistic was computed or seen.** The script stops before signals or trades are
  built, and the STOP report (`reports/research/m27_holdout.md`) contains data checks only.

## Cause (verified)
- In the Yale `ie_data.xls`, each month's P is a **monthly average** of daily closes, except
  the file's **final month, 2023-09**.
- That month's value, **4515.77**, is a **single day's S&P 500 close**, to the assistant's
  knowledge the close of 2023-09-01.
  - It has two decimals, while the averages have long fractional parts (for example 2023-08:
    4457.3587…).
  - SPY's close that day × 10 is 4511.9, consistent with it. SPY's September average × 10 is
    4399.3.
- The check compared that single day with SPY's **whole-month average** (4399.3), giving the
  2.5% gap. This is a check-design error, the assistant's, not a defect in SPY data.
  - ADR-0019 A1 inspected the file's month labels before access, but not whether its final
    month was complete.

## Decision
- **E1:** check (e) excludes Shiller's final month **2023-09** from the price comparison, so it
  covers 2016-01 → 2023-08 (92 months). Nothing else changes: no threshold, no other month, no
  rule, cost, statistic or outcome definition.
- **The holdout result remains confirmatory** (PASS / KILL / NOT CONFIRMED, as ADR-0019 H3),
  not descriptive only.
  - **Why this is still an honest test:** the descriptive-only clause exists to stop a data
    exception being granted *after* a disappointing result. Here the exception is decided blind
    to the result, on a cause anyone can verify, and limited to one month of an external
    reference file.
  - **Disclosed cost:** this overrides a rule written in advance. Readers should weigh that, and
    the report will say so at the top.
- **One more access, once:**
  - a new registered run (touches_final_holdout), logged with `adr_ref = "ADR-0020"`;
  - the script refuses if an ADR-0020 access is already logged or a non-FAILED holdout run
    exists;
  - the code is the committed 59882ec script **plus only** the 2023-09 exclusion and the new
    ADR reference, committed with owner OK before the run.
  - **The data checks run again in full.** Any new failure stops the idea with no further
    exceptions: this ADR allows none.
- **After the rerun:** the independent rebuild of every holdout trade, CI, and the report, as
  planned in ADR-0019.

## Consequences
- **Registry:** n_trials on the 2016–2026 window rises again (41 → 42); both runs stay
  recorded.
- **Process lesson (for `docs/LESSONS_LEARNED.md`):** before a one-shot access, check that every
  external reference series is complete in every month it is compared on, not just that the
  month labels exist.
