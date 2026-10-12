"""Server-side admin commands, for when an admin cannot sign in.

Usage (Docker):
  docker compose exec backend python -m mbp.cli list-admins
  docker compose exec backend python -m mbp.cli reset-password <username> [--generate]
  docker compose exec backend python -m mbp.cli disable-2fa <username>
"""

import argparse
import getpass
import secrets
import sys

from sqlalchemy import delete

from mbp.db import get_sessionmaker
from mbp.models import AuthSession
from mbp.repositories.admin_repository import AdminRepository
from mbp.repositories.login_attempt_repository import LoginAttemptRepository
from mbp.security.passwords import hash_password
from mbp.services.two_factor_service import disable_two_factor

MIN_PASSWORD_LENGTH = 10


def _list_admins(db) -> int:
    from mbp.models import AdminAccount

    for admin in db.query(AdminAccount).order_by(AdminAccount.username):
        two_factor = "two-step verification on" if admin.totp_enabled else "password only"
        print(f"{admin.username}\t{two_factor}")
    return 0


def _new_password(generate: bool) -> str | None:
    if generate:
        return secrets.token_urlsafe(15)
    first = getpass.getpass("New password: ")
    if len(first) < MIN_PASSWORD_LENGTH:
        print(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        return None
    if getpass.getpass("Repeat the new password: ") != first:
        print("The passwords do not match.", file=sys.stderr)
        return None
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mbp.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list-admins", help="Show the admin accounts.")
    reset = commands.add_parser(
        "reset-password", help="Set a new password for an admin (forgotten password)."
    )
    reset.add_argument("username")
    reset.add_argument(
        "--generate", action="store_true", help="Generate a random password and print it."
    )
    disable = commands.add_parser(
        "disable-2fa", help="Turn off two-factor authentication for an admin (lost phone)."
    )
    disable.add_argument("username")
    args = parser.parse_args(argv)

    with get_sessionmaker()() as db:
        if args.command == "list-admins":
            return _list_admins(db)
        admin = AdminRepository(db).get_by_username(args.username)
        if admin is None:
            print(f"No admin named {args.username!r}.", file=sys.stderr)
            return 1
        if args.command == "reset-password":
            password = _new_password(args.generate)
            if password is None:
                return 1
            AdminRepository(db).update_password_hash(admin, hash_password(password))
            # Everyone signed in with the old password is signed out, and a lockout from
            # failed attempts is lifted.
            db.execute(delete(AuthSession).where(AuthSession.admin_id == admin.id))
            LoginAttemptRepository(db).delete(admin.username)
            db.commit()
            print(f"Password changed for {admin.username!r}; all its sessions were ended.")
            if args.generate:
                print(f"New password: {password}")
            if admin.totp_enabled:
                print("Two-step verification is still on (turn it off with disable-2fa).")
            return 0
        if not admin.totp_enabled:
            print(f"Two-factor authentication is already off for {admin.username!r}.")
            return 0
        disable_two_factor(admin)
        db.commit()
    print(
        f"Two-factor authentication turned off for {args.username!r}. Sign in and set it up again."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
