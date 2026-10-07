# ADR-0008 — Shuffled-label canary: average per-fold AUC over repeated permutations

- Status: **ACCEPTED** (owner, 2026-10-07, option "A")
- Date: 2026-10-07
- Milestone: M9 (criterion 3, T-LEAK-13)
- Amends: PHASE_1_SPEC §11 gate 4 (how "OOS AUC" of the time-shuffled-label model is computed)
- Supersedes: M9 owner decision Q6 (single permutation, AUC of scores pooled across folds)

## Context
Gate 4 requires a model trained on shuffled labels to give OOS AUC within 0.50 ± 0.02. M9 Q6
implemented it as one row-level permutation of the training (and calibration) labels per fold
and target, with AUC computed on test scores pooled across all 7 folds. Run
`canary-541beb1db5f4` (2026-10-07, kept in `validation_runs`) failed for three targets, all
**below** 0.5: B_dn 0.25% 0.448, B_up 0.50% 0.438, B_dn 0.50% 0.444 (others 0.491–0.517).

Diagnosis (recorded in `docs/MILESTONES.md`, M9 note 1):
- Leakage of test labels into training raises AUC; it cannot produce AUC systematically below 0.5.
- The mean of per-fold canary AUCs is 0.484–0.510 for every target. Pooling scores across folds
  mixes fold-level base rates: each canary model mostly predicts its own training base rate, and
  B base rates mean-revert between training and test blocks, so the pooled AUC is pushed below 0.5
  by the pooling, not by the model.
- One permutation is one noisy draw. When the features strongly predict the target (B), a random
  function of the features has a wide AUC spread (per-fold SD up to 0.07).

This change is made **after** seeing a failed canary. That is disclosed here; the failed run stays
recorded, and the tolerance (± 0.02) is not loosened.

## Decision
- Canary statistic = mean over `models.gbm.canary_n_permutations` (= 20) independent row-level
  permutations (seeded from `canary_seed`) of the **mean of per-fold OOS AUCs** (AUC computed on
  each fold's test block against the true labels; no pooling of scores across folds).
- Each permutation refits the fold's selected grid point on permuted training labels, with early
  stopping on permuted calibration labels, exactly as before.
- Pass if |statistic − 0.50| ≤ `canary_auc_tolerance` (0.02, unchanged) for every target.
- The report also shows the spread across permutations (SD, min, max of the per-permutation
  means) and the per-fold AUCs averaged over permutations.
- The canary is registered as a new `canary` run (new config hash). Grid and OOS run
  configurations are unchanged; `canary_n_permutations` is part of the canary run config only.

## Consequences
- The canary now tests what it is meant to test (does the pipeline find signal where none can
  exist?) without the cross-fold base-rate artefact, and with a far less noisy estimate.
- Compute cost: 20 × 70 extra LightGBM fits (small; early stopping ends most of them quickly).
- A future model family (M13 onward) reuses this statistic. Changing it again needs a new ADR.
