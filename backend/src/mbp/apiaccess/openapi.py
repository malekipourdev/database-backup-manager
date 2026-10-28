"""The OpenAPI document of the external API, built from the very routes the panel itself uses."""

import re
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from mbp.apiaccess import scopes
from mbp.apiaccess.middleware import V1_PREFIX, is_v1
from mbp.apiaccess.summaries import SUMMARIES
from mbp.apiaccess.webhooks import ALL_EVENTS, EVENT_NAMES

VERSION = "1.0.0"
TITLE = "DevOps Manager API"
SECURITY = [{"bearerAuth": []}, {"apiKeyHeader": []}]
# Tag of the endpoints about the key itself (no scope needed).
SELF_TAG = "api"

TAG_DESCRIPTIONS: dict[str, str] = {
    SELF_TAG: "The key making the request, and what keys and webhooks can be given.",
    "servers": "Servers with an agent: add, connect, rename, remove; their install tokens.",
    "instances": "Database servers (MySQL/MariaDB): connection, test, databases, selection.",
    "backups": "Backup runs: start, follow, list, delete, upload to remote storage, download "
    "(download needs `backups:download`).",
    "backup-settings": "Compression, encryption and dump options, globally and per database.",
    "schedules": "Automatic backups: cron-like schedules, preview, run now.",
    "storage": "Remote (S3) storage and retention policies.",
    "containers": "Docker containers of a server: list, inspect, stats, logs, start/stop/"
    "restart; host resources; alert thresholds.",
    "projects": "Projects deployed from Git with Docker Compose: create, deploy, follow "
    "deployments, state; project folders.",
    "webservers": "nginx and Apache: sites, configuration files with backups, test, reload, "
    "maintenance mode, certificates (Let's Encrypt), logs, health checks.",
    "notifications": "Alert rules, thresholds, the notification webhook channel and the log of "
    "alerts.",
    "bots": "Bale and Telegram bots and their admins.",
    "webhooks": "Webhooks of this API: subscribe an address to events, test, deliveries.",
    "health": "Is the panel up (no key needed).",
}

ERROR_SCHEMA = {
    "title": "Error",
    "type": "object",
    "required": ["code"],
    "properties": {
        "code": {"type": "string", "description": "Machine-readable, e.g. `insufficient_scope`"},
        "detail": {"type": "string", "description": "More about the error, when there is more"},
        "fields": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Field name → error code, on `validation_error`",
        },
    },
}


def _error(description: str) -> dict:
    return {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    }


DESCRIPTION = f"""
Everything the panel can do, for your own software: the panel's dashboard is built on the
same endpoints, so nothing it shows or does is missing here.

## Base URL

`https://<your panel>{V1_PREFIX}` — every path below is under it. This document:
`{V1_PREFIX}/openapi.json` (import it into Postman, Insomnia, or an OpenAPI code generator).

## Authentication

Create a key in the panel: **API → Keys → New key**. The key is shown once; store it as a
secret. Send it with every request, either way:

```
Authorization: Bearer mbp_xxxxxxxx...
X-API-Key: mbp_xxxxxxxx...
```

A key acts as the admin who created it; changes it makes appear in the panel's activity logs
as `<admin> (API: <key name>)` with the source `api`. Keys cannot manage keys: that is done
in the panel only.

A key can be limited to addresses or networks (`203.0.113.7`, `10.0.0.0/8`), given an expiry
date, turned off, or rotated (a new secret, same settings).

## Scopes

Each area (the tags below) has a `read` and a `write` scope: `projects:read`,
`projects:write`, ... `write` includes `read`. GET requests read; the other methods write.
Downloading a backup file needs `backups:download` (the dumps hold all the data). `*` allows
everything. Each operation lists the scope it needs (`x-required-scope`). A request without
it gets `403 insufficient_scope`, with the missing scope in `detail`.

## Servers

The panel manages several servers. Endpoints about one server's things take a `server`
query parameter (the server's ID from `GET /servers`); without it they act on the panel's
own server.

## Requests and responses

JSON in, JSON out (UTF-8). Times are ISO 8601 in UTC. A field left out of a PATCH body is
kept. Lists that can grow without bound are paged (see each endpoint's parameters).

Long work runs in the background and returns `202` at once:

- backups: `POST /instances/{{id}}/backups` → poll `GET /backups/runs/{{run_id}}` until
  `status` is `success` or `failed`;
- deploys: `POST /projects/{{id}}/deploy` → poll `GET /deployments/{{id}}` (its log grows);
- certificates and other web server jobs → poll `GET /webservers/-/jobs/{{job_id}}`.

Or skip the polling: subscribe a webhook to `backup_succeeded`, `backup_failed`,
`deploy_succeeded`, `deploy_failed`, ...

## Errors

```json
{{"code": "insufficient_scope", "detail": "projects:write"}}
```

| Status | Codes |
| --- | --- |
| 401 | `api_key_missing`, `api_key_invalid`, `api_key_expired` |
| 403 | `insufficient_scope`, `ip_not_allowed`, `api_key_disabled`, `api_disabled`; \
refusals of the panel itself (e.g. `webservers_read_only`) |
| 404 | `<thing>_not_found` |
| 409 | conflicts, e.g. `name_taken`, `agent_outdated` |
| 422 | `validation_error`, with `fields`: field name → error code |
| 429 | `rate_limited` (see below) |
| 502/503/504 | a server's agent could not be reached or failed |

## Rate limits

Each key has its own limit (requests per minute; set in the panel). Responses carry
`X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset` (seconds until the
window resets); a `429` also has `Retry-After`.

## Webhooks

Instead of polling, let the panel call you: `POST /webhooks` with your URL and the events you
want (`["*"]` for all). The response holds the webhook's signing secret, shown once.

Events: {", ".join(f"`{e}`" for e in EVENT_NAMES)}.

Each event is a `POST` of JSON:

```json
{{
  "id": "6f1c0e3a-…",
  "event": "backup_failed",
  "created_at": "2026-01-01T08:00:00+00:00",
  "severity": "error",
  "subject": "backup_failed:3:shop",
  "message": "Backup of shop on prod failed: …",
  "params": {{"instance": "prod", "db": "shop", "reason": "…"}},
  "run_id": 42,
  "source": "devops-manager"
}}
```

with the headers `X-MBP-Event`, `X-MBP-Delivery` (the payload's `id`; the same on retries),
`X-MBP-Timestamp` (Unix seconds) and `X-MBP-Signature`:
`sha256=` + hex HMAC-SHA256 of `<timestamp>.<raw body>` with the secret. Check it, and reject
old timestamps (e.g. older than 5 minutes) to stop replays:

```python
import hashlib, hmac, time

def verify(secret: str, body: bytes, timestamp: str, signature: str) -> bool:
    if abs(time.time() - int(timestamp)) > 300:
        return False
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return hmac.compare_digest("sha256=" + mac.hexdigest(), signature)
```

```js
const crypto = require("crypto");
function verify(secret, rawBody, timestamp, signature) {{
  if (Math.abs(Date.now() / 1000 - Number(timestamp)) > 300) return false;
  const mac = crypto.createHmac("sha256", secret)
    .update(`${{timestamp}}.${{rawBody}}`)
    .digest("hex");
  return crypto.timingSafeEqual(Buffer.from(`sha256=${{mac}}`), Buffer.from(signature));
}}
```

Answer with any `2xx` within 10 seconds. Otherwise the delivery is retried twice (after 10
seconds and after a minute). Deliveries can be listed, and sent again, with
`GET /webhooks/{{id}}/deliveries` and `POST /webhooks/deliveries/{{id}}/redeliver`.
Webhooks get every event they subscribe to whatever the panel's alert rules, but repeats of
the same alert inside the alert cooldown are not sent.

## Calling from a browser

Server-to-server calls need nothing more. For a web page that calls the API itself, add its
origin (`https://app.example.com`) in the panel: **API → Settings → Allowed origins**. Keep
in mind that a key in a web page can be read by anyone using that page: give it only the
scopes the page needs, or call the API from your own backend instead.

## Examples

```bash
curl -H "Authorization: Bearer $MBP_KEY" https://panel.example.com{V1_PREFIX}/projects
curl -X POST -H "Authorization: Bearer $MBP_KEY" -H "Content-Type: application/json" \\
     -d '{{"ref": "main"}}' https://panel.example.com{V1_PREFIX}/projects/3/deploy
```

```js
const api = (path, init = {{}}) =>
  fetch(`https://panel.example.com{V1_PREFIX}${{path}}`, {{
    ...init,
    headers: {{
      Authorization: `Bearer ${{KEY}}`,
      "Content-Type": "application/json",
      ...init.headers,
    }},
  }}).then(async (r) => {{
    if (!r.ok) throw await r.json();
    return r.status === 204 ? null : r.json();
  }});

const runs = await api("/backups/runs?page_size=20");
```

```python
import httpx
api = httpx.Client(base_url="https://panel.example.com{V1_PREFIX}",
                   headers={{"Authorization": f"Bearer {{KEY}}"}})
started = api.post("/instances/1/backups", json={{"scope": "single", "database": "shop"}}).json()
run_id = started["created"][0]["id"]
```

## Versioning

`v1` stays compatible: fields and endpoints may be added, never removed or changed in
meaning. A breaking change would come as `v2`, next to `v1`.
"""


def _operation_id(op: dict, path: str, method: str) -> str:
    """FastAPI's id is "<function><path>_<method>"; keep the function's name."""
    original = op.get("operationId", "")
    suffix = re.sub(r"\W", "_", path) + "_" + method
    if original.endswith(suffix) and len(original) > len(suffix):
        return original[: -len(suffix)]
    return original


def _refs(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[1])
        for value in node.values():
            _refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _refs(value, found)


def build_spec(app: FastAPI) -> dict:
    spec = get_openapi(
        title=TITLE,
        version=VERSION,
        description=DESCRIPTION,
        routes=app.routes,
    )
    paths = {path: ops for path, ops in spec.get("paths", {}).items() if is_v1(path)}
    seen: dict[str, int] = {}
    for path, ops in paths.items():
        relative = path[len(V1_PREFIX) :]
        for method, op in ops.items():
            tags = op.get("tags") or []
            area = tags[0] if tags else ""
            name = _operation_id(op, path, method)
            seen[name] = seen.get(name, 0) + 1
            op["operationId"] = name
            op["summary"] = SUMMARIES.get(f"{method.upper()} {relative}", op.get("summary", ""))
            if area in scopes.AREAS or area == SELF_TAG:
                op["security"] = SECURITY
                responses = op.setdefault("responses", {})
                responses.setdefault("401", _error("No key, or not a valid one"))
                responses.setdefault("403", _error("The key may not do this"))
                responses.setdefault("429", _error("Too many requests for this key"))
                if area in scopes.AREAS:
                    needed = scopes.required_scope(method.upper(), area, relative)
                    op["x-required-scope"] = needed
                    note = f"**Scope:** `{needed}`"
                    op["description"] = (
                        f"{op['description']}\n\n{note}" if op.get("description") else note
                    )
            else:
                op["security"] = []
    # Function names repeat across areas (get_settings, ...): those get the area in front.
    for ops in paths.values():
        for op in ops.values():
            if seen.get(op["operationId"], 0) > 1:
                area = (op.get("tags") or ["x"])[0].replace("-", "_")
                op["operationId"] = f"{area}_{op['operationId']}"
    spec["paths"] = paths

    components = spec.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas["Error"] = ERROR_SCHEMA
    # Only the schemas the external API uses (the panel's own endpoints have others).
    used: set[str] = set()
    _refs(paths, used)
    while True:
        more: set[str] = set()
        for name in used:
            _refs(schemas.get(name, {}), more)
        if more <= used:
            break
        used |= more
    components["schemas"] = {name: schemas[name] for name in sorted(used) if name in schemas}
    components["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "description": "`Authorization: Bearer mbp_…` (a key from the panel's API page)",
        },
        "apiKeyHeader": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
    }
    present = {tag for ops in paths.values() for op in ops.values() for tag in op.get("tags", [])}
    order = [SELF_TAG, *scopes.AREAS, "health"]
    spec["tags"] = [
        {"name": tag, "description": TAG_DESCRIPTIONS.get(tag, "")}
        for tag in order
        if tag in present
    ]
    spec["x-scopes"] = list(scopes.SCOPES)
    spec["x-webhook-events"] = [ALL_EVENTS, *EVENT_NAMES]
    return spec


def get_spec(app: FastAPI) -> dict:
    spec = getattr(app.state, "v1_openapi", None)
    if spec is None:
        spec = build_spec(app)
        app.state.v1_openapi = spec
    return spec


def catalog(app: FastAPI) -> dict:
    """Areas with how many operations read and write, every scope, every webhook event."""
    counts = {area: {"read": 0, "write": 0} for area in scopes.AREAS}
    for ops in get_spec(app)["paths"].values():
        for op in ops.values():
            needed = op.get("x-required-scope")
            if not needed:
                continue
            area, _, level = needed.partition(":")
            counts[area]["write" if level == "write" else "read"] += 1
    return {
        "base_path": V1_PREFIX,
        "areas": [{"area": area, **counts[area]} for area in scopes.AREAS],
        "scopes": list(scopes.SCOPES),
        "events": [ALL_EVENTS, *EVENT_NAMES],
    }
