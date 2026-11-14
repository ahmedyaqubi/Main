# M28 step 5: data price quote, SPY / IWM / NVDA / TSLA / AAPL (ADR-0021 D7)

Generated 2026-11-14 10:05 UTC by `scripts/m28_price_data.py`. **Price only: no market data was downloaded.** Every request priced exactly with Databento `metadata.get_cost`; scope in `configs/m28_data.yaml`.

Development 2023-03-28 → 2025-10-02; holdout storage 2025-10-03 → 2026-10-02.

| ticker | part | cbbo-1m | definition | underlying bbo-1m | underlying ohlcv-1m | total |
|---|---|---|---|---|---|---|
| SPY | dev | $0.8497 | $0.0240 | $0.1324 | $0.2146 | **$1.22** |
| SPY | holdout | $0.3832 | $0.0108 | $0.0559 | $0.0710 | **$0.52** |
| IWM | dev | $0.6996 | $0.0198 | $0.1321 | $0.1829 | **$1.03** |
| IWM | holdout | $0.3035 | $0.0086 | $0.0525 | $0.0674 | **$0.43** |
| NVDA | dev | $0.8054 | $0.0233 | $0.1315 | $0.2464 | **$1.21** |
| NVDA | holdout | $0.2438 | $0.0070 | $0.0455 | $0.0787 | **$0.38** |
| TSLA | dev | $0.7713 | $0.0223 | $0.1350 | $0.2494 | **$1.18** |
| TSLA | holdout | $0.3421 | $0.0099 | $0.0399 | $0.0730 | **$0.46** |
| AAPL | dev | $0.5512 | $0.0160 | $0.1118 | $0.1970 | **$0.88** |
| AAPL | holdout | $0.2431 | $0.0070 | $0.0349 | $0.0672 | **$0.35** |

**Development total: $5.52. Holdout storage total: $2.15. Both: $7.66.** Budget left (D7): $71.49.

| ticker | mean symbols per session | sessions with no Tiingo row | sessions with no D2 expiry |
|---|---|---|---|
| SPY | 23.6 | 0  | 0  |
| IWM | 19.2 | 0  | 0  |
| NVDA | 20.6 | 0  | 0  |
| TSLA | 21.8 | 0  | 0  |
| AAPL | 15.5 | 0  | 0  |

