"""Final-holdout lock (spec §8, T-WF-03). Sessions after `holdout_after` may only be read by a
registered run with touches_final_holdout = true; every access is logged to
final_test_access_log, and any access after the first needs an approved ADR reference."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import Engine, text


class HoldoutLockedError(PermissionError):
    """Attempt to read final-holdout sessions without an authorised, logged access."""


class HoldoutGuard:
    def __init__(self, holdout_after: date, engine: Engine | None) -> None:
        self.holdout_after = holdout_after
        self.engine = engine

    def check(
        self,
        sessions: Iterable[date],
        *,
        run_id: str | None = None,
        justification: str | None = None,
        adr_ref: str | None = None,
    ) -> None:
        """Return silently if no session is in the holdout; otherwise authorise and log the
        access or raise HoldoutLockedError."""
        touched = sorted(d for d in sessions if d > self.holdout_after)
        if not touched:
            return
        where = f"{len(touched)} final-holdout sessions ({touched[0]}..{touched[-1]})"
        if self.engine is None or run_id is None or not justification:
            raise HoldoutLockedError(
                f"{where} requested without a registered run, justification and database log"
            )
        with self.engine.begin() as c:
            row = c.execute(
                text("SELECT touches_final_holdout FROM validation_runs WHERE run_id = :r"),
                {"r": run_id},
            ).first()
            if row is None or not row[0]:
                raise HoldoutLockedError(
                    f"{where}: run {run_id} is not registered with touches_final_holdout"
                )
            prior = c.execute(text("SELECT count(*) FROM final_test_access_log")).scalar_one()
            if prior > 0 and not adr_ref:
                raise HoldoutLockedError(
                    f"{where}: the final holdout was already accessed {prior} time(s); "
                    "another access requires an approved ADR reference"
                )
            c.execute(
                text("""
                    INSERT INTO final_test_access_log (run_id, justification, adr_ref)
                    VALUES (:r, :j, :a)"""),
                {"r": run_id, "j": justification, "a": adr_ref},
            )
