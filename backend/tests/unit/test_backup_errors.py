import errno

import pytest

from mbp.backups.errors import classify_dump_failure, classify_os_error

PASSWORD = "Sup3r-Secret"


@pytest.mark.parametrize(
    ("stderr", "code"),
    [
        # mysqldump 8.4
        (
            "mysqldump: Got error: 1044: Access denied for user 'b'@'%' to database 'shop' "
            "when selecting the database",
            "missing_privileges",
        ),
        (
            "mysqldump: Got error: 1045: Access denied for user 'b'@'172.18.0.3' "
            "(using password: YES) when trying to connect",
            "auth_rejected",
        ),
        (
            "mysqldump: Got error: 1049: Unknown database 'nope' when selecting the database",
            "database_not_found",
        ),
        (
            "mysqldump: Error 2013: Lost connection to MySQL server during query when dumping "
            "table `t` at row: 1024",
            "connection_lost",
        ),
        (
            "mysqldump: Couldn't execute 'SHOW CREATE PROCEDURE `p`': SELECT command denied "
            "to user 'b'@'%' for table 'proc' (1142)",
            "missing_privileges",
        ),
        # mariadb-dump 11.8
        (
            "mariadb-dump: Got error: 1044: \"Access denied for user 'b'@'%' to database "
            "'shop'\" when selecting the database",
            "missing_privileges",
        ),
        (
            "mariadb-dump: Got error: 2002: \"Can't connect to server on 'db' (115)\" "
            "when trying to connect",
            "connection_lost",
        ),
        ("mysqldump: Couldn't execute 'FLUSH TABLES': something odd (1105)", "dump_failed"),
    ],
)
def test_classify_dump_failure(stderr, code):
    assert classify_dump_failure(2, stderr, PASSWORD)[0] == code


def test_warnings_are_dropped_from_message():
    stderr = (
        "mysqldump: [Warning] Using a password on the command line interface can be insecure.\n"
        "mysqldump: Got error: 1049: Unknown database 'x' when selecting the database\n"
    )
    code, message = classify_dump_failure(2, stderr, PASSWORD)
    assert code == "database_not_found"
    assert "Warning" not in message


def test_password_scrubbed_and_truncated():
    stderr = f"mysqldump: weird failure with {PASSWORD} " + "x" * 3000
    code, message = classify_dump_failure(2, stderr, PASSWORD)
    assert code == "dump_failed"
    assert PASSWORD not in message
    assert len(message) <= 1000


def test_empty_stderr_has_message():
    assert classify_dump_failure(137, "", PASSWORD)[1] == "dump tool exited with code 137"


@pytest.mark.parametrize(
    ("err", "code"),
    [(errno.ENOSPC, "disk_full"), (errno.EDQUOT, "disk_full"), (errno.EACCES, "storage_error")],
)
def test_classify_os_error(err, code):
    assert classify_os_error(OSError(err, "x"))[0] == code
