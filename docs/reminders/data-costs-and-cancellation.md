# Reminder: data costs and how to stop them

Last updated 2026-10-08. Keep this with the project; review it when M19T/M20 finish.

## What has been bought (one-off, nothing recurring)
| when | what | cost | recurring? |
|---|---|---|---|
| M2/M4 (2026-10-05) | QQQ underlying + 1DTE/2DTE options history (Databento, usage-based) | ≈ $13.26 | no |
| M19T (2026-10-08) | expiry-day options 2023–2026, holdout-period storage, 2020–2023 extension, QQQ daily bars | $10.18 | no |

These were **pay-per-request** downloads. They created no subscription. Nothing renews.

## Forward data collection (F): approved, not started
- **Approved:** about $0.64/month of Databento usage-based pulls for sessions after 2026-10-02.
- **Not set up:** no script and no scheduled task exist yet.
- **If it is set up later**, it will be one of two things:
  - a script you run, which stops when you stop running it; or
  - a scheduled task. To stop that, delete the task: ask Claude to remove it, or use the scheduled-tasks list in the desktop app.
- **Alternative:** collect live data during paper trading (M20) instead. See below.

## Checklist to stop all data spending when finished
1. **Databento account.**
   - Check your plan. If you are on a monthly plan (for example "Standard"), cancel it in the
     Databento portal's billing/plan page. Menu names may differ; Databento support can confirm.
   - On pay-as-you-go there is nothing to cancel. Optionally set a usage or spending limit in the
     portal, or revoke the API key in `.env` so no script can spend money.
2. **Scheduled tasks.** If forward collection was ever scheduled, delete the task.
3. **Paper trading (M20, later).** Live market data from a broker (for example IBKR) is usually
   a **monthly subscription**. Cancel it in the broker's account settings under market data
   subscriptions when paper trading ends. Menu names may differ; confirm with the broker.
4. **API keys.** When the project is finished, remove the keys from `.env` and revoke them in
   each provider's portal.

## Can forward data come from paper trading instead?
Yes, technically. M20's live feed would see the same sessions. Three caveats:
- **Timing:** M20 is blocked until a strategy passes development gates. Forward data is meant to
  *confirm* a strategy *before* paper trading. Waiting for M20 means the confirmation data
  starts accumulating only after M20 starts.
- **Same source:** confirmation data should come from the same vendor and construction as the
  development data (Databento consolidated 1-minute quotes). A broker feed has its own NBBO and
  snapshot timing, so its results could differ for data reasons, not strategy reasons.
- **Cost:** about $0.64/month at Databento is cheaper than most live-data subscriptions.
