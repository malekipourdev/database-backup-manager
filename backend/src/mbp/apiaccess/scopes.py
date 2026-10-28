"""What a key may do: one read and one write scope per area of the panel.

An area is the OpenAPI tag of the endpoints ("instances", "projects", ...). GET reads; every
other method writes, except the few POSTs below that only compute something. Write implies
read. Downloading a backup file needs "backups:download" on its own: the dumps hold all the
data of the databases. "*" allows everything.
"""

# Every area, in the order the documentation and the panel list them.
AREAS: tuple[str, ...] = (
    "servers",
    "instances",
    "backups",
    "backup-settings",
    "schedules",
    "storage",
    "containers",
    "projects",
    "webservers",
    "notifications",
    "bots",
    "webhooks",
)
ALL = "*"
DOWNLOAD = "backups:download"
SCOPES: tuple[str, ...] = (
    ALL,
    *(f"{area}:{level}" for area in AREAS for level in ("read", "write")),
    DOWNLOAD,
)
READ_METHODS = frozenset({"GET", "HEAD"})
# (method, route path) that change nothing although they are POSTs.
READ_POSTS = frozenset(
    {
        ("POST", "/backup-settings/preview"),
        ("POST", "/schedules/preview"),
    }
)


def required_scope(method: str, area: str, path: str) -> str:
    """The scope an operation needs; `path` is the route's path without the /api/v1 prefix."""
    if area == "backups" and path.endswith("/download"):
        return DOWNLOAD
    read = method in READ_METHODS or (method, path) in READ_POSTS
    return f"{area}:{'read' if read else 'write'}"


def allows(scopes: list[str], needed: str) -> bool:
    if ALL in scopes or needed in scopes:
        return True
    area, _, level = needed.partition(":")
    return level == "read" and f"{area}:write" in scopes


def normalize(scopes: list[str]) -> list[str]:
    """Known scopes only, without duplicates, in the canonical order; ["*"] absorbs the rest."""
    wanted = set(scopes)
    if ALL in wanted:
        return [ALL]
    return [scope for scope in SCOPES if scope in wanted]


def unknown(scopes: list[str]) -> list[str]:
    return [scope for scope in scopes if scope not in SCOPES]
