"""DQ report numbers and markdown rendering (reports/dq/)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import polars as pl

from qqq1dte.validation.gates import GateResult
from qqq1dte.validation.records import CleanResult

TIMESTAMP_CHECKS = ("TS_AFTER_INGEST", "TS_EVENT_AFTER_RECV")


@dataclass(frozen=True)
class DatasetCounts:
    name: str
    raw: int
    cleaned: int
    rejected: int
    flagged: int
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    flagged_by_flag: dict[str, int] = field(default_factory=dict)
    sessions: int = 0
    timestamp_errors: int = 0

    @property
    def conserved(self) -> bool:
        return self.raw == self.cleaned + self.rejected


def summarize_dataset(name: str, raw: pl.DataFrame, res: CleanResult) -> DatasetCounts:
    reasons = Counter(r for rs in res.rejected["dq_reasons"].to_list() for r in rs)
    flags = Counter(f for fs in res.cleaned["dq_flags"].to_list() for f in fs)
    sessions = pl.concat([res.cleaned.select("session_date"), res.rejected.select("session_date")])[
        "session_date"
    ].n_unique()
    return DatasetCounts(
        name=name,
        raw=raw.height,
        cleaned=res.cleaned.height,
        rejected=res.rejected.height,
        flagged=int((res.cleaned["dq_status"] == "FLAGGED").sum()),
        rejected_by_reason=dict(sorted(reasons.items())),
        flagged_by_flag=dict(sorted(flags.items())),
        sessions=sessions,
        timestamp_errors=sum(reasons.get(c, 0) for c in TIMESTAMP_CHECKS),
    )


def merge_counts(name: str, parts: list[DatasetCounts]) -> DatasetCounts:
    rej: Counter[str] = Counter()
    fl: Counter[str] = Counter()
    for p in parts:
        rej.update(p.rejected_by_reason)
        fl.update(p.flagged_by_flag)
    return DatasetCounts(
        name=name,
        raw=sum(p.raw for p in parts),
        cleaned=sum(p.cleaned for p in parts),
        rejected=sum(p.rejected for p in parts),
        flagged=sum(p.flagged for p in parts),
        rejected_by_reason=dict(sorted(rej.items())),
        flagged_by_flag=dict(sorted(fl.items())),
        sessions=sum(p.sessions for p in parts),
        timestamp_errors=sum(p.timestamp_errors for p in parts),
    )


def render_report(
    datasets: list[DatasetCounts],
    bar_cov: pl.DataFrame | None,
    chain_cov: pl.DataFrame | None,
    gates: list[GateResult],
    title: str,
    extra: list[str] | None = None,
    min_bar_coverage: float = 0.98,
) -> str:
    lines = [f"# {title}", ""]
    lines += [
        "## Datasets",
        "",
        "| dataset | raw | cleaned | rejected | flagged | sessions | timestamp errors "
        "| conservation |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for d in datasets:
        cons = "conservation OK" if d.conserved else "**CONSERVATION FAILED**"
        lines.append(
            f"| {d.name} | {d.raw} | {d.cleaned} | {d.rejected} | {d.flagged} "
            f"| {d.sessions} | {d.timestamp_errors} | {cons} |"
        )
    lines += [
        "",
        "### Rejections and flags by check",
        "",
        "| dataset | check | kind | rows |",
        "|---|---|---|---|",
    ]
    for d in datasets:
        for k, v in d.rejected_by_reason.items():
            lines.append(f"| {d.name} | {k} | rejected | {v} |")
        for k, v in d.flagged_by_flag.items():
            lines.append(f"| {d.name} | {k} | flagged | {v} |")
    if bar_cov is not None and bar_cov.height:
        exp, rec = int(bar_cov["expected"].sum()), int(bar_cov["received"].sum())
        lines += [
            "",
            "## Underlying bars (QQQ, RTH)",
            "",
            f"Sessions {bar_cov.height}; bars expected {exp:,}, received {rec:,}; "
            f"missing {exp - rec:,} ({(exp - rec) / exp:.4%}). Sessions below threshold: "
            f"{int((bar_cov['coverage'] < min_bar_coverage).sum())}.",
            "",
        ]
    if chain_cov is not None and chain_cov.height:
        lines += [
            "## Options chain coverage (frozen-rule call and put at prediction timestamps)",
            "",
            f"Sessions {chain_cov.height}; timestamps {int(chain_cov['n_timestamps'].sum()):,}; "
            f"valid {int(chain_cov['n_valid'].sum()):,}; no spot "
            f"{int(chain_cov['no_spot'].sum()):,}; call invalid "
            f"{int(chain_cov['call_invalid'].sum()):,}; put invalid "
            f"{int(chain_cov['put_invalid'].sum()):,}.",
            "",
        ]
    if gates:
        lines += [
            "## Gates",
            "",
            "| gate | name | result | numbers | rule |",
            "|---|---|---|---|---|",
        ]
        for g in gates:
            nums = "; ".join(
                f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in g.numbers.items()
            )
            lines.append(
                f"| {g.gate} | {g.name} | {'PASS' if g.passed else '**FAIL**'} | {nums} "
                f"| {g.rule} |"
            )
    if extra:
        lines += ["", *extra]
    return "\n".join(lines) + "\n"
