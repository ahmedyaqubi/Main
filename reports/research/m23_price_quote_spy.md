# M23 Step 0: SPY data-scope price quote (ADR-0014)

Generated 2026-10-09 05:03 UTC by `scripts/m23_price_gap.py`. **Price only: no market data was downloaded.** Prices come from Databento `metadata.get_cost` (free); the listing universe comes from free symbology resolution.

- Sessions 2013-04-01 → 2026-10-02: 3399. The holdout is every session after 2025-10-02 (storage only, D3).
- Universe: 569,158 SPY contracts. Sessions with no previous close in the Cboe file: 0. Symbology chunks with nothing to resolve: 2024-03-29..2024-04-01.
- Sample: every 19th session (179 sessions priced exactly). The total is extrapolated per year (sample mean x sessions in the year).

| year | sessions | sampled | entry symbols (mean) | exit symbols (mean) | $ per session (mean) | estimate $ |
|---|---|---|---|---|---|---|
| 2013 | 192 | 11 | 173 | 18 | 0.0009 | 0.17 |
| 2014 | 252 | 13 | 232 | 17 | 0.0011 | 0.28 |
| 2015 | 252 | 13 | 287 | 35 | 0.0014 | 0.36 |
| 2016 | 252 | 13 | 295 | 14 | 0.0014 | 0.36 |
| 2017 | 251 | 14 | 207 | 91 | 0.0013 | 0.31 |
| 2018 | 251 | 13 | 268 | 98 | 0.0016 | 0.39 |
| 2019 | 252 | 13 | 241 | 93 | 0.0014 | 0.36 |
| 2020 | 253 | 13 | 275 | 120 | 0.0017 | 0.42 |
| 2021 | 252 | 14 | 342 | 79 | 0.0018 | 0.46 |
| 2022 | 251 | 13 | 344 | 124 | 0.0020 | 0.50 |
| 2023 | 250 | 13 | 378 | 176 | 0.0023 | 0.58 |
| 2024 | 252 | 13 | 375 | 127 | 0.0021 | 0.54 |
| 2025 | 250 | 13 | 376 | 172 | 0.0023 | 0.57 |
| 2026 | 189 | 10 | 516 | 240 | 0.0031 | 0.59 |

**Estimated total: $5.90** (cap $50, R8). By part, sample sums: definitions $0.1211, entry quotes $0.1628, exit quotes $0.0262. Unresolved requests in the sample: 0.

Uncertainty: this is an estimate from a 1-in-19 sample. The purchase step prices every request exactly and stops at the cap.

SPY band: previous SPX close / 10 as a storage-scope proxy. SPY's own closes are fetched before any SPY Step 1 (W and labels never use the proxy).
