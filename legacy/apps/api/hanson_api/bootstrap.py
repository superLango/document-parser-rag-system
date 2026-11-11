"""Create the initial platform administrator.

Usage (from ``apps/api``):

    python -m hanson_api.bootstrap --username admin --password "change-me"

The command is idempotent: an existing user keeps its password unless
``--reset-password`` is passed.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from .config import PlatformSettings
from .db import build_engine, build_session_factory, init_db, verify_migrations
from .models import User
from .security import hash_password


def create_user(
    settings: PlatformSettings,
    username: str,
    password: str,
    *,
    display_name: str = "管理员",
    role: str = "admin",
    reset_password: bool = False,
) -> User:
    engine = build_engine(settings)
    try:
        if settings.db_auto_create:
            init_db(engine)
        else:
            verify_migrations(engine)
        session_factory = build_session_factory(engine)
        with session_factory() as db:
            user = db.scalar(select(User).where(User.username == username))
            if user is None:
                user = User(
                    username=username,
                    display_name=display_name,
                    hashed_password=hash_password(password),
                    role=role,
                )
                db.add(user)
                db.commit()
                db.refresh(user)
                return user
            if reset_password:
                user.hashed_password = hash_password(password)
                db.commit()
                db.refresh(user)
            return user
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a platform user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--display-name", default="管理员")
    parser.add_argument("--role", default="admin")
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args(argv)

    settings = PlatformSettings.from_env()
    user = create_user(
        settings,
        args.username,
        args.password,
        display_name=args.display_name,
        role=args.role,
        reset_password=args.reset_password,
    )
    print(f"user={user.username} id={user.id} role={user.role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
