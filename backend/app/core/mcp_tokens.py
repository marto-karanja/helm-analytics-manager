"""Bearer tokens for the MCP server and pipeline pulls: random, shown once, stored only as a SHA-256 hash."""
import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indexing import McpToken

TOKEN_PREFIX = "helm_"
SCOPES = ("read", "write")
RATE_LIMIT_PER_MINUTE = 60


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_token(db: AsyncSession, label: str, scope: str) -> tuple[McpToken, str]:
    """Returns the row and the plaintext token. The plaintext exists only in this return value."""
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
    label = label.strip()
    if not label or len(label) > 100:
        raise ValueError("label must be 1-100 characters")
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = McpToken(label=label, scope=scope, token_hash=hash_token(raw))
    db.add(row)
    await db.commit()
    return row, raw


async def verify_token(db: AsyncSession, raw: str | None) -> McpToken | None:
    """The active token for a presented secret, or None. Records last use."""
    if not raw or not raw.startswith(TOKEN_PREFIX):
        return None
    row = (await db.execute(select(McpToken).where(McpToken.token_hash == hash_token(raw)))).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    row.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return row


def allows(token: McpToken, needed: str) -> bool:
    return token.scope == "write" or needed == "read"


class RateLimiter:
    """Sliding one-minute window per key, in memory. One MCP process serves all clients, so this is enough."""

    def __init__(self, per_minute: int = RATE_LIMIT_PER_MINUTE, clock=time.monotonic):
        self.per_minute, self.clock = per_minute, clock
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self.clock()
        hits = self._hits[key]
        while hits and hits[0] <= now - 60:
            hits.popleft()
        if len(hits) >= self.per_minute:
            return False
        hits.append(now)
        return True
