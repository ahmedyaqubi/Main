# Lessons learned (Phase 1 + Phase 2, 2026-10-05 → 2026-10-10)

What the research taught us, and the practical traps we hit. Read this before starting any new
study.

## The three findings
1. **Option prices were fair, and direction signals were tiny.**
   - Option prices already reflected how far QQQ would move (M19R D1: an implied-move benchmark
     matched the full model).
   - Direction information was real but small. The best model accuracy was 0.557 against a
     required 0.57–0.65 (M19S).
   - Calibration failed for every option-outcome target (M19, gate 12).
2. **Costs and fills decided every result.**
   - Every strategy family lost money at realistic fills: QQQ long premium, QQQ 0/1DTE short
     premium, SPX 7/30DTE spreads.
   - Several were near break-even at mid prices. So the deciding question was always "what
     price do you really get?", never "is the prediction good?".
   - The M19T KILL also depended on the commission assumption. At $0-commission brokers the
     mid-fill results would have been near zero (`reports/research/phase1_synthesis.md` §4).
3. **The bid–ask spread was the largest cost.**
   - SPX, 0.5%-wide spreads: the gap between conservative and mid fills was about $145–$246
     per trade, against median credits of about $300.
   - QQQ: about $2.80 per spread in commissions, against $20–$33 credits.
   - The spread is roughly fixed in points while the credit grows with width, so narrow
     structures are hit hardest.

## Records that must not be lost
- **Registered trials:** 40 on the overlapping 2020–2026 window (39 from Phase 1, plus 1 in
  M23). Any later result on these dates must be judged against that count (deflated Sharpe,
  PBO).
- **Locked holdouts, never read. They are the most valuable data we own:**
  - QQQ: 2026-04-03 → 2026-10-02 (ADR-0011);
  - SPX: 2025-10-03 → 2026-10-02 (ADR-0014 D3).

  Each may be opened once, only by an owner ADR, for a configuration that passed every
  development gate.
- **Data spend:** about $37 in total, all one-off (`docs/reminders/data-costs-and-cancellation.md`).

## Practical gotchas (each one cost us time)
**Data:**
- **OCC-adjusted strikes.** QQQ paid a special dividend; OCC memo #53847, ex-date 2023-12-27.
  Strikes became off-dollar (for example 399.78).
  - Downloads that request whole-dollar symbols silently miss those contracts.
  - Check the corporate actions for the whole window before buying data (ADR-0005; M19T R3
    supplement).
- **Zero-quote days.** Databento resolved definitions but returned no quotes for ext
  2021-02-09 / 02-10.
  - Code must treat a missing file as UNRESOLVED_DATA, never as a crash or an empty success.
- **Symbology timing.**
  - Symbology resolution is day-level: a contract "listed on D" may have been listed after the
    trade time.
  - Choose expiries and strikes from point-in-time data: definitions known at T_e, or listings
    from earlier days.
  - Never substitute an expiry or strike that wasn't stored (M23 leakage-review fix).
- **Calendar and exclusions are instrument-specific.** QQQ's excluded session (2023-12-27) and
  strike adjustment must not be applied to SPX. Use a config copy per instrument.
- **A cap in points becomes an index-level cap.** SPX's fixed 2.00-point spread cap failed
  mostly in high-index years. Use relative thresholds (R10 amendment).

**Money and approvals:**
- **Fill and price rounding.**
  - Fills round against the trader to the tick. Prices quoted to the owner must not be
    rounded down: a $10.64 quote was really $10.642887, and the cap guard stopped the
    download.
  - Quote exact totals and an "approve up to" figure rounded up.

**Running long jobs:**
- **The 2-hour background-job limit.**
  - Long downloads and builds hit it.
  - Make every long job resumable (cache plus skip what's on disk).
  - For multi-hour work, start a detached process (`Start-Process`, log file) and watch it.
- **Detached runs and the terminal panel.** The desktop app's terminal integration failed:
  that shell couldn't see `AppData\Roaming`, so `uv.exe` wasn't found. Detached processes using
  `.venv\Scripts\python.exe` worked.
- **Network errors.** Retry dropped connections as well as vendor 5xx errors.

**Statistics and process:**
- **Sampling bias in price quotes.** Every 20th session is nearly always the same weekday; use
  a stride coprime with 5.
- **Never peek before the registered run.**
  - Debug a screen on synthetic labels (`--dry-run-labels`).
  - Look only at statuses and entry fields until the trial is registered.
- **Overlapping positions need block bootstraps.** 7–30-day holds entered daily overlap, so the
  effective sample is the number of independent holding periods (M23 R12).
- **Register from committed code only.** Dirty-tree runs create catalogue rows tied to "-dirty"
  commits that later need cleaning (M19T incident).
