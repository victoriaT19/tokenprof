"""Per-framework summary of an experiment batch: usage from the trace, accuracy from
the graded answers, and tokenprof findings by type.

    python summarize.py ../../docs/results/2026-11-06-exp-baseline.jsonl
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from tokenprof.analyze import analyze  # noqa: E402
from tokenprof.trace import read_traces  # noqa: E402


def framework_of(run_id: str) -> str:
    return run_id.split("-", 1)[0]


def summarize(trace_path: Path) -> dict[str, dict]:
    records = read_traces(trace_path)
    answers = [json.loads(line) for line in trace_path.with_name(trace_path.stem + "-answers.jsonl").read_text(encoding="utf-8").splitlines() if line]

    by_fw: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_fw[framework_of(record.get("run_id") or "?")].append(record)

    summary = {}
    for fw, fw_records in sorted(by_fw.items()):
        ok = [r for r in fw_records if r.get("status") == 200]
        usage = [r["usage"] for r in ok if r.get("usage")]
        reported = [u["cached_tokens"] for u in usage if u.get("cached_tokens") is not None]
        fw_answers = [a for a in answers if a["framework"] == fw]
        tasks = len(fw_answers)
        analysis = analyze(fw_records)
        totals = analysis.totals()
        summary[fw] = {
            "tasks": tasks,
            "correct": sum(a["correct"] for a in fw_answers),
            "calls": len(ok),
            "failed_calls": len(fw_records) - len(ok),
            "calls_per_task": round(len(ok) / tasks, 2) if tasks else None,
            "prompt_tokens": sum(u["prompt_tokens"] for u in usage),
            "completion_tokens": sum(u["completion_tokens"] for u in usage),
            "prompt_tokens_per_task": round(sum(u["prompt_tokens"] for u in usage) / tasks) if tasks else None,
            "cached_tokens_reported": sum(reported),
            "calls_with_cache_reported": len(reported),
            "latency_s": round(sum(r["latency_ms"] or 0 for r in ok) / 1000, 1),
            "wasted_by_kind": totals["wasted_by_kind"],
            "anatomy_pct": _anatomy(analysis),
        }
    return summary


def _anatomy(analysis) -> dict[str, float]:
    parts: dict[str, int] = defaultdict(int)
    for call in analysis.calls:
        for part, tokens in call.parts().items():
            parts[part] += tokens
    total = sum(parts.values()) or 1
    return {part: round(100 * tokens / total, 1) for part, tokens in parts.items()}


if __name__ == "__main__":
    print(json.dumps(summarize(Path(sys.argv[1])), indent=2, ensure_ascii=False))
