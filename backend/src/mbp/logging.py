import logging
import threading

REDACTED = "***"
SECRET_KEYS = frozenset(
    {"password", "password_encrypted", "encryption_key", "token", "admin_password"}
)

_secrets: set[str] = set()
_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Remember a secret value so it is masked in any log output."""
    if value and len(value) >= 4:
        with _lock:
            _secrets.add(value)


def redact(text: str) -> str:
    with _lock:
        secrets = sorted(_secrets, key=len, reverse=True)
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text


def _redact_mapping(mapping: dict) -> dict:
    return {
        key: REDACTED if str(key).lower() in SECRET_KEYS else value
        for key, value in mapping.items()
    }


def _redact_arg(value):
    """One %-argument, masked; non-strings keep their type unless they print a secret."""
    if isinstance(value, str):
        return redact(value)
    text = str(value)
    masked = redact(text)
    return value if masked == text else masked


class SecretRedactionFilter(logging.Filter):
    """Masks secret-named fields and registered secret values in log records.

    The arguments are masked one by one and keep their shape: some formatters (uvicorn's
    access log) unpack them, and breaking them made logging print the request's exception,
    with its submitted values, as a "Logging error".
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, dict):
            record.args = {
                key: REDACTED if str(key).lower() in SECRET_KEYS else _redact_arg(value)
                for key, value in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(_redact_arg(value) for value in record.args)
        record.msg = redact(record.msg) if isinstance(record.msg, str) else record.msg
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


_FILTER = SecretRedactionFilter()


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
        root.setLevel(level)
    # A record that fails to format must not make logging print the exception being handled
    # (it can hold submitted values such as passwords) to stderr.
    logging.raiseExceptions = False
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            if _FILTER not in handler.filters:
                handler.addFilter(_FILTER)
