# M19T Step 1: model-free screen of the defined-risk short-premium family (ADR-0013)

Generated 2026-10-08 22:11 UTC by `scripts/m19t_step1.py`, code 8b86c3504cdc. Registered run `screen_1c-9c607f3c96e7` (n_trials 38 → 39). Development sessions 2020-01-02 → 2026-04-02 only; the holdout was not read.

## Family outcome: **KILL**

Rules (D3):
- **ADVANCE**: one-sided 95% lower bound of the mean net P&L per session at the conservative fill > 0, and no D4 guard applies.
- **KILL**: two-sided 95% upper bound at the mid fill < 0.
- **AMBIGUOUS** otherwise. The family is KILL only if every cell is KILL. AMBIGUOUS means one pre-registered re-screen after ≥ 250 new development sessions, then PARKED.
- Session-block bootstrap: 2000 reps, seed 20261007, one shared draw set over all sessions.

These are development-data results with their uncertainty. They are not a claim of profitability, and nothing here is out-of-sample.

## Decision table

| cell | tenor | structure | X | sessions | from 2023 | trades | mean net/session (cons) | lower bound (cons) | mean (mid) | upper bound (mid) | guards | era-driven | outcome |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | 0dte | put | 0.20 | 1155 | 810 | 11123 | -14.30 | -16.96 | -2.40 | -0.55 | - | no | **KILL** |
| S2 | 0dte | put | 0.33 | 1153 | 810 | 10951 | -24.98 | -28.26 | -2.90 | -0.74 | - | no | **KILL** |
| S3 | 0dte | condor | 0.20 | 1153 | 808 | 11001 | -26.35 | -29.01 | -5.85 | -3.84 | - | no | **KILL** |
| S4 | 1dte | put | 0.20 | 1143 | 799 | 21583 | -19.92 | -23.55 | -3.25 | -1.21 | - | no | **KILL** |
| S5 | 1dte | put | 0.33 | 1142 | 797 | 21512 | -33.65 | -38.22 | -3.68 | -1.23 | - | no | **KILL** |
| S6 | 1dte | condor | 0.20 | 1115 | 779 | 20937 | -36.29 | -40.40 | -7.71 | -5.38 | - | no | **KILL** |

## D4 columns (pooled, per cell)

Dollars per 1-lot position. *Mean net*: mean over sessions of each session's mean trade, with a 95% bootstrap CI. *Loss share*: losing trades at the conservative fill. *Break-even loss share*: mean win ÷ (mean win + mean loss) on the same trades. *DD*: maximum drawdown of cumulative session means, in $ and in units of mean max risk.

| cell | conservative [95% CI] | moderate [95% CI] | mid [95% CI] | median | loss share | break-even loss share | X | worst 5% | max losing run | DD $ | DD / max risk | net per $ risk | NO_TRADE | §4.9 rejected | UNRESOLVED | EXCLUDED |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | -14.30 [-17.48, -11.19] | -8.97 [-11.47, -6.54] | -2.40 [-4.21, -0.55] | 15.80 | 0.329 | 0.186 | 0.20 | -180.27 | 6 | 16575.18 | 212.44 | -0.1833 | 4.0% | 3.7% | 0.4% | - |
| S2 | -24.98 [-29.15, -21.03] | -14.79 [-17.94, -11.83] | -2.90 [-5.16, -0.74] | 6.42 | 0.446 | 0.239 | 0.33 | -226.13 | 8 | 28893.08 | 451.15 | -0.3900 | 5.4% | 4.6% | 0.5% | - |
| S3 | -26.35 [-29.52, -22.95] | -17.27 [-19.62, -14.62] | -5.85 [-7.56, -3.84] | -12.23 | 0.553 | 0.280 | 0.20 | -180.72 | 14 | 30382.24 | 552.89 | -0.4795 | 4.8% | 4.4% | 0.7% | - |
| S4 | -19.92 [-24.26, -15.90] | -12.25 [-15.43, -9.30] | -3.25 [-5.45, -1.21] | 17.09 | 0.291 | 0.135 | 0.20 | -258.01 | 6 | 22796.82 | 284.54 | -0.2486 | 0.6% | 0.5% | 1.0% | EXIT_SESSION_EXCLUDED 19, LABEL_CROSSES_BLOCK 19 |
| S5 | -33.65 [-39.01, -28.60] | -19.56 [-23.56, -15.92] | -3.68 [-6.21, -1.23] | 17.88 | 0.427 | 0.199 | 0.33 | -308.06 | 11 | 38428.72 | 580.66 | -0.5085 | 0.8% | 0.5% | 1.1% | EXIT_SESSION_EXCLUDED 19, LABEL_CROSSES_BLOCK 19 |
| S6 | -36.29 [-41.11, -31.68] | -23.26 [-26.74, -19.91] | -7.71 [-10.09, -5.38] | -12.55 | 0.525 | 0.242 | 0.20 | -272.99 | 8 | 40507.65 | 684.13 | -0.6129 | 0.8% | 0.6% | 2.0% | EXIT_SESSION_EXCLUDED 19, EX_DIV_SPAN 379, LABEL_CROSSES_BLOCK 19 |

## Rows by era, weekday and descriptive groups (point estimates; never decisions)

| cell | rows | sessions | trades | mean cons | mean moderate | mean mid | loss share | break-even loss share |
|---|---|---|---|---|---|---|---|---|
| S1 | era 1 Friday-only | 70 | 631 | -15.45 | -9.99 | -2.55 | 0.347 | 0.195 |
| S1 | era 2 Mon/Wed/Fri | 245 | 2268 | -20.70 | -12.99 | -3.46 | 0.386 | 0.190 |
| S1 | era 3 daily | 840 | 8224 | -12.34 | -7.71 | -2.08 | 0.311 | 0.184 |
| S1 | weekday Mon | 229 | 2207 | -9.39 | -4.66 | 1.20 | 0.284 | 0.199 |
| S1 | weekday Tue | 184 | 1792 | -8.58 | -4.46 | 0.58 | 0.278 | 0.191 |
| S1 | weekday Wed | 253 | 2426 | -14.41 | -9.24 | -2.75 | 0.353 | 0.199 |
| S1 | weekday Thu | 178 | 1755 | -20.10 | -13.76 | -6.23 | 0.364 | 0.168 |
| S1 | weekday Fri | 311 | 2943 | -17.91 | -11.85 | -4.34 | 0.351 | 0.175 |
| S1 | without VENDOR_DEGRADED days (R4) | 1153 | 11103 | -14.35 | -9.01 | -2.43 | 0.329 | 0.185 |
| S2 | era 1 Friday-only | 69 | 587 | -24.72 | -15.09 | -3.41 | 0.468 | 0.244 |
| S2 | era 2 Mon/Wed/Fri | 244 | 2207 | -34.52 | -20.43 | -4.28 | 0.496 | 0.232 |
| S2 | era 3 daily | 840 | 8157 | -22.23 | -13.13 | -2.45 | 0.431 | 0.242 |
| S2 | weekday Mon | 229 | 2180 | -19.37 | -10.39 | 0.19 | 0.425 | 0.259 |
| S2 | weekday Tue | 184 | 1767 | -16.58 | -8.35 | 1.40 | 0.389 | 0.247 |
| S2 | weekday Wed | 252 | 2389 | -25.48 | -15.34 | -3.41 | 0.457 | 0.240 |
| S2 | weekday Thu | 178 | 1736 | -31.39 | -19.74 | -6.44 | 0.486 | 0.230 |
| S2 | weekday Fri | 310 | 2879 | -30.01 | -18.58 | -5.28 | 0.465 | 0.227 |
| S2 | without VENDOR_DEGRADED days (R4) | 1151 | 10931 | -25.02 | -14.82 | -2.91 | 0.447 | 0.239 |
| S3 | era 1 Friday-only | 70 | 618 | -29.56 | -19.42 | -5.40 | 0.634 | 0.278 |
| S3 | era 2 Mon/Wed/Fri | 245 | 2222 | -41.11 | -26.18 | -7.73 | 0.634 | 0.252 |
| S3 | era 3 daily | 838 | 8161 | -21.77 | -14.49 | -5.34 | 0.525 | 0.288 |
| S3 | weekday Mon | 229 | 2180 | -25.11 | -15.55 | -3.75 | 0.540 | 0.295 |
| S3 | weekday Tue | 184 | 1784 | -21.60 | -14.82 | -6.21 | 0.521 | 0.283 |
| S3 | weekday Wed | 253 | 2406 | -29.67 | -19.48 | -6.80 | 0.585 | 0.277 |
| S3 | weekday Thu | 177 | 1731 | -27.54 | -19.20 | -8.77 | 0.572 | 0.272 |
| S3 | weekday Fri | 310 | 2900 | -26.70 | -17.09 | -4.75 | 0.543 | 0.275 |
| S3 | without VENDOR_DEGRADED days (R4) | 1151 | 10981 | -26.41 | -17.32 | -5.89 | 0.553 | 0.280 |
| S4 | era 1 Friday-only | 74 | 1380 | -14.56 | -8.17 | 0.08 | 0.284 | 0.160 |
| S4 | era 2 Mon/Wed/Fri | 241 | 4564 | -25.09 | -15.99 | -5.04 | 0.331 | 0.136 |
| S4 | era 3 daily | 828 | 15639 | -18.89 | -11.52 | -3.02 | 0.280 | 0.133 |
| S4 | weekday Mon | 158 | 2992 | -15.22 | -9.68 | -3.15 | 0.290 | 0.154 |
| S4 | weekday Tue | 252 | 4783 | -11.91 | -6.65 | -0.03 | 0.263 | 0.154 |
| S4 | weekday Wed | 183 | 3402 | -29.20 | -19.33 | -8.16 | 0.359 | 0.132 |
| S4 | weekday Thu | 306 | 5783 | -25.42 | -16.28 | -5.67 | 0.312 | 0.126 |
| S4 | weekday Fri | 244 | 4623 | -17.36 | -9.31 | 0.08 | 0.244 | 0.123 |
| S4 | without VENDOR_DEGRADED days (R4) | 1142 | 21564 | -19.95 | -12.27 | -3.27 | 0.291 | 0.135 |
| S4 | descriptive: Fri->Mon | 216 | 4097 | -13.98 | -7.12 | 1.05 | 0.230 | 0.128 |
| S4 | descriptive: pre-holiday | 44 | 826 | -43.90 | -27.96 | -10.44 | 0.390 | 0.112 |
| S5 | era 1 Friday-only | 75 | 1373 | -33.32 | -20.12 | -4.91 | 0.480 | 0.233 |
| S5 | era 2 Mon/Wed/Fri | 241 | 4514 | -39.31 | -24.00 | -6.63 | 0.491 | 0.209 |
| S5 | era 3 daily | 826 | 15625 | -32.03 | -18.21 | -2.70 | 0.404 | 0.192 |
| S5 | weekday Mon | 156 | 2964 | -31.51 | -17.81 | -2.50 | 0.398 | 0.192 |
| S5 | weekday Tue | 252 | 4756 | -23.37 | -12.68 | -0.17 | 0.418 | 0.228 |
| S5 | weekday Wed | 183 | 3407 | -46.81 | -28.37 | -8.20 | 0.457 | 0.177 |
| S5 | weekday Thu | 307 | 5776 | -39.80 | -24.61 | -7.53 | 0.460 | 0.196 |
| S5 | weekday Fri | 244 | 4609 | -28.03 | -14.82 | 0.18 | 0.393 | 0.202 |
| S5 | without VENDOR_DEGRADED days (R4) | 1141 | 21493 | -33.71 | -19.60 | -3.71 | 0.428 | 0.199 |
| S5 | descriptive: Fri->Mon | 216 | 4081 | -24.66 | -12.52 | 1.40 | 0.373 | 0.203 |
| S5 | descriptive: pre-holiday | 44 | 828 | -58.77 | -37.29 | -13.94 | 0.558 | 0.188 |
| S6 | era 1 Friday-only | 74 | 1362 | -23.46 | -13.38 | 0.28 | 0.487 | 0.271 |
| S6 | era 2 Mon/Wed/Fri | 234 | 4424 | -45.66 | -29.45 | -9.65 | 0.591 | 0.238 |
| S6 | era 3 daily | 807 | 15151 | -34.75 | -22.37 | -7.87 | 0.509 | 0.242 |
| S6 | weekday Mon | 155 | 2943 | -29.11 | -19.47 | -7.86 | 0.526 | 0.264 |
| S6 | weekday Tue | 251 | 4748 | -33.06 | -21.19 | -6.67 | 0.507 | 0.237 |
| S6 | weekday Wed | 182 | 3318 | -49.31 | -33.22 | -14.73 | 0.605 | 0.237 |
| S6 | weekday Thu | 303 | 5697 | -34.38 | -22.03 | -6.97 | 0.510 | 0.239 |
| S6 | weekday Fri | 224 | 4231 | -36.88 | -21.76 | -4.04 | 0.503 | 0.239 |
| S6 | without VENDOR_DEGRADED days (R4) | 1114 | 20918 | -36.35 | -23.31 | -7.75 | 0.526 | 0.242 |
| S6 | descriptive: Fri->Mon | 198 | 3743 | -33.42 | -20.09 | -4.20 | 0.506 | 0.250 |
| S6 | descriptive: pre-holiday | 42 | 787 | -56.79 | -33.17 | -6.77 | 0.531 | 0.202 |

