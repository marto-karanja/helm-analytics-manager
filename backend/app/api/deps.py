from fastapi import Header, HTTPException, status

from app.core.config import settings


async def verify_sync_token(authorization: str = Header(...)) -> None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != settings.sync_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sync token")
