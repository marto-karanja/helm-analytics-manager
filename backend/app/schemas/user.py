import uuid

from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    is_demo: bool


class UserCreate(schemas.BaseUserCreate):
    is_demo: bool = False


class UserUpdate(schemas.BaseUserUpdate):
    pass
