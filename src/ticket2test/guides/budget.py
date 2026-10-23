"""Spending control for guide calls: a client wrapper that checks the budget before every call.

Found on the first real run (2026-10-23): the Claude CLI adds 6k-23k input tokens of its own
to every call, doesn't enforce the output cap (Opus wrote ~5.3k tokens against a 4k cap; its
thinking counts as output), and JSON retries made up to three calls per area while the budget
was checked once per area. So:

- the worst case is checked before *every* call, retries included;
- a call's worst case is its estimated input plus an overhead, and an output allowance, at the
  configured prices;
- overhead and output are calibrated from real calls (the largest seen per model) and saved
  next to the guides, so later estimates use measured numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ticket2test.config import Settings
from ticket2test.generate.context import estimate_tokens
from ticket2test.llm.base import LLMClient, LLMError, LLMRequest, LLMResponse


class BudgetExceeded(LLMError):
    """The next call's worst case doesn't fit in what is left of the budget."""


class CostUnknown(LLMError):
    """A call reported neither a cost nor tokens; spending can't be tracked."""


@dataclass
class Calibration:
    overhead_tokens: int  # input tokens a call costs beyond its estimated prompt
    output_tokens: int  # output tokens a call may produce
    calls: int = 0  # real calls these numbers come from (0: configured defaults)

    def to_json(self) -> dict[str, int]:
        return {
            "overhead_tokens": self.overhead_tokens,
            "output_tokens": self.output_tokens,
            "calls": self.calls,
        }


def load_calibration(folder: Path, model: str, settings: Settings) -> Calibration:
    cfg = settings.guides
    default = Calibration(cfg.call_overhead_tokens, max(cfg.output_allowance_tokens, 1))
    try:
        data = json.loads((folder / "calibration.json").read_text(encoding="utf-8"))[model]
        seen = Calibration(
            int(data["overhead_tokens"]), int(data["output_tokens"]), int(data["calls"])
        )
    except (OSError, ValueError, KeyError, TypeError):
        return default
    # Measured numbers replace the defaults only upwards: an estimate never gets optimistic.
    return Calibration(
        max(seen.overhead_tokens, default.overhead_tokens),
        max(seen.output_tokens, default.output_tokens),
        seen.calls,
    )


def save_calibration(folder: Path, model: str, calibration: Calibration) -> None:
    path = folder / "calibration.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[model] = calibration.to_json()
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def call_cost(tokens_in: int, tokens_out: int, model: str, settings: Settings) -> float | None:
    price = settings.guides.prices.get(model)
    if price is None:
        return None
    return round(
        (tokens_in * price.input_per_mtok + tokens_out * price.output_per_mtok) / 1_000_000, 6
    )


class BudgetGuard(LLMClient):
    """Wraps the guide client: refuses a call whose worst case would exceed the budget, adds
    each call's actual cost, and calibrates overhead and output from what calls really use."""

    def __init__(
        self,
        inner: LLMClient,
        model: str,
        settings: Settings,
        budget_usd: float,
        calibration: Calibration,
    ) -> None:
        self.inner = inner
        self.model = model
        self.settings = settings
        self.budget_usd = budget_usd
        self.calibration = calibration
        self.spent_usd = 0.0

    def worst_case(self, prompt_tokens: int) -> float | None:
        cal = self.calibration
        return call_cost(
            prompt_tokens + cal.overhead_tokens, cal.output_tokens, self.model, self.settings
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        prompt_tokens = estimate_tokens(
            "".join(m.content for m in request.messages), self.settings.context.chars_per_token
        )
        worst = self.worst_case(prompt_tokens)
        if worst is None:
            raise BudgetExceeded(f"no price configured for {self.model}")
        if self.spent_usd + worst > self.budget_usd:
            raise BudgetExceeded(
                f"the next call's worst case (${worst:.2f}) would exceed the budget "
                f"(${self.spent_usd:.2f} of ${self.budget_usd:.2f} spent)"
            )
        response = self.inner.complete(request)
        tokens_in, tokens_out = response.input_tokens, response.output_tokens
        if response.cost_usd is not None:
            cost: float | None = response.cost_usd
        elif tokens_in is not None or tokens_out is not None:
            cost = call_cost(tokens_in or 0, tokens_out or 0, self.model, self.settings)
        else:
            cost = None
        if cost is None:
            raise CostUnknown("the call reported neither a cost nor tokens")
        self.spent_usd = round(self.spent_usd + cost, 6)
        cal = self.calibration
        if tokens_in is not None:
            cal.overhead_tokens = max(cal.overhead_tokens, tokens_in - prompt_tokens)
        if tokens_out is not None:
            cal.output_tokens = max(cal.output_tokens, tokens_out)
        cal.calls += 1
        return response
