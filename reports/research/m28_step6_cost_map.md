# M28 step 6: cost map (ADR-0021 D5). Not a trial.

Generated 2026-11-14 11:12 UTC by `scripts/m28_cost_map.py`. Development sessions only; no signal or return of either setup was computed (calls and puts priced alike; the underlying move is used only as an absolute value).

## Per ticker, setup and broker

Tradeable = quote present, passes the §4.9 liquidity gates, and ask x 100 + buy fees <= $500. Cost share and break-even are over tradeable contracts (call and put rows both counted).

| ticker | setup | broker | sessions | liquid | under cap | tradeable/side | cost share median (P25-P75) | median outlay | median break-even, calendar / trading hours (unknown) | P75 abs move | D5 rule 1, calendar / trading hours |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | S1 | ibkr_canada | 632 | 99.52% | 98.49% | 618 | 3.26% (2.61%-4.18%) | $152.03 | 0.17% / 0.38% (0 / 0) | 1.09% | kept / kept |
| AAPL | S1 | webull_canada | 632 | 99.52% | 98.49% | 618 | 3.25% (2.59%-4.16%) | $152.02 | 0.17% / 0.38% (0 / 0) | 1.09% | kept / kept |
| AAPL | S2 | ibkr_canada | 632 | 99.04% | 99.12% | 614 | 2.96% (2.23%-4.18%) | $133.03 | 0.06% / 0.07% (0 / 0) | 0.21% | kept / kept |
| AAPL | S2 | webull_canada | 632 | 99.04% | 99.12% | 614 | 2.94% (2.23%-4.15%) | $133.02 | 0.06% / 0.07% (0 / 0) | 0.21% | kept / kept |
| IWM | S1 | ibkr_canada | 632 | 99.60% | 100.00% | 629 | 3.77% (3.04%-4.50%) | $116.03 | 0.17% / 0.40% (0 / 0) | 1.01% | kept / kept |
| IWM | S1 | webull_canada | 632 | 99.60% | 100.00% | 629 | 3.75% (3.03%-4.48%) | $116.02 | 0.17% / 0.40% (0 / 0) | 1.01% | kept / kept |
| IWM | S2 | ibkr_canada | 632 | 99.92% | 100.00% | 626 | 4.13% (3.25%-5.19%) | $90.03 | 0.05% / 0.07% (0 / 0) | 0.19% | kept / kept |
| IWM | S2 | webull_canada | 632 | 99.92% | 100.00% | 626 | 4.11% (3.23%-5.17%) | $90.02 | 0.05% / 0.07% (0 / 0) | 0.19% | kept / kept |
| NVDA | S1 | ibkr_canada | 632 | 99.84% | 57.69% | 364 | 2.33% (1.91%-2.96%) | $241.03 | 0.27% / 0.64% (0 / 0) | 2.29% | kept / kept |
| NVDA | S1 | webull_canada | 632 | 99.84% | 57.69% | 364 | 2.33% (1.91%-2.95%) | $241.02 | 0.27% / 0.64% (0 / 0) | 2.29% | kept / kept |
| NVDA | S2 | ibkr_canada | 632 | 100.00% | 63.60% | 398 | 2.15% (1.64%-2.82%) | $227.03 | 0.07% / 0.10% (0 / 0) | 0.36% | kept / kept |
| NVDA | S2 | webull_canada | 632 | 100.00% | 63.60% | 398 | 2.14% (1.63%-2.81%) | $227.02 | 0.07% / 0.10% (0 / 0) | 0.36% | kept / kept |
| QQQ | S1 | ibkr_canada | 756 | 99.87% | 96.56% | 729 | 1.84% (1.49%-2.24%) | $221.03 | 0.13% / 0.31% (0 / 0) | 0.91% | kept / kept |
| QQQ | S1 | webull_canada | 756 | 99.87% | 96.56% | 729 | 1.83% (1.48%-2.23%) | $221.02 | 0.13% / 0.31% (0 / 0) | 0.91% | kept / kept |
| QQQ | S2 | ibkr_canada | 756 | 100.00% | 98.73% | 738 | 2.06% (1.56%-2.65%) | $177.03 | 0.02% / 0.04% (0 / 0) | 0.15% | kept / kept |
| QQQ | S2 | webull_canada | 756 | 100.00% | 98.73% | 738 | 2.05% (1.55%-2.64%) | $177.02 | 0.02% / 0.04% (0 / 0) | 0.15% | kept / kept |
| SPY | S1 | ibkr_canada | 632 | 99.76% | 98.49% | 620 | 1.96% (1.58%-2.33%) | $174.03 | 0.09% / 0.22% (0 / 0) | 0.64% | kept / kept |
| SPY | S1 | webull_canada | 632 | 99.76% | 98.49% | 620 | 1.95% (1.57%-2.32%) | $174.02 | 0.09% / 0.22% (0 / 0) | 0.64% | kept / kept |
| SPY | S2 | ibkr_canada | 632 | 100.00% | 98.96% | 620 | 2.31% (1.81%-2.93%) | $138.03 | 0.02% / 0.03% (0 / 0) | 0.12% | kept / kept |
| SPY | S2 | webull_canada | 632 | 100.00% | 98.96% | 620 | 2.30% (1.80%-2.92%) | $138.02 | 0.02% / 0.03% (0 / 0) | 0.12% | kept / kept |
| TSLA | S1 | ibkr_canada | 632 | 99.84% | 47.31% | 298 | 2.67% (2.12%-3.29%) | $351.03 | 0.32% / 0.74% (0 / 0) | 2.75% | kept / kept |
| TSLA | S1 | webull_canada | 632 | 99.84% | 47.31% | 298 | 2.67% (2.11%-3.28%) | $351.02 | 0.32% / 0.74% (0 / 0) | 2.75% | kept / kept |
| TSLA | S2 | ibkr_canada | 632 | 100.00% | 57.75% | 362 | 2.10% (1.74%-2.70%) | $326.03 | 0.08% / 0.11% (0 / 0) | 0.43% | kept / kept |
| TSLA | S2 | webull_canada | 632 | 100.00% | 57.75% | 362 | 2.09% (1.73%-2.70%) | $326.02 | 0.08% / 0.11% (0 / 0) | 0.43% | kept / kept |

Session statuses (rows per side):

- AAPL S1: {'PRICED': 1261, 'NO_OPTION_QUOTE': 1, 'NO_UNDERLYING_QUOTE': 1}
- AAPL S2: {'NO_UNDERLYING_QUOTE': 1, 'EARLY_CLOSE': 6, 'PRICED': 1250}
- IWM S1: {'PRICED': 1263, 'NO_OPTION_QUOTE': 1}
- IWM S2: {'PRICED': 1252, 'EARLY_CLOSE': 6}
- NVDA S1: {'NO_UNDERLYING_QUOTE': 1, 'PRICED': 1262}
- NVDA S2: {'EARLY_CLOSE': 6, 'PRICED': 1250, 'NO_UNDERLYING_QUOTE': 1}
- QQQ S1: {'PRICED': 1510, 'NO_OPTION_QUOTE': 2}
- QQQ S2: {'EARLY_CLOSE': 8, 'PRICED': 1496}
- SPY S1: {'NO_OPTION_QUOTE': 4, 'PRICED': 1260}
- SPY S2: {'PRICED': 1252, 'EARLY_CLOSE': 6}
- TSLA S1: {'PRICED': 1264}
- TSLA S2: {'PRICED': 1252, 'EARLY_CLOSE': 6}

## Required edge (D5 rule 2: information only, ADR-0021 amendment A2)

Rule 2 is **not applied**: for S1 the required edge (share of premium) and the paper's 0.13 (of the stop distance on shares) are in different units, and converting needs the signal; S2's paper effect is unverified. The figures below are also too low, especially for S1: the M11 trades they come from were closed by target and stop exits (median hold about 20-25 minutes); S1 holds 09:35 -> 15:50 with no such limit. Drops are decided by rule 1 alone.

ADVANCE level (D7): 98.3333%, one-sided. Spread of per-trade net returns, as a share of the premium paid, from the M11 conservative development trades with each broker's fees re-applied:

- ibkr_canada: sd 0.2624 over 4,528 trades (7 M11 trades with no exit price left out: no return exists for them)
- webull_canada: sd 0.2624 over 4,528 trades (7 M11 trades with no exit price left out: no return exists for them)

Expected trades per setup = tradeable sessions per side, summed over the tickers kept by rule 1 (one trade per ticker-session; D6 pools the tickers in one run).

| setup | broker | tickers kept | expected trades | required mean net return per trade |
|---|---|---|---|---|
| S1 | ibkr_canada | AAPL, IWM, NVDA, QQQ, SPY, TSLA | 3,258 | 0.98% of premium |
| S1 | webull_canada | AAPL, IWM, NVDA, QQQ, SPY, TSLA | 3,258 | 0.98% of premium |
| S2 | ibkr_canada | AAPL, IWM, NVDA, QQQ, SPY, TSLA | 3,356 | 0.96% of premium |
| S2 | webull_canada | AAPL, IWM, NVDA, QQQ, SPY, TSLA | 3,356 | 0.96% of premium |

## Days Databento marks as reduced quality

From `metadata.get_dataset_condition` (cached in `data/research/m28/dataset_condition.json`). Rows are this map's D2 contracts on those days, per ticker (development sessions only), by status:

- OPRA.PILLAR 2024-06-03: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- OPRA.PILLAR 2025-10-22: QQQ {'PRICED': 4}
- EQUS.MINI 2025-03-24: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-04-04: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-05-06: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-06-04: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-06-16: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-07-09: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-08-08: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-08-13: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-08-19: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-08-25: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-09-03: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-09-08: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-09-12: AAPL {'PRICED': 4}; IWM {'PRICED': 4}; NVDA {'PRICED': 4}; QQQ {'PRICED': 4}; SPY {'PRICED': 4}; TSLA {'PRICED': 4}
- EQUS.MINI 2025-10-10: QQQ {'PRICED': 4}
- EQUS.MINI 2025-10-13: QQQ {'PRICED': 4}

Tickers in this run: QQQ, SPY, IWM, NVDA, TSLA, AAPL.

