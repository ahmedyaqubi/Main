# M3 sample ingestion report

Generated 2026-10-06 08:15 UTC by `scripts/m3_ingest_sample.py` (code aa4eccb14076). Source: M2 sample week, 40 DBN files (tick `cmbp-1` excluded by design).

| vendor dataset | schema | kind | files | rows | coverage | dataset_id |
|---|---|---|---|---|---|---|
| EQUS.MINI | bbo-1m | raw_market_data | 5 | 3,986 | 2025-03-10 → 2025-03-14 | `f2740f87bbea4fd0…` |
| EQUS.MINI | ohlcv-1m | raw_market_data | 5 | 3,073 | 2025-03-10 → 2025-03-14 | `324e7161b0cb12b6…` |
| OPRA.PILLAR | cbbo-1m | raw_options_data | 5 | 844,452 | 2025-03-10 → 2025-03-14 | `7c00c4ca03a044cc…` |
| OPRA.PILLAR | definition | raw_options_data | 20 | 9,086 | 2025-02-24 → 2025-03-14 | `c101f5799ccdb0f5…` |
| OPRA.PILLAR | statistics | raw_options_data | 5 | 192,712 | 2025-03-10 → 2025-03-14 | `2223748f3bce5643…` |

## Idempotency (second ingestion pass)

- every file already present on the second pass: **True**
- identical `raw_file_id`s: **True**; identical row counts: **True**
- identical `dataset_id`s recomputed: **True**
- Parquet files on disk: 40 for 40 source files

## Catalogue

Registered in `dataset_versions`: 5 new, 0 already present; a second registration wrote 0 rows (expected 0).
