"""Render an existing benchmark directory without running the tracker or touching its DB."""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def stage_totals(path):
    totals = {}
    process_cpu = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["type"] != "interval":
            continue
        process_cpu += record["process_cpu_ms"]
        for name, item in record["stages"].items():
            total = totals.setdefault(
                name,
                {
                    "count": 0,
                    "cpu_ms": 0.0,
                    "exclusive_cpu_ms": 0.0,
                    "wall_ms": 0.0,
                    "max_wall_ms": 0.0,
                },
            )
            total["count"] += item["count"]
            total["cpu_ms"] += item["thread_cpu_ms"]["total"]
            total["exclusive_cpu_ms"] += item["exclusive_thread_cpu_ms"]["total"]
            total["wall_ms"] += item["wall_ms"]["total"]
            total["max_wall_ms"] = max(total["max_wall_ms"], item["wall_ms"]["max"])
    return totals, process_cpu


def render(root):
    raw = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    runs = raw if isinstance(raw, list) else [raw]
    lines = [
        "# Benchmark report",
        "",
        "CPU is normalized to all logical processors. State labels come from sampled",
        "tracker state; transitions between samples are not reconstructed.",
        "",
        "| Run | State | Seconds | CPU mean % | CPU s/min | CPU p95 % (1s) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for run in runs:
        for state, item in run.get("states", {}).items():
            lines.append(
                f"| {run.get('directory', 'observed')} | {state} | "
                f"{item['elapsed_seconds']:.1f} | {item['cpu_percent_mean']:.3f} | "
                f"{item['cpu_seconds_per_minute']:.2f} | {item['cpu_percent_p95_1s']:.3f} |"
            )
    by_mode = defaultdict(list)
    for run in runs:
        if "ALL" in run.get("states", {}) and "mode" in run:
            by_mode[run["mode"]].append(run["states"]["ALL"])
    if by_mode:
        lines.extend(
            [
                "",
                "| Mode | Runs | Weighted mean CPU % | Run min % | Run max % |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for mode, items in by_mode.items():
            elapsed = sum(item["elapsed_seconds"] for item in items)
            average = (
                sum(item["cpu_percent_mean"] * item["elapsed_seconds"] for item in items) / elapsed
            )
            values = [item["cpu_percent_mean"] for item in items]
            lines.append(
                f"| {mode} | {len(items)} | {average:.3f} | {min(values):.3f} | {max(values):.3f} |"
            )
        lines.extend(
            [
                "",
                "This is a descriptive comparison, not a statistical claim about overhead.",
                "Compare matching states and workloads; short runs include scheduling noise.",
            ]
        )
    for run in runs:
        history = run.get("history")
        if history:
            lines.extend(
                [
                    "",
                    f"History `{run.get('directory')}`: integrity={history['integrity']}, "
                    f"FK errors={history['foreign_key_errors']}, "
                    f"open={sum(history['open_sessions'].values())}, "
                    f"negative={sum(history['negative_intervals'].values())}.",
                    "",
                ]
            )
    lines.extend(
        [
            "",
            "## Instrumented stages",
            "",
            "These totals include startup, warmup and shutdown. They differ from the",
            "external steady-state window above. Inclusive rows overlap; only exclusive",
            "CPU can be added. Quantiles are kept per interval in JSONL, not averaged.",
        ]
    )
    paths = [
        root / run["directory"] / "performance.jsonl"
        for run in runs
        if "directory" in run and (root / run["directory"] / "performance.jsonl").exists()
    ]
    if (root / "performance.jsonl").exists():
        paths.append(root / "performance.jsonl")
    for path in paths:
        stages, process_cpu = stage_totals(path)
        exclusive = sum(item["exclusive_cpu_ms"] for item in stages.values())
        lines.extend(
            [
                "",
                f"### {path.parent.name}",
                "",
                f"Process CPU: {process_cpu:.1f} ms; instrumented exclusive CPU: "
                f"{exclusive:.1f} ms; residual: {process_cpu - exclusive:.1f} ms.",
                "",
                "Residual includes uninstrumented threads, diagnostics and clock resolution.",
                "",
                "| Stage | Calls | Inclusive CPU ms | Exclusive CPU ms | "
                "Wall mean ms | Wall max ms |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for name, item in sorted(stages.items(), key=lambda pair: -pair[1]["exclusive_cpu_ms"]):
            lines.append(
                f"| {name} | {item['count']} | {item['cpu_ms']:.1f} | "
                f"{item['exclusive_cpu_ms']:.1f} | {item['wall_ms'] / item['count']:.2f} | "
                f"{item['max_wall_ms']:.2f} |"
            )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    target = args.directory / "report.md"
    target.write_text(render(args.directory), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
