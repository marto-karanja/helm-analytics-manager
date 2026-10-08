"""Which projects the current caller may see. Set once per authenticated MCP or REST call; the shared service
layer reads it, so both front ends enforce the same rule. None means unrestricted (the owner's own tokens)."""
from contextvars import ContextVar

allowed_slugs: ContextVar[frozenset[str] | None] = ContextVar("helm_allowed_slugs", default=None)


def permits(slug: str) -> bool:
    allowed = allowed_slugs.get()
    return allowed is None or slug in allowed


def as_scope(project_slugs: list[str] | None) -> frozenset[str] | None:
    return None if project_slugs is None else frozenset(project_slugs)
