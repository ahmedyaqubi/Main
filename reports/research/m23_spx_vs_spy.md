# M23 Step 0: SPX vs SPY entry friction (ADR-0014)

Generated 2026-10-09 05:28 UTC by `scripts/m23_compare_sample.py`. Entry quotes only (10:00:05 ET) on 30 development sessions, 2013-04-01 → 2025-03-26. No exit, P&L or outcome computed; nothing registered. Sample cost $0.0659.

Put-spread pick by the frozen credit rule, X = 0.2, W = 0.5% of the previous close (SPY: SPX close / 10, descriptive only). Medians; prices in index or ETF points (x 100 = $ per spread). *Friction share*: (mid credit - conservative credit) / mid credit.

| target DTE | underlying | picks | W | mid credit | conservative credit | friction | friction share | short-leg spread | long-leg spread |
|---|---|---|---|---|---|---|---|---|---|
| 7 | SPX | 30 | 15 | 3.925 | 3.250 | 0.400 | 11.5% | 0.450 | 0.350 |
| 7 | SPY | 30 | 1 | 0.265 | 0.230 | 0.020 | 8.1% | 0.020 | 0.025 |
| 30 | SPX | 26 | 15 | 4.175 | 3.000 | 0.800 | 18.3% | 0.800 | 0.800 |
| 30 | SPY | 29 | 1 | 0.275 | 0.220 | 0.050 | 13.7% | 0.050 | 0.050 |

Status counts (OK / AT_BAND_EDGE / NO_QUALIFYING): SPX 7d OK 30, SPX 30d NO_QUALIFYING 4, SPX 30d OK 26, SPY 7d OK 30, SPY 30d NO_QUALIFYING 1, SPY 30d OK 29.

Commissions and fees are not included: they depend on the broker schedule (R3). SPX carries an index-option fee per contract on top; SPY a much smaller equity fee. One SPX spread is about 10x the notional of one SPY spread.
