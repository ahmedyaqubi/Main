# M33: underlying quotes that S3 would read (survey for the plan; no signal)

Generated 2026-11-16 00:47 Alberta Daylight Time by `scripts/m33_quote_survey.py`. Development sessions only, early closes left out. Timestamps are counted and bid-ask spreads measured; no return, direction, boundary or price level is computed.

For each time, the record read is the latest cleaned one with `available_at` at or before it. *usable* = at most 60 seconds old, two-sided, not crossed. Spread is a share of the mid, over usable records. "open as read" is the open plus 1 minute(s) (`noise_area.open_offset_minutes`).

| ticker | time | sessions | stamped exactly | usable | median | 99th | largest | over 0.2% |
|---|---|---|---|---|---|---|---|---|
| QQQ | 09:30 (the open itself) | 749 | 748 | 738 | 0.013% | 3.055% | 199.993% | 29 |
| QQQ | open as read | 749 | 749 | 749 | 0.008% | 0.028% | 0.154% | 0 |
| QQQ | check 10:00 | 749 | 749 | 749 | 0.008% | 0.218% | 0.528% | 9 |
| QQQ | check 10:30 | 749 | 749 | 749 | 0.006% | 0.026% | 0.103% | 0 |
| QQQ | check 11:00 | 749 | 749 | 749 | 0.005% | 0.016% | 0.154% | 0 |
| QQQ | check 11:30 | 749 | 749 | 749 | 0.005% | 0.016% | 0.028% | 0 |
| QQQ | check 12:00 | 749 | 749 | 749 | 0.005% | 0.017% | 0.045% | 0 |
| QQQ | check 12:30 | 749 | 749 | 749 | 0.005% | 0.017% | 0.061% | 0 |
| QQQ | check 13:00 | 749 | 749 | 749 | 0.005% | 0.017% | 0.028% | 0 |
| QQQ | check 13:30 | 749 | 749 | 749 | 0.005% | 0.016% | 0.045% | 0 |
| QQQ | check 14:00 | 749 | 749 | 749 | 0.005% | 0.071% | 0.862% | 5 |
| QQQ | check 14:30 | 749 | 749 | 749 | 0.005% | 0.017% | 0.045% | 0 |
| QQQ | check 15:00 | 749 | 749 | 749 | 0.005% | 0.017% | 0.028% | 0 |
| QQQ | check 15:30 | 749 | 749 | 749 | 0.005% | 0.015% | 0.037% | 0 |
| QQQ | exit 15:50 | 749 | 749 | 749 | 0.011% | 0.088% | 0.237% | 2 |
| SPY | 09:30 (the open itself) | 626 | 607 | 600 | 0.010% | 5.147% | 6.011% | 12 |
| SPY | open as read | 626 | 626 | 626 | 0.005% | 0.014% | 0.024% | 0 |
| SPY | check 10:00 | 626 | 626 | 626 | 0.006% | 0.128% | 0.867% | 4 |
| SPY | check 10:30 | 626 | 626 | 626 | 0.004% | 0.019% | 0.054% | 0 |
| SPY | check 11:00 | 626 | 626 | 626 | 0.004% | 0.014% | 0.025% | 0 |
| SPY | check 11:30 | 626 | 626 | 626 | 0.004% | 0.017% | 0.025% | 0 |
| SPY | check 12:00 | 626 | 626 | 626 | 0.004% | 0.015% | 0.021% | 0 |
| SPY | check 12:30 | 626 | 626 | 626 | 0.004% | 0.017% | 0.027% | 0 |
| SPY | check 13:00 | 626 | 626 | 626 | 0.004% | 0.013% | 0.022% | 0 |
| SPY | check 13:30 | 626 | 626 | 626 | 0.004% | 0.015% | 0.044% | 0 |
| SPY | check 14:00 | 626 | 626 | 626 | 0.004% | 0.050% | 0.217% | 1 |
| SPY | check 14:30 | 626 | 626 | 626 | 0.004% | 0.013% | 0.036% | 0 |
| SPY | check 15:00 | 626 | 626 | 626 | 0.004% | 0.017% | 0.023% | 0 |
| SPY | check 15:30 | 626 | 626 | 626 | 0.004% | 0.015% | 0.032% | 0 |
| SPY | exit 15:50 | 626 | 626 | 626 | 0.006% | 0.049% | 0.075% | 0 |
| IWM | 09:30 (the open itself) | 626 | 599 | 589 | 0.027% | 0.114% | 10.021% | 6 |
| IWM | open as read | 626 | 626 | 626 | 0.013% | 0.029% | 0.046% | 0 |
| IWM | check 10:00 | 626 | 626 | 625 | 0.012% | 1.083% | 3.831% | 24 |
| IWM | check 10:30 | 626 | 626 | 626 | 0.009% | 0.026% | 0.062% | 0 |
| IWM | check 11:00 | 626 | 626 | 626 | 0.009% | 0.018% | 0.028% | 0 |
| IWM | check 11:30 | 626 | 626 | 626 | 0.009% | 0.018% | 0.028% | 0 |
| IWM | check 12:00 | 626 | 626 | 626 | 0.009% | 0.019% | 0.028% | 0 |
| IWM | check 12:30 | 626 | 626 | 626 | 0.009% | 0.018% | 0.028% | 0 |
| IWM | check 13:00 | 626 | 626 | 626 | 0.009% | 0.019% | 0.028% | 0 |
| IWM | check 13:30 | 626 | 626 | 626 | 0.008% | 0.022% | 0.076% | 0 |
| IWM | check 14:00 | 626 | 626 | 626 | 0.008% | 0.086% | 0.498% | 3 |
| IWM | check 14:30 | 626 | 626 | 626 | 0.008% | 0.021% | 0.031% | 0 |
| IWM | check 15:00 | 626 | 626 | 626 | 0.006% | 0.018% | 0.028% | 0 |
| IWM | check 15:30 | 626 | 626 | 626 | 0.006% | 0.015% | 0.022% | 0 |
| IWM | exit 15:50 | 626 | 626 | 626 | 0.011% | 0.522% | 4.261% | 12 |
| NVDA | 09:30 (the open itself) | 626 | 605 | 620 | 0.341% | 4.802% | 7.506% | 461 |
| NVDA | open as read | 626 | 625 | 625 | 0.059% | 0.343% | 1.022% | 29 |
| NVDA | check 10:00 | 626 | 625 | 625 | 0.047% | 0.239% | 0.349% | 12 |
| NVDA | check 10:30 | 626 | 625 | 625 | 0.026% | 0.167% | 0.205% | 1 |
| NVDA | check 11:00 | 626 | 625 | 625 | 0.021% | 0.134% | 0.234% | 1 |
| NVDA | check 11:30 | 626 | 625 | 625 | 0.021% | 0.129% | 0.314% | 4 |
| NVDA | check 12:00 | 626 | 625 | 625 | 0.019% | 0.122% | 0.195% | 0 |
| NVDA | check 12:30 | 626 | 625 | 625 | 0.020% | 0.120% | 0.240% | 2 |
| NVDA | check 13:00 | 626 | 625 | 625 | 0.021% | 0.120% | 0.168% | 0 |
| NVDA | check 13:30 | 626 | 625 | 625 | 0.018% | 0.126% | 0.308% | 3 |
| NVDA | check 14:00 | 626 | 625 | 625 | 0.020% | 0.137% | 0.196% | 0 |
| NVDA | check 14:30 | 626 | 625 | 625 | 0.020% | 0.146% | 0.344% | 1 |
| NVDA | check 15:00 | 626 | 625 | 625 | 0.018% | 0.117% | 0.230% | 1 |
| NVDA | check 15:30 | 626 | 625 | 625 | 0.018% | 0.110% | 0.158% | 0 |
| NVDA | exit 15:50 | 626 | 625 | 625 | 0.024% | 0.129% | 0.303% | 2 |
| TSLA | 09:30 (the open itself) | 626 | 614 | 619 | 0.264% | 2.381% | 5.164% | 403 |
| TSLA | open as read | 626 | 626 | 626 | 0.065% | 0.271% | 0.333% | 21 |
| TSLA | check 10:00 | 626 | 626 | 626 | 0.063% | 0.231% | 0.444% | 15 |
| TSLA | check 10:30 | 626 | 626 | 626 | 0.043% | 0.181% | 0.311% | 4 |
| TSLA | check 11:00 | 626 | 626 | 626 | 0.034% | 0.135% | 0.233% | 1 |
| TSLA | check 11:30 | 626 | 626 | 626 | 0.030% | 0.141% | 0.335% | 3 |
| TSLA | check 12:00 | 626 | 626 | 626 | 0.028% | 0.138% | 0.187% | 0 |
| TSLA | check 12:30 | 626 | 626 | 626 | 0.029% | 0.116% | 0.131% | 0 |
| TSLA | check 13:00 | 626 | 626 | 626 | 0.028% | 0.117% | 0.226% | 1 |
| TSLA | check 13:30 | 626 | 626 | 626 | 0.027% | 0.134% | 0.200% | 0 |
| TSLA | check 14:00 | 626 | 626 | 626 | 0.028% | 0.146% | 0.305% | 4 |
| TSLA | check 14:30 | 626 | 626 | 626 | 0.026% | 0.136% | 0.250% | 2 |
| TSLA | check 15:00 | 626 | 626 | 626 | 0.025% | 0.184% | 0.274% | 4 |
| TSLA | check 15:30 | 626 | 626 | 626 | 0.023% | 0.124% | 0.187% | 0 |
| TSLA | exit 15:50 | 626 | 626 | 626 | 0.033% | 0.185% | 0.352% | 6 |

## Sessions with every quote S3 needs as history

- QQQ: 749 sessions; a usable quote at the open as read and at every check on 749; not on: none
- SPY: 626 sessions; a usable quote at the open as read and at every check on 626; not on: none
- IWM: 626 sessions; a usable quote at the open as read and at every check on 625; not on: 2025-09-26
- NVDA: 626 sessions; a usable quote at the open as read and at every check on 625; not on: 2024-05-28
- TSLA: 626 sessions; a usable quote at the open as read and at every check on 626; not on: none
