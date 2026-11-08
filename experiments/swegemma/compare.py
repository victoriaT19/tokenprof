"""Compare resolution between runs task by task, with an exact McNemar test.

Usage:
    python compare.py base_e4b window_e4b guided_e4b full_e4b

Reads results/<name>/run_results.jsonl. For each run vs the first one, prints
tasks solved by both / only the reference / only the run, and the two-sided
exact McNemar p-value (binomial test on the discordant tasks). With 129 tasks
and resolution rates under 10%, only large differences reach significance.
"""

import json
import sys
from math import comb
from pathlib import Path

HERE = Path(__file__).parent


def solved(name: str) -> dict[str, bool]:
    rows = {}
    for line in (HERE / "results" / name / "run_results.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        value = row.get("resolved")
        rows[row["instance_id"]] = value is True or str(value).lower() == "true"
    return rows


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for b and c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * p)


def main(names: list[str]) -> None:
    ref_name, *others = names
    ref = solved(ref_name)
    print(f"| run | resolved | both | only {ref_name} | only run | McNemar p |")
    print("|---|---|---|---|---|---|")
    print(f"| {ref_name} | {sum(ref.values())} | | | | |")
    for name in others:
        run = solved(name)
        ids = ref.keys() & run.keys()
        both = sum(1 for i in ids if ref[i] and run[i])
        only_ref = sum(1 for i in ids if ref[i] and not run[i])
        only_run = sum(1 for i in ids if run[i] and not ref[i])
        print(f"| {name} | {sum(run.values())} | {both} | {only_ref} | {only_run} | "
              f"{mcnemar_exact(only_ref, only_run):.2f} |")
    union = set().union(*({i for i, v in solved(n).items() if v} for n in names))
    print(f"\nTasks solved by at least one run: {len(union)}")


if __name__ == "__main__":
    main(sys.argv[1:])
