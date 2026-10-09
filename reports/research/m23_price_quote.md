# M23 Step 0: SPX data-scope price quote (ADR-0014)

Generated 2026-10-09 03:17 UTC by `scripts/m23_price_gap.py`. **Price only: no market data was downloaded.** Prices come from Databento `metadata.get_cost` (free); the listing universe comes from free symbology resolution.

- Sessions 2013-04-01 → 2026-10-02: 3399. The holdout is every session after 2025-10-02 (storage only, D3).
- Universe: 1,050,018 SPX/SPXW contracts. Sessions with no previous close in the Cboe file: 0. Symbology chunks with nothing to resolve (this run): none.
- Sample: every 19th session (179 sessions priced exactly). The total is extrapolated per year (sample mean x sessions in the year).

| year | sessions | sampled | entry symbols (mean) | exit symbols (mean) | $ per session (mean) | estimate $ |
|---|---|---|---|---|---|---|
| 2013 | 192 | 11 | 283 | 15 | 0.0014 | 0.26 |
| 2014 | 252 | 13 | 359 | 34 | 0.0018 | 0.44 |
| 2015 | 252 | 13 | 417 | 45 | 0.0021 | 0.53 |
| 2016 | 252 | 13 | 393 | 64 | 0.0020 | 0.51 |
| 2017 | 251 | 14 | 391 | 175 | 0.0024 | 0.60 |
| 2018 | 251 | 13 | 591 | 218 | 0.0034 | 0.86 |
| 2019 | 252 | 13 | 519 | 162 | 0.0029 | 0.74 |
| 2020 | 253 | 13 | 556 | 288 | 0.0035 | 0.89 |
| 2021 | 252 | 14 | 669 | 145 | 0.0036 | 0.90 |
| 2022 | 251 | 13 | 541 | 223 | 0.0032 | 0.81 |
| 2023 | 250 | 13 | 590 | 376 | 0.0039 | 0.98 |
| 2024 | 252 | 13 | 673 | 348 | 0.0042 | 1.07 |
| 2025 | 250 | 13 | 596 | 336 | 0.0038 | 0.94 |
| 2026 | 189 | 10 | 880 | 411 | 0.0054 | 1.01 |

**Estimated total: $10.54** (cap $50, R8). By part, sample sums: definitions $0.2190, entry quotes $0.2817, exit quotes $0.0529. Unresolved requests in the sample: 0.

Uncertainty: this is an estimate from a 1-in-19 sample. The purchase step prices every request exactly and stops at the cap.
