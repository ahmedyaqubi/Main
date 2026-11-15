# M30: underlying quotes that S2 would read (survey before the plan; no signal)

Generated 2026-11-15 03:59 Alberta Daylight Time by `scripts/m30_quote_survey.py`. Development sessions only. Timestamps are counted and bid-ask spreads measured; no return, direction or price level is computed.

For each time, the record read is the latest cleaned one with `available_at` at or before it. *usable* = at most 60 seconds old, two-sided, not crossed. Spread is a share of the mid, over usable records. The 10:00, 15:30 and 15:50 rows leave out early-close sessions (S2 is NO_TRADE there); the close rows use each session's own close (16:00, or 13:00 on an early close); close-1m and close-5m are one and five minutes before it.

| ticker | time | sessions | stamped exactly | usable | none or stale | one-sided or crossed | usable but not regular-hours | median | 90th | 99th | largest | over 0.05% | over 0.10% | over 0.20% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QQQ | close | 757 | 757 | 757 | 0 | 0 | 0 | 0.011% | 0.034% | 0.150% | 0.279% | 54 | 35 | 2 |
| QQQ | close-1m | 757 | 757 | 757 | 0 | 0 | 0 | 0.003% | 0.006% | 0.011% | 0.019% | 0 | 0 | 0 |
| QQQ | close-5m | 757 | 757 | 757 | 0 | 0 | 0 | 0.006% | 0.017% | 0.056% | 0.181% | 16 | 2 | 0 |
| QQQ | signal_10:00 | 749 | 749 | 749 | 0 | 0 | 0 | 0.008% | 0.062% | 0.218% | 0.528% | 91 | 28 | 9 |
| QQQ | entry_15:30 | 749 | 749 | 749 | 0 | 0 | 0 | 0.005% | 0.008% | 0.015% | 0.037% | 0 | 0 | 0 |
| QQQ | exit_15:50 | 749 | 749 | 749 | 0 | 0 | 0 | 0.011% | 0.030% | 0.088% | 0.237% | 23 | 5 | 2 |
| SPY | close | 632 | 632 | 632 | 0 | 0 | 0 | 0.007% | 0.017% | 0.133% | 0.370% | 20 | 7 | 2 |
| SPY | close-1m | 632 | 632 | 632 | 0 | 0 | 0 | 0.002% | 0.005% | 0.009% | 0.019% | 0 | 0 | 0 |
| SPY | close-5m | 632 | 632 | 632 | 0 | 0 | 0 | 0.004% | 0.009% | 0.023% | 0.061% | 1 | 0 | 0 |
| SPY | signal_10:00 | 626 | 626 | 626 | 0 | 0 | 0 | 0.006% | 0.025% | 0.128% | 0.867% | 36 | 14 | 4 |
| SPY | entry_15:30 | 626 | 626 | 626 | 0 | 0 | 0 | 0.004% | 0.007% | 0.015% | 0.032% | 0 | 0 | 0 |
| SPY | exit_15:50 | 626 | 626 | 626 | 0 | 0 | 0 | 0.006% | 0.017% | 0.049% | 0.075% | 6 | 0 | 0 |
| IWM | close | 632 | 632 | 632 | 0 | 0 | 0 | 0.010% | 0.016% | 0.029% | 0.128% | 3 | 2 | 0 |
| IWM | close-1m | 632 | 632 | 632 | 0 | 0 | 0 | 0.005% | 0.009% | 0.012% | 0.016% | 0 | 0 | 0 |
| IWM | close-5m | 632 | 632 | 632 | 0 | 0 | 0 | 0.006% | 0.012% | 0.023% | 0.061% | 1 | 0 | 0 |
| IWM | signal_10:00 | 626 | 626 | 625 | 0 | 0 | 0 | 0.012% | 0.062% | 1.083% | 3.831% | 72 | 40 | 24 |
| IWM | entry_15:30 | 626 | 626 | 626 | 0 | 0 | 0 | 0.006% | 0.011% | 0.015% | 0.022% | 0 | 0 | 0 |
| IWM | exit_15:50 | 626 | 626 | 626 | 0 | 0 | 0 | 0.011% | 0.031% | 0.522% | 4.261% | 29 | 14 | 12 |
| NVDA | close | 632 | 631 | 631 | 1 | 0 | 0 | 0.133% | 0.537% | 1.342% | 2.090% | 491 | 371 | 226 |
| NVDA | close-1m | 632 | 631 | 631 | 1 | 0 | 0 | 0.012% | 0.044% | 0.236% | 0.657% | 50 | 16 | 9 |
| NVDA | close-5m | 632 | 631 | 631 | 1 | 0 | 0 | 0.024% | 0.070% | 0.206% | 0.405% | 123 | 37 | 8 |
| NVDA | signal_10:00 | 626 | 625 | 625 | 1 | 0 | 0 | 0.047% | 0.121% | 0.239% | 0.349% | 291 | 105 | 12 |
| NVDA | entry_15:30 | 626 | 625 | 625 | 1 | 0 | 0 | 0.018% | 0.056% | 0.110% | 0.158% | 92 | 10 | 0 |
| NVDA | exit_15:50 | 626 | 625 | 625 | 1 | 0 | 0 | 0.024% | 0.065% | 0.129% | 0.303% | 105 | 24 | 2 |
| TSLA | close | 632 | 632 | 632 | 0 | 0 | 0 | 0.192% | 0.698% | 1.697% | 2.853% | 560 | 453 | 308 |
| TSLA | close-1m | 632 | 632 | 632 | 0 | 0 | 0 | 0.016% | 0.059% | 0.603% | 1.617% | 79 | 28 | 14 |
| TSLA | close-5m | 632 | 632 | 632 | 0 | 0 | 0 | 0.033% | 0.097% | 0.226% | 0.396% | 184 | 61 | 12 |
| TSLA | signal_10:00 | 626 | 626 | 626 | 0 | 0 | 0 | 0.063% | 0.135% | 0.231% | 0.444% | 413 | 140 | 15 |
| TSLA | entry_15:30 | 626 | 626 | 626 | 0 | 0 | 0 | 0.023% | 0.064% | 0.124% | 0.187% | 113 | 17 | 0 |
| TSLA | exit_15:50 | 626 | 626 | 626 | 0 | 0 | 0 | 0.033% | 0.087% | 0.185% | 0.352% | 167 | 50 | 6 |

## Sessions and gaps

- QQQ: 757 calendar sessions, 756 research sessions, 8 early closes; rejected underlying records stamped at one of these times: 0; research sessions whose previous session is outside the data or excluded: 2023-03-28, 2023-12-28
- SPY: 632 calendar sessions, 632 research sessions, 6 early closes; rejected underlying records stamped at one of these times: 0; research sessions whose previous session is outside the data or excluded: 2023-03-28
- IWM: 632 calendar sessions, 632 research sessions, 6 early closes; rejected underlying records stamped at one of these times: 0; research sessions whose previous session is outside the data or excluded: 2023-03-28
- NVDA: 632 calendar sessions, 632 research sessions, 6 early closes; rejected underlying records stamped at one of these times: 0; research sessions whose previous session is outside the data or excluded: 2023-03-28
- TSLA: 632 calendar sessions, 632 research sessions, 6 early closes; rejected underlying records stamped at one of these times: 0; research sessions whose previous session is outside the data or excluded: 2023-03-28
