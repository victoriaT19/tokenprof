"""Cost estimation from a user-supplied price table.

Prices change often, so none are hardcoded: the table is a JSON file mapping
model names to USD prices per million tokens, for example

    {"my-model": {"input_per_mtok": 0.5, "output_per_mtok": 1.5, "cached_input_per_mtok": 0.05}}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None = None


class Pricing:
    def __init__(self, prices: dict[str, ModelPrice]) -> None:
        self.prices = prices

    @classmethod
    def from_file(cls, path: str | Path) -> Pricing:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls({model: ModelPrice(**entry) for model, entry in raw.items()})

    def lookup(self, model: str | None) -> ModelPrice | None:
        """Exact match first, then the longest table key that prefixes the model name
        (so a dated version like "model-2025-01-01" falls back to "model")."""
        if not model:
            return None
        if model in self.prices:
            return self.prices[model]
        candidates = [key for key in self.prices if model.startswith(key)]
        return self.prices[max(candidates, key=len)] if candidates else None

    def cost(self, model: str | None, usage: dict[str, Any] | None) -> float | None:
        price = self.lookup(model)
        if price is None or not usage:
            return None
        prompt = usage.get("prompt_tokens") or 0
        cached = usage.get("cached_tokens") or 0
        completion = usage.get("completion_tokens") or 0
        cached_rate = price.cached_input_per_mtok
        if cached_rate is None:
            cached_rate = price.input_per_mtok
        total = (
            (prompt - cached) * price.input_per_mtok
            + cached * cached_rate
            + completion * price.output_per_mtok
        )
        return total / 1_000_000
