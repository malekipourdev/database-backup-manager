#!/usr/bin/env python3
"""Fake mysqldump/mariadb-dump for tests. Behaviour is chosen by the database name prefix:

ok_*            normal dump (~200 KB) ending with the completion marker
big_<MiB>_*     dump of <MiB> mebibytes
slow_<sec>_*    sleep <sec> seconds, then a normal dump
nomarker_*      full output, exit 0, but no completion marker
crash_*         half the output, then "Lost connection" (2013) and exit 2
denied_*        error 1044 (missing privileges), exit 2
missing_*       error 1049 (unknown database), exit 2
pwecho_*        an error message that contains the password, exit 2
"""

import sys
import time

MARKER = "-- Dump completed on 2026-10-11 12:00:00\n"


def read_password(option_file: str) -> str:
    with open(option_file, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("password="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def body(target_bytes: int) -> None:
    out = sys.stdout.buffer
    out.write(b"-- Fake dump\nCREATE TABLE `t` (`id` int, `v` varchar(64));\n")
    row = b"INSERT INTO `t` VALUES (1,'fake row data for backup tests 0123456789');\n"
    block = row * (1024 * 1024 // len(row))
    written = 0
    while written + len(block) <= target_bytes:
        out.write(block)
        written += len(block)
    remaining = max(0, target_bytes - written) // len(row)
    out.write(row * remaining)
    out.flush()


def fail(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()
    sys.exit(2)


def main() -> None:
    args = sys.argv[1:]
    if not args or not args[0].startswith("--defaults-extra-file="):
        fail("fake_dump: --defaults-extra-file must be the first argument")
    password = read_password(args[0].split("=", 1)[1])
    if password and any(password in arg for arg in args):
        fail("fake_dump: PASSWORD FOUND ON COMMAND LINE")
    database = args[-1]
    kind, _, rest = database.partition("_")

    if kind == "denied":
        fail(f"mysqldump: Got error: 1044: Access denied for user 'u'@'%' to database '{database}'")
    if kind == "missing":
        fail(
            f"mysqldump: Got error: 1049: Unknown database '{database}' when selecting the database"
        )
    if kind == "pwecho":
        fail(f"mysqldump: Got error: 1105: weird failure mentioning {password}")
    if kind == "slow":
        time.sleep(float(rest.split("_")[0]))
    if kind == "crash":
        body(100 * 1024)
        fail("mysqldump: Error 2013: Lost connection to server during query when dumping table `t`")

    size = int(rest.split("_")[0]) * 1024 * 1024 if kind == "big" else 200 * 1024
    body(size)
    if kind != "nomarker":
        sys.stdout.write(MARKER)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
