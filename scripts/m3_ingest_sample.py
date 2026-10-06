"""M3 acceptance evidence: ingest the M2 sample week into the raw store, twice.

The second pass must change nothing (idempotency). Datasets are registered in
`dataset_versions` when DATABASE_URL is set (in .env); otherwise the report says so.
Tick files (cmbp-1) are excluded: M2 decided the research store uses 1-minute NBBO.

Usage: uv run python scripts/m3_ingest_sample.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.core.config import config_hash, load_config
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.ingestion.databento_raw import IngestResult, RawStore, compute_dataset_id, ingest_file

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "raw" / "databento" / "m2_sample"
STORE = RawStore(ROOT / "data" / "raw")
REPORT = ROOT / "reports" / "m3" / "ingest_sample.md"
EXCLUDED_SCHEMAS = {"cmbp-1"}


def kind_for(vendor_dataset: str) -> str:
    return "raw_options_data" if vendor_dataset == "OPRA.PILLAR" else "raw_market_data"


def code_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        return out.stdout.strip() + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def sample_files() -> list[Path]:
    return sorted(p for p in SAMPLE.rglob("*.dbn.zst") if p.parent.name not in EXCLUDED_SCHEMAS)


def ingest_all(now: datetime) -> list[IngestResult]:
    return [ingest_file(p, STORE, now=now) for p in sample_files()]


def main() -> int:
    load_dotenv(ROOT / ".env")
    files = sample_files()
    if not files:
        print(f"no sample files under {SAMPLE}; run scripts/m2_fetch_sample.py first")
        return 1

    first = ingest_all(datetime.now(UTC))
    second = ingest_all(datetime.now(UTC))

    groups: dict[tuple[str, str], list[IngestResult]] = defaultdict(list)
    for r in first:
        groups[(r.vendor_dataset, r.schema)].append(r)

    cfg_hash = config_hash(load_config().model_dump(mode="json"))
    commit = code_commit()
    versions: list[DatasetVersion] = []
    for (vds, schema), results in sorted(groups.items()):
        ids = [r.raw_file_id for r in results]
        versions.append(
            DatasetVersion(
                dataset_id=compute_dataset_id(kind_for(vds), vds, schema, ids),
                kind=kind_for(vds),
                source="databento",
                coverage_start=min(r.partition_date for r in results),
                coverage_end=max(r.partition_date for r in results),
                row_count=sum(r.rows for r in results),
                storage_uri=f"data/raw/parquet/{vds}/{schema}",
                code_commit=commit,
                config_hash=cfg_hash,
            )
        )

    # Idempotency evidence: second pass found everything present with identical ids/rows.
    same_ids = [a.raw_file_id for a in first] == [b.raw_file_id for b in second]
    same_rows = [a.rows for a in first] == [b.rows for b in second]
    all_present = all(b.already_present for b in second)
    ids_again = {
        compute_dataset_id(kind_for(v), v, s, [r.raw_file_id for r in rs])
        for (v, s), rs in groups.items()
    }
    dataset_ids_stable = ids_again == {dv.dataset_id for dv in versions}

    db_note: str
    url = os.environ.get("DATABASE_URL")
    if url:
        engine = create_engine(url)
        new = [record_dataset(engine, dv) for dv in versions]
        again = [record_dataset(engine, dv) for dv in versions]
        engine.dispose()
        db_note = (
            f"Registered in `dataset_versions`: {sum(new)} new, {len(new) - sum(new)} already "
            f"present; a second registration wrote {sum(again)} rows (expected 0)."
        )
    else:
        db_note = "DATABASE_URL not set: `dataset_versions` registration not run."

    lines = [
        "# M3 sample ingestion report",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m3_ingest_sample.py` "
        f"(code {commit[:12]}). Source: M2 sample week, {len(files)} DBN files "
        f"(tick `cmbp-1` excluded by design).",
        "",
        "| vendor dataset | schema | kind | files | rows | coverage | dataset_id |",
        "|---|---|---|---|---|---|---|",
    ]
    for dv, ((vds, schema), results) in zip(versions, sorted(groups.items()), strict=True):
        lines.append(
            f"| {vds} | {schema} | {dv.kind} | {len(results)} | {dv.row_count:,} "
            f"| {dv.coverage_start} → {dv.coverage_end} | `{dv.dataset_id[:16]}…` |"
        )
    lines += [
        "",
        "## Idempotency (second ingestion pass)",
        "",
        f"- every file already present on the second pass: **{all_present}**",
        f"- identical `raw_file_id`s: **{same_ids}**; identical row counts: **{same_rows}**",
        f"- identical `dataset_id`s recomputed: **{dataset_ids_stable}**",
        f"- Parquet files on disk: {len(list((STORE.root / 'parquet').rglob('*.parquet')))} "
        f"for {len(files)} source files",
        "",
        "## Catalogue",
        "",
        db_note,
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT.relative_to(ROOT)}")
    ok = all_present and same_ids and same_rows and dataset_ids_stable
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
