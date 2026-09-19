import argparse
import asyncio
import getpass
import sys

from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users.exceptions import UserAlreadyExists

from app.core.users import UserManager
from app.db.session import async_session_maker
from app.models.user import User
from app.schemas.user import UserCreate

MIN_PASSWORD_LENGTH = 12


async def create_user(email: str, password: str) -> User:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    async with async_session_maker() as session:
        manager = UserManager(SQLAlchemyUserDatabase(session, User))
        return await manager.create(UserCreate(email=email, password=password))


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="create an account (password is prompted, never an argument)")
    create.add_argument("email")
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1

    try:
        user = asyncio.run(create_user(args.email, password))
    except (ValueError, UserAlreadyExists) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {user.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
