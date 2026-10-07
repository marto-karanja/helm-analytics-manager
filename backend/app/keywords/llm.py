"""Claude API access for keyword expansion, with a per-call spend ledger and a daily cap."""
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.indexing import LlmSpend

# USD per million tokens, input / output. From the published price list; update when models or prices change.
# An unknown model is billed at the most expensive known rate so the daily cap errs on the safe side.
PRICES_PER_MTOK = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
}
FALLBACK_PRICE = (10.0, 50.0)
MAX_OUTPUT_TOKENS = 16000


class LlmError(RuntimeError):
    pass


class DailyCapReached(LlmError):
    pass


@dataclass
class LlmReply:
    text: str
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def cost_usd(self) -> float:
        return cost_usd(self.model, self.input_tokens, self.output_tokens)

    def json(self) -> dict:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise LlmError(f"model did not return valid JSON: {exc}") from exc


# (system prompt, user prompt, JSON schema) -> reply. Tests inject a fake with this shape.
LlmCall = Callable[[str, str, dict], Awaitable[LlmReply]]


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES_PER_MTOK.get(model, FALLBACK_PRICE)
    return round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 6)


async def spent_today(db: AsyncSession, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total = (await db.execute(select(func.coalesce(func.sum(LlmSpend.cost_usd), 0.0)).where(LlmSpend.created_at >= start))).scalar_one()
    return float(total)


async def check_cap(db: AsyncSession, cap_usd: float, now: datetime | None = None) -> None:
    spent = await spent_today(db, now)
    if spent >= cap_usd:
        raise DailyCapReached(f"daily LLM spend cap reached (${spent:.2f} of ${cap_usd:.2f})")


async def record_spend(db: AsyncSession, project_id, reply: LlmReply) -> float:
    db.add(
        LlmSpend(
            project_id=project_id,
            model=reply.model,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            cost_usd=reply.cost_usd,
        )
    )
    await db.commit()
    return reply.cost_usd


async def call_claude(system: str, user: str, schema: dict) -> LlmReply:
    """One non-streaming structured-output call. Thinking stays at the model default and effort is
    left at its default; sampling parameters are not sent because current models reject them."""
    if not settings.anthropic_api_key:
        raise LlmError("HELM_ANTHROPIC_API_KEY is not set")
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.keyword_model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    if response.stop_reason == "refusal":
        category = getattr(getattr(response, "stop_details", None), "category", None)
        raise LlmError(f"the model declined the request ({category or 'no category'})")
    if response.stop_reason == "max_tokens":
        raise LlmError("the model's answer was cut off at the output limit; reduce the seed list")
    text = next((b.text for b in response.content if b.type == "text"), "")
    return LlmReply(
        text=text,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
