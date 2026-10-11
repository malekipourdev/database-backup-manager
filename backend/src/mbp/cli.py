"""Server-side admin commands, e.g. for an admin locked out of two-factor authentication.

Usage (Docker): docker compose exec backend python -m mbp.cli disable-2fa <username>
"""

import argparse
import sys

from mbp.db import get_sessionmaker
from mbp.repositories.admin_repository import AdminRepository
from mbp.services.two_factor_service import disable_two_factor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mbp.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    disable = commands.add_parser(
        "disable-2fa", help="Turn off two-factor authentication for an admin (lost phone)."
    )
    disable.add_argument("username")
    args = parser.parse_args(argv)

    with get_sessionmaker()() as db:
        admin = AdminRepository(db).get_by_username(args.username)
        if admin is None:
            print(f"No admin named {args.username!r}.", file=sys.stderr)
            return 1
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
