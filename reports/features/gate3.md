# Gate 3 — point-in-time integrity of feature snapshots

Generated 2026-10-07 02:05 UTC; feature_version f2.

**Result: PASS**

- Rows checked: 1,572,480 (all stored rows, not a sample)
- Rows with available_at > prediction_ts: **0**
- Rows with null available_at (missing values): 43,679
- Replay of 20 random timestamps (seed 7) from inputs holding the full history, i.e. including data after T: all identical

| session | timestamp (ET) | features | identical |
|---|---|---|---|
| 2023-05-22 | 10:40 | 28 | yes |
| 2023-06-07 | 14:15 | 28 | yes |
| 2023-06-22 | 10:20 | 28 | yes |
| 2023-07-11 | 11:00 | 28 | yes |
| 2023-07-14 | 12:05 | 28 | yes |
| 2023-08-03 | 10:20 | 28 | yes |
| 2023-08-15 | 13:55 | 28 | yes |
| 2023-11-06 | 10:15 | 28 | yes |
| 2024-02-12 | 12:05 | 28 | yes |
| 2024-03-21 | 10:10 | 28 | yes |
| 2024-07-24 | 11:10 | 28 | yes |
| 2024-09-24 | 12:50 | 28 | yes |
| 2024-11-05 | 14:10 | 28 | yes |
| 2024-12-10 | 11:15 | 28 | yes |
| 2025-01-03 | 11:00 | 28 | yes |
| 2025-04-24 | 13:00 | 28 | yes |
| 2025-06-05 | 11:40 | 28 | yes |
| 2025-08-14 | 10:50 | 28 | yes |
| 2025-11-21 | 11:45 | 28 | yes |
| 2026-08-05 | 13:40 | 28 | yes |
