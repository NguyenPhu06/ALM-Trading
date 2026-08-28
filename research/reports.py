"""Research report generation (section 24).

Every study writes two files: a JSON one for machines and a Markdown one for
people. They are generated from the same payload, so the prose can never drift
from the numbers.

Reports live under `reports/research/` and are gitignored — a report is an
output of a dataset, not source code, and committing them would invite reading a
stale one as current.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

DEFAULT_DIRECTORY = Path("reports") / "research"

# Section 24's filenames, mapped to the study that fills each one.
REPORT_FILES: tuple[str, ...] = (
    "strategy_comparison", "regime_analysis", "session_analysis", "timeframe_analysis",
    "nn_value_analysis", "ablation_analysis", "dca_analysis", "time_exit_analysis",
    "champion_challenger", "liquidity_event_analysis", "signal_conflicts",
    "multiple_testing", "error_lab",
)

HEADER_NOTE = (
    "Forward-observation research. Not a backtest, not executed results, and not "
    "a recommendation to trade. Every figure is net of spread, commission, "
    "slippage and swap."
)


@dataclass(frozen=True, slots=True)
class ReportBundle:
    name: str
    payload: dict[str, Any]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def json_name(self) -> str:
        return f"{self.name}.json"

    @property
    def markdown_name(self) -> str:
        return f"{self.name}.md"

    def as_dict(self) -> dict[str, Any]:
        return {"report": self.name,
                "generated_at": self.generated_at.isoformat(),
                "evidence": "FORWARD_OBSERVATION",
                "note": HEADER_NOTE,
                # Research produces documents; it never places anything.
                "orders_sent": 0,
                **self.payload}


class ResearchReporter:
    def __init__(self, directory: str | Path = DEFAULT_DIRECTORY):
        self.directory = Path(directory)

    def build(self, name: str, payload: Mapping[str, Any]) -> ReportBundle:
        if name not in REPORT_FILES:
            # Unknown names are allowed but recorded, so a typo is visible in the
            # output directory rather than silently producing a stray file.
            payload = {**payload, "unregistered_report": True}
        return ReportBundle(name, dict(payload))

    def write(self, bundle: ReportBundle) -> dict[str, Path]:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = bundle.as_dict()

        json_path = self.directory / bundle.json_name
        json_path.write_text(json.dumps(payload, indent=2, default=str, sort_keys=True),
                             encoding="utf-8")

        markdown_path = self.directory / bundle.markdown_name
        markdown_path.write_text(render_markdown(bundle.name, payload), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    def generate(self, reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        written: dict[str, Any] = {}
        for name, payload in reports.items():
            paths = self.write(self.build(name, payload))
            written[name] = {kind: str(path) for kind, path in paths.items()}
        index = {"generated_at": datetime.now(timezone.utc).isoformat(),
                 "reports": written, "note": HEADER_NOTE, "orders_sent": 0}
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "index.json").write_text(
            json.dumps(index, indent=2, default=str, sort_keys=True), encoding="utf-8")
        return index


# ------------------------------------------------------------------ rendering
def render_markdown(name: str, payload: Mapping[str, Any]) -> str:
    title = name.replace("_", " ").title()
    lines = [f"# {title}", "", f"> {HEADER_NOTE}", ""]
    generated = payload.get("generated_at")
    if generated:
        lines += [f"Generated: {generated}", ""]

    for key, value in payload.items():
        if key in {"report", "generated_at", "note", "orders_sent", "evidence"}:
            continue
        lines += _render(key, value, level=2)
    lines += ["", "---", "", "ORDERS SENT: 0. Research does not execute."]
    return "\n".join(lines) + "\n"


def _render(key: str, value: Any, *, level: int) -> list[str]:
    heading = "#" * min(level, 6)
    label = str(key).replace("_", " ").title()

    if isinstance(value, Mapping):
        if _is_table(value):
            return [f"{heading} {label}", "", *_table(list(value.values())), ""]
        lines = [f"{heading} {label}", ""]
        for inner_key, inner in value.items():
            lines += _render(inner_key, inner, level=level + 1)
        return lines

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = list(value)
        if items and all(isinstance(item, Mapping) for item in items):
            return [f"{heading} {label}", "", *_table(items), ""]
        return [f"{heading} {label}", "",
                (", ".join(str(item) for item in items) if items else "_(none)_"), ""]

    return [f"- **{label}**: {_format(value)}"]


def _is_table(value: Mapping[str, Any]) -> bool:
    items = list(value.values())
    return bool(items) and all(isinstance(item, Mapping) for item in items) \
        and len({tuple(sorted(item)) for item in items}) == 1


def _table(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if not rows:
        return ["_(none)_"]
    columns = [key for key in rows[0]
               if not isinstance(rows[0][key], (Mapping, list, tuple))]
    if not columns:
        columns = list(rows[0])
    header = "| " + " | ".join(str(name).replace("_", " ") for name in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(_format(row.get(name)) for name in columns) + " |"
            for row in rows]
    return [header, divider, *body]


def _format(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".") if abs(value) < 1000 else f"{value:.2f}"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) if value else "—"
    if isinstance(value, Mapping):
        return json.dumps(value, default=str)
    return str(value)
