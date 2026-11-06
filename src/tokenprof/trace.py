"""Trace records: one JSON object per LLM call, appended to a JSONL file."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any


class TraceWriter:
    """Appends trace records to a JSONL file. Safe to share across concurrent requests."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str)
        async with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


def read_traces(path: str | Path) -> list[dict[str, Any]]:
    """Load every record from a JSONL trace file, skipping blank lines."""
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
