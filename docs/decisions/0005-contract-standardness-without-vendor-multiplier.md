# ADR-0005 — Standard-contract evidence without a vendor multiplier; OCC strike adjustments

- Status: **ACCEPTED** (owner, 2026-10-06, option "b")
- Date: 2026-10-06
- Milestone: M4
- Amends: PHASE_1_SPEC §1 ("Contract multiplier: 100 (verify per contract from chain metadata;
  reject the contract if it is not 100)") and DATA_QUALITY.md contract checks.

## Context
1. **Databento does not publish the multiplier for OPRA.** On every QQQ option definition checked
   (2023-06-01, the 2023-12-28 full chain, the 2025-03 sample week), `contract_multiplier` and
   `original_contract_size` hold the undefined value (INT32_MAX) and `unit_of_measure_qty` is
   empty. The spec's per-contract multiplier check cannot be done with this vendor. Applying it
   literally rejected every option quote in the first M4 run.
2. **OCC adjusted every QQQ option on 2023-12-27.** OCC Information Memo #53847 (2023-12-26):
   QQQ special cash dividend of $0.21584, ex-date 2023-12-27. *"Strike prices will be reduced by
   0.21584 and rounded to the nearest penny"* (e.g. 410.00 → 409.78). Symbol stays `QQQ`,
   multiplier stays 100, deliverable 100 QQQ shares. So x.78 / x.28 strikes after that date are
   real standard contracts, not vendor errors (M2 had wrongly called 2023-12-28 an anomaly).
   Contracts listed before the ex-date keep adjusted strikes until they expire. In the research
   window, 29 expirations (dailies to 2024-01-09, weeklies, monthlies, quarterlies and LEAPS
   through 2026-12-18) carry them. In 27 sessions the 1DTE expiry has adjusted strikes.

## Decision
A QQQ option definition is a **standard 100-share contract** when all of these hold:
- OCC root (first 6 characters of the OCC symbol, stripped) equals `dq.option_root` (`QQQ`).
  Adjusted-deliverable series get new roots (e.g. `QQQ1`) → `NONSTANDARD_ROOT`, rejected.
- The multiplier is 100 **or undefined**. Undefined → INFO flag `MULTIPLIER_UNKNOWN`. A defined
  value other than 100 → `INVALID_MULTIPLIER`, rejected.
- The strike is on the `dq.strike_increment` grid ($0.50), **or** matches a documented OCC
  strike adjustment in `dq.strike_adjustments` on/after its ex-date (some grid strike K with
  round(K − reduction, 2) = strike) → INFO flag `ADJUSTED_STRIKE`. Otherwise
  `NONSTANDARD_STRIKE`, rejected.
- The OCC symbol's date equals the definition's expiration, which is an XNYS session.

The same predicate (`validation.records.standard_contract`) defines the chain visible to the
frozen selection rule, so adjusted contracts are **eligible** for selection after the ex-date,
exactly as listed in the market at the time.

Data completeness: the main options pull requested whole-dollar strikes only. For the 46
sessions whose D+1/D+2 expiry carries adjusted strikes, a supplemental pull fetched the adjusted
symbols (`scripts/m4_fetch_history.py options-adjusted`, $0.16).

## Consequences
- New corporate actions require a new `dq.strike_adjustments` entry, backed by its OCC memo,
  and an amendment to this ADR. Until then an adjusted series would be rejected as
  `NONSTANDARD_STRIKE` (conservative: rejected, never silently accepted).
- **Open for M11 (selection):** whether the frozen rule should prefer standard-grid strikes when
  adjusted and standard strikes are both listed for the same expiry is a spec question, not a
  data-quality one. The current spec §5 rule ("lowest listed strike ≥ spot") treats them equally.
- Sources: OCC Information Memo #53847 (via MIAX corporate action alert,
  https://www.miaxglobal.com/alert/2023/12/26/miax-exchange-group-options-markets-corporate-action-alert-invesco-qqq);
  OCC memo index https://infomemo.theocc.com/infomemos?number=53849 (related 2QQQ series memo).
