"""Write area guides: one LLM call per area, within a dollar budget.

Areas go largest first (by test count). An area whose stored guide was built from the same
area digest, prompt version and model is up to date and skipped. Before each call the worst
case (estimated input + the full output cap, at the configured prices) must fit in what is
left of the budget; after each call the actual cost is added: what the provider reports, else
tokens x prices. The budget can never exceed ``guides.max_budget_usd``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from ticket2test.config import Settings
from ticket2test.generate.context import estimate_tokens
from ticket2test.guides.budget import (
    BudgetExceeded,
    BudgetGuard,
    CostUnknown,
    call_cost,
    load_calibration,
    save_calibration,
)
from ticket2test.guides.check import check_guide
from ticket2test.guides.inputs import pick_material
from ticket2test.index.indexer import IndexData
from ticket2test.llm.base import LLMClient, LLMError, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.meter import UsageMeter
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import StructuredOutputError, complete_structured
from ticket2test.models.guide import AreaGuide, GuideOutput, GuidePlanItem, GuideRun
from ticket2test.models.suite_map import AreaSummary, SuiteMap
from ticket2test.prompts import PromptTemplate, load_prompt


class BudgetError(ValueError):
    """The requested budget is above the configured ceiling."""


def guides_dir(repo_root: Path, settings: Settings) -> Path:
    if settings.guides.dir is not None:
        return settings.guides.dir
    name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in repo_root.resolve().name)
    return settings.paths.output_dir / "guides" / name


def guide_path(folder: Path, area: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in area)
    return folder / f"{safe}.json"


def load_guide(folder: Path, area: str) -> AreaGuide | None:
    try:
        return AreaGuide.model_validate_json(guide_path(folder, area).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_guides(
    suite_map: SuiteMap,
    index: IndexData,
    settings: Settings,
    client: LLMClient | None,
    folder: Path,
    budget_usd: float | None = None,
    estimate_only: bool = False,
    force: bool = False,
    areas: list[str] | None = None,
) -> GuideRun:
    cfg = settings.guides
    budget = cfg.max_budget_usd if budget_usd is None else budget_usd
    if budget > cfg.max_budget_usd:
        raise BudgetError(
            f"budget ${budget:.2f} is above guides.max_budget_usd (${cfg.max_budget_usd:.2f}); "
            "lower it, or raise the ceiling in the config on purpose"
        )
    prompt = load_prompt(cfg.prompt, settings.paths.prompts_dir)
    model = model_name(settings, "guide")
    run = GuideRun(
        repo_root=suite_map.repo_root,
        created_at=datetime.now(UTC),
        model=model,
        prompt_version=prompt.version,
        estimate_only=estimate_only,
        budget_usd=budget,
        ceiling_usd=cfg.max_budget_usd,
        prices_known=model in cfg.prices,
        items=[],
    )
    wanted = [a for a in suite_map.areas if areas is None or a.name in areas]
    ordered = sorted(wanted, key=lambda a: (-a.tests, a.name))
    calibration = load_calibration(folder, model, settings)
    run.overhead_tokens, run.output_allowance_tokens = (
        calibration.overhead_tokens,
        calibration.output_tokens,
    )
    meter = UsageMeter(client) if client is not None and not estimate_only else None
    guard = BudgetGuard(meter, model, settings, budget, calibration) if meter is not None else None
    built = 0
    for area in ordered:
        material = pick_material(area, index, settings)
        user = _user(prompt, area, material.text)
        tokens_in = estimate_tokens(prompt.system + user, settings.context.chars_per_token)
        worst = call_cost(
            tokens_in + calibration.overhead_tokens, calibration.output_tokens, model, settings
        )
        item = GuidePlanItem(
            area=area.name,
            tests=area.tests,
            status="planned",
            input_tokens_estimate=tokens_in,
            max_output_tokens=calibration.output_tokens,
            cost_estimate_usd=worst,
        )
        run.items.append(item)
        stored = load_guide(folder, area.name)
        if (
            not force
            and stored is not None
            and stored.digest == area.digest
            and stored.prompt_version == prompt.version
            and stored.model == model
        ):
            item.status = "up_to_date"
            continue
        if estimate_only:
            continue
        if run.stopped:
            item.status = "stopped"
            continue
        if built >= cfg.max_areas_per_run:
            item.status = "over_limit"
            continue
        assert meter is not None and guard is not None
        started = time.monotonic()
        before, spent_before = meter.usage, guard.spent_usd
        try:
            guide = _write(guard, prompt, user, model, settings)
        except BudgetExceeded as exc:
            item.status = "over_budget" if meter.usage == before else "failed"
            item.note = str(exc)[:300]
            run.stopped = item.note
        except CostUnknown as exc:
            item.status = "failed"
            item.note = f"{exc}: stopping"
            run.stopped = item.note
        except (LLMError, StructuredOutputError) as exc:
            item.status = "failed"
            item.note = str(exc)[:300]
        else:
            checked, removed, unverified = check_guide(guide, area, index)
            usage = meter.usage.minus(before)
            save_guide(
                folder,
                AreaGuide(
                    area=area.name,
                    digest=area.digest,
                    sources=area.sources,
                    model=model,
                    prompt_version=prompt.version,
                    built_at=datetime.now(UTC),
                    input_pieces=material.pieces,
                    input_tokens_estimate=tokens_in,
                    guide=checked,
                    removed=removed,
                    unverified=unverified,
                    usage=usage,
                    cost_usd=round(guard.spent_usd - spent_before, 6),
                ),
            )
            built += 1
            item.status = "built"
            item.removed, item.unverified = len(removed), len(unverified)
        item.usage = meter.usage.minus(before)
        item.cost_usd = round(guard.spent_usd - spent_before, 6)
        item.seconds = round(time.monotonic() - started, 1)
        run.spent_usd = guard.spent_usd
    if guard is not None and guard.calibration.calls:
        save_calibration(folder, model, guard.calibration)
        run.overhead_tokens = guard.calibration.overhead_tokens
        run.output_allowance_tokens = guard.calibration.output_tokens
    return run


def save_guide(folder: Path, guide: AreaGuide) -> None:
    from ticket2test.guides.render import render_guide

    folder.mkdir(parents=True, exist_ok=True)
    path = guide_path(folder, guide.area)
    path.write_text(guide.model_dump_json(indent=2), encoding="utf-8")
    path.with_suffix(".md").write_text(render_guide(guide), encoding="utf-8")


def _user(prompt: PromptTemplate, area: AreaSummary, material: str) -> str:
    return prompt.render_user(area=area.name, material=material)


def _write(
    client: LLMClient, prompt: PromptTemplate, user: str, model: str, settings: Settings
) -> GuideOutput:
    result = complete_structured(
        client,
        LLMRequest(
            messages=(
                Message(role="system", content=prompt.system),
                Message(role="user", content=user),
            ),
            temperature=settings.llm.temperature,
            seed=settings.llm.seed,
            max_output_tokens=settings.guides.max_output_tokens,
            json_schema=strict_schema(GuideOutput),
            model=model,
        ),
        GuideOutput,
        max_retries=settings.llm.max_retries_on_bad_json,
    )
    return result.value
