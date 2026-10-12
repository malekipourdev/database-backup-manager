"""Log redaction must mask secrets without breaking formatters (uvicorn's access log)."""

import io
import logging

from uvicorn.logging import AccessFormatter

from mbp.logging import _FILTER, register_secret

SECRET = "Leaky-Secret-Value-31"


def handler_with(formatter: logging.Formatter) -> tuple[logging.Handler, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    handler.addFilter(_FILTER)
    return handler, stream


def test_access_log_keeps_working_and_is_masked(capsys):
    register_secret(SECRET)
    handler, stream = handler_with(
        AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s')
    )
    logger = logging.getLogger("test.access")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        # As uvicorn logs a request, while the request's own exception is being handled.
        try:
            raise ValueError(f"input={SECRET}")
        except ValueError:
            logger.info(
                '%s - "%s %s HTTP/%s" %d',
                "127.0.0.1:5000",
                "GET",
                f"/api/x?token={SECRET}",
                "1.1",
                200,
            )
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert "GET /api/x?token=*** HTTP/1.1" in out and "200" in out
    err = capsys.readouterr().err
    assert "Logging error" not in err and SECRET not in err and SECRET not in out


def test_plain_messages_and_mappings(caplog):
    register_secret(SECRET)
    handler, stream = handler_with(logging.Formatter("%(message)s"))
    logger = logging.getLogger("test.plain")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        logger.info("connecting with %s", SECRET)
        logger.info("value %(password)s and %(other)s", {"password": "x", "other": SECRET})
        logger.info(f"inline {SECRET}")
        logger.info("object %s", {"nested": SECRET})
        logger.info("count %d", 42)
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert SECRET not in out
    assert "connecting with ***" in out and "value *** and ***" in out and "count 42" in out


def test_formatting_errors_do_not_dump_the_exception(capsys):
    from mbp.logging import configure_logging

    configure_logging()
    handler, _ = handler_with(logging.Formatter("%(message)s"))
    logger = logging.getLogger("test.broken")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        try:
            raise ValueError(f"input={SECRET}")
        except ValueError:
            logger.info("%d", "not a number")
    finally:
        logger.removeHandler(handler)
    assert SECRET not in capsys.readouterr().err
