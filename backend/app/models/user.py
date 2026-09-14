from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"

    is_demo: Mapped[bool] = mapped_column(default=False)
