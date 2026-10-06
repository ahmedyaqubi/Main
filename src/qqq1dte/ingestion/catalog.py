"""Dataset catalogue: one `dataset_versions` row per immutable dataset (docs/SCHEMA.md §B)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Engine, text


class DatasetConflictError(RuntimeError):
    """The same dataset_id was registered with different content: a hashing bug or tampering."""


@dataclass(frozen=True)
class DatasetVersion:
    dataset_id: str
    kind: str
    source: str
    coverage_start: date
    coverage_end: date
    row_count: int
    storage_uri: str
    code_commit: str
    config_hash: str
    parent_ids: list[str] = field(default_factory=list)


# Fields that define the dataset's content. code_commit and created_at are provenance of the
# first registration and may legitimately differ on a re-run.
_CONTENT_FIELDS = (
    "kind",
    "source",
    "coverage_start",
    "coverage_end",
    "row_count",
    "storage_uri",
    "config_hash",
)


def record_dataset(engine: Engine, dv: DatasetVersion) -> bool:
    """Insert dv; return False (no write) if an identical dataset_id is already registered."""
    with engine.begin() as c:
        inserted = c.execute(
            text("""
                INSERT INTO dataset_versions (dataset_id, kind, parent_ids, source,
                  coverage_start, coverage_end, row_count, storage_uri, code_commit, config_hash)
                VALUES (:dataset_id, :kind, :parent_ids, :source, :coverage_start,
                  :coverage_end, :row_count, :storage_uri, :code_commit, :config_hash)
                ON CONFLICT (dataset_id) DO NOTHING
                RETURNING dataset_id"""),
            {**dv.__dict__},
        ).first()
        if inserted is not None:
            return True
        row = (
            c.execute(
                text(
                    f"SELECT {', '.join(_CONTENT_FIELDS)}, parent_ids FROM dataset_versions "
                    "WHERE dataset_id = :d"
                ),
                {"d": dv.dataset_id},
            )
            .mappings()
            .one()
        )
    stored = {k: row[k] for k in _CONTENT_FIELDS}
    given = {k: getattr(dv, k) for k in _CONTENT_FIELDS}
    if stored != given or sorted(row["parent_ids"]) != sorted(dv.parent_ids):
        raise DatasetConflictError(
            f"dataset_id {dv.dataset_id} already registered with different content: "
            f"stored={stored} given={given}"
        )
    return False
