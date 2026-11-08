"""Behaviour metrics per run, each tested against a reference run with Fisher's exact test.

Usage:
    python behaviour.py base_e4b window_e4b guided_e4b full_e4b

Resolution differences between configurations are within noise at 129 tasks,
but behaviour is measured over hundreds of tool calls or all 129 runs, so its
changes can be tested. Reads results/<name>/ (packed traces + run_results.jsonl).
"""

import re
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from tokenprof.swe import detect, load_results_dir  # noqa: E402

HERE = Path(__file__).parent
VERIFY = re.compile(r"\b(pytest|unittest|python3?)\b")


def fisher(a: int, n1: int, b: int, n2: int) -> float:
    """Two-sided Fisher exact p-value for a/n1 vs b/n2."""
    total, k = n1 + n2, a + b

    def prob(x: int) -> float:
        return comb(n1, x) * comb(n2, k - x) / comb(total, k)

    observed = prob(a)
    lo, hi = max(0, k - n2), min(k, n1)
    return min(1.0, sum(p for x in range(lo, hi + 1) if (p := prob(x)) <= observed * (1 + 1e-9)))


def metrics(name: str) -> dict[str, tuple[int, int]]:
    runs = load_results_dir(HERE / "results" / name)
    seq = [t for r in runs for _, t in r.tool_sequence()]
    edits = [t for t in seq if t.name == "edit_file"]
    reads = [t for t in seq if t.name == "read_file"]
    flags = {r.instance_id: {f.kind for f in detect(r)} for r in runs}

    def runs_with(kind: str) -> tuple[int, int]:
        return sum(1 for r in runs if kind in flags[r.instance_id]), len(runs)

    return {
        "edit_file succeeded (calls)": (sum(1 for t in edits if t.status == "ok"), len(edits)),
        "read_file with a line range (calls)": (
            sum(1 for t in reads if t.args.get("start_line") or t.args.get("end_line")), len(reads)),
        "runs with an unscoped truncated read": runs_with("unscoped_truncated_read"),
        "runs with a repeated read": runs_with("repeated_read"),
        "runs with a context overflow": runs_with("context_overflow"),
        "runs with no submission": runs_with("no_submit"),
        "runs with a nudge": runs_with("continuation_nudge"),
        "runs that executed code": (
            sum(1 for r in runs if any(t.name == "run_command" and VERIFY.search(str(t.args.get("command")))
                                       for _, t in r.tool_sequence())), len(runs)),
        "runs resolved": (sum(1 for r in runs if r.resolved), len(runs)),
    }


def main(names: list[str]) -> None:
    table = {name: metrics(name) for name in names}
    ref = names[0]
    print("| metric | " + " | ".join(names) + " |")
    print("|---" * (len(names) + 1) + "|")
    for metric in table[ref]:
        a, n1 = table[ref][metric]
        cells = [f"{a}/{n1} ({a / n1:.0%})"]
        for name in names[1:]:
            b, n2 = table[name][metric]
            p = fisher(a, n1, b, n2)
            star = " **" if p < 0.01 else (" *" if p < 0.05 else "")
            cells.append(f"{b}/{n2} ({b / n2:.0%}) p={p:.3f}{star}")
        print(f"| {metric} | " + " | ".join(cells) + " |")
    print("\np-values: two-sided Fisher exact test vs the first run; * p<0.05, ** p<0.01")


if __name__ == "__main__":
    main(sys.argv[1:])
