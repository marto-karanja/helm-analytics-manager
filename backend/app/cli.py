import argparse
import asyncio
import getpass
import sys

from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users.exceptions import UserAlreadyExists
from sqlalchemy import select

from app.core.users import UserManager
from app.db.session import async_session_maker
from app.models.project import Project
from app.models.user import User
from app.schemas.user import UserCreate

MIN_PASSWORD_LENGTH = 12
GSC_PREFIXES = ("sc-domain:", "http://", "https://")


async def create_user(email: str, password: str) -> User:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    async with async_session_maker() as session:
        manager = UserManager(SQLAlchemyUserDatabase(session, User))
        return await manager.create(UserCreate(email=email, password=password))


async def set_analytics(slug: str, gsc: str | None, ga4: str | None) -> Project:
    if gsc is None and ga4 is None:
        raise ValueError("Give at least one of --gsc or --ga4")
    if gsc is not None and not gsc.startswith(GSC_PREFIXES):
        raise ValueError("--gsc must be `sc-domain:example.com` or a URL prefix like `https://example.com/`")
    if ga4 is not None and not ga4.startswith("properties/"):
        raise ValueError("--ga4 must look like `properties/123456789`")
    async with async_session_maker() as session:
        project = (
            await session.execute(select(Project).where(Project.slug == slug, Project.is_demo.is_(False)))
        ).scalar_one_or_none()
        if project is None:
            raise ValueError(f"No project with slug {slug!r}")
        if gsc is not None:
            project.gsc_site_url = gsc
        if ga4 is not None:
            project.ga4_property_id = ga4
        await session.commit()
        return project


def _run_set_analytics(args: argparse.Namespace) -> int:
    try:
        project = asyncio.run(set_analytics(args.slug, args.gsc, args.ga4))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{project.slug}: gsc_site_url={project.gsc_site_url} ga4_property_id={project.ga4_property_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="create an account (password is prompted, never an argument)")
    create.add_argument("email")
    analytics = sub.add_parser("set-analytics", help="set a project's Search Console / GA4 identifiers")
    analytics.add_argument("slug")
    analytics.add_argument("--gsc", help="Search Console property, e.g. sc-domain:example.com or https://example.com/")
    analytics.add_argument("--ga4", help="GA4 property, e.g. properties/123456789")
    args = parser.parse_args()

    if args.command == "set-analytics":
        return _run_set_analytics(args)

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
