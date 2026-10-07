"""Owner-editable settings stored in `app_settings`, with defaults and server-side validation."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indexing import AppSetting

INSPECTION_CEILING = 1500  # hard global ceiling per day; the UI can lower the budget but never exceed this
VOLUME_SOURCES = ("gsc_proxy", "keyword_planner")
WEIGHT_KEYS = ("demand", "gap", "relevance", "competition")


class SettingError(ValueError):
    pass


def _int_between(low: int, high: int) -> Callable[[Any], int]:
    def check(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise SettingError("must be a whole number")
        if not low <= value <= high:
            raise SettingError(f"must be between {low} and {high}")
        return value

    return check


def _number_between(low: float, high: float) -> Callable[[Any], float]:
    def check(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SettingError("must be a number")
        if not low <= value <= high:
            raise SettingError(f"must be between {low} and {high}")
        return float(value)

    return check


def _volume_source(value: Any) -> str:
    if value not in VOLUME_SOURCES:
        raise SettingError(f"must be one of {', '.join(VOLUME_SOURCES)}")
    return value


def _weights(value: Any) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != set(WEIGHT_KEYS):
        raise SettingError(f"must have exactly the keys {', '.join(WEIGHT_KEYS)}")
    check = _number_between(0, 10)
    return {key: check(value[key]) for key in WEIGHT_KEYS}


def _budget_split(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise SettingError("must map project slug to a daily budget")
    check = _int_between(0, INSPECTION_CEILING)
    return {str(slug): check(n) for slug, n in value.items()}


@dataclass(frozen=True)
class SettingSpec:
    default: Any
    validate: Callable[[Any], Any]
    description: str


SPECS: dict[str, SettingSpec] = {
    "inspection_budget": SettingSpec(
        500, _int_between(0, INSPECTION_CEILING), "URL inspections per day across all projects (hard ceiling 1,500)"
    ),
    "inspection_budget_split": SettingSpec({}, _budget_split, "Optional per-project daily cap, keyed by slug"),
    "thin_word_threshold": SettingSpec(300, _int_between(50, 5000), "Pages below this word count are flagged thin"),
    "scoring_weights": SettingSpec(
        {"demand": 1.0, "gap": 1.2, "relevance": 0.6, "competition": 0.3}, _weights, "Keyword score weights"
    ),
    "volume_source": SettingSpec("gsc_proxy", _volume_source, "Where keyword demand comes from"),
    "llm_daily_cap_usd": SettingSpec(2.0, _number_between(0, 100), "Daily Claude API spend cap in USD"),
}


async def get_setting(db: AsyncSession, key: str) -> Any:
    spec = SPECS[key]
    row = await db.get(AppSetting, key)
    return spec.default if row is None else row.value


async def get_all_settings(db: AsyncSession) -> dict[str, Any]:
    rows = {row.key: row.value for row in (await db.execute(select(AppSetting))).scalars()}
    return {key: rows.get(key, spec.default) for key, spec in SPECS.items()}


async def put_setting(db: AsyncSession, key: str, value: Any, updated_by: str | None) -> Any:
    spec = SPECS.get(key)
    if spec is None:
        raise SettingError(f"unknown setting {key!r}")
    clean = spec.validate(value)
    row = await db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=clean, updated_by=updated_by))
    else:
        row.value = clean
        row.updated_by = updated_by
    await db.commit()
    return clean


def effective_budget(configured: int) -> int:
    """The server-side clamp: whatever is stored, a run never spends past the ceiling."""
    return max(0, min(int(configured), INSPECTION_CEILING))
