"""Web servers on a server (nginx, Apache): sites, status, files, logs, certificates, checks.

Every change goes through WebServerService (read-only mode, audit log); the agent tests the
configuration before reloading and undoes a change the web server does not accept.
"""

import re
from datetime import timedelta
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy.orm import Session

from mbp.api.containers import get_server
from mbp.api.errors import ApiError
from mbp.api.schemas import (
    CertbotIssueIn,
    CertbotStatus,
    WebActionItem,
    WebActionPage,
    WebBackupContent,
    WebBackupList,
    WebCertificates,
    WebCheckIn,
    WebCheckItem,
    WebCheckList,
    WebCheckResultItem,
    WebCheckUpdate,
    WebEnabledIn,
    WebFileContent,
    WebFileWrite,
    WebJob,
    WebKind,
    WebLogLines,
    WebMaintenanceIn,
    WebPathsIn,
    WebPhpSockets,
    WebRestoreIn,
    WebResult,
    WebServerList,
    WebServerSettingsIO,
    WebSiteCreate,
    WebStatusList,
    WebTestResult,
)
from mbp.apiaccess.keys import Actor, current_actor
from mbp.db import get_db, utcnow
from mbp.models import Server, WebCheck
from mbp.repositories.webserver_repository import WebServerRepository
from mbp.webservers.service import WebServerService

router = APIRouter(tags=["webservers"])
MAX_CHECKS = 200
RECENT_RESULTS = 48


def service(
    request: Request, db: Session = Depends(get_db), server: Server = Depends(get_server)
) -> WebServerService:
    return WebServerService(db, request.app.state.agents.for_server(server), server)


# --- reads ---


@router.get("/webservers", response_model=WebServerList)
def list_webservers(svc: WebServerService = Depends(service)) -> dict:
    return svc.list()


@router.get("/webservers/-/status", response_model=WebStatusList)
def status(svc: WebServerService = Depends(service)) -> dict:
    return svc.status()


@router.get("/webservers/-/certificates", response_model=WebCertificates)
def certificates(svc: WebServerService = Depends(service)) -> dict:
    return {"certificates": svc.agent.web_certificates()}


@router.get("/webservers/-/php-sockets", response_model=WebPhpSockets)
def php_sockets(svc: WebServerService = Depends(service)) -> dict:
    return {"sockets": svc.agent.web_php_sockets()}


@router.get("/webservers/-/certbot", response_model=CertbotStatus)
def certbot(svc: WebServerService = Depends(service)) -> dict:
    return svc.agent.web_certbot()


@router.get("/webservers/-/jobs/{job_id}", response_model=WebJob)
def job(job_id: str, svc: WebServerService = Depends(service)) -> dict:
    return svc.job(job_id)


@router.get("/webservers/{kind}/file", response_model=WebFileContent)
def read_file(
    kind: WebKind, path: str = Query(max_length=500), svc: WebServerService = Depends(service)
) -> dict:
    return svc.agent.web_file(kind, path)


@router.get("/webservers/{kind}/backups", response_model=WebBackupList)
def backups(
    kind: WebKind, path: str = Query(max_length=500), svc: WebServerService = Depends(service)
) -> dict:
    return svc.agent.web_backups(kind, path)


@router.get("/webservers/{kind}/backup", response_model=WebBackupContent)
def backup(
    kind: WebKind,
    path: str = Query(max_length=500),
    name: str = Query(max_length=32),
    svc: WebServerService = Depends(service),
) -> dict:
    return {"content": svc.agent.web_backup(kind, path, name)}


@router.get("/webservers/{kind}/logs", response_model=WebLogLines)
def logs(
    kind: WebKind,
    path: str = Query(max_length=500),
    lines: int = Query(default=200, ge=1, le=2000),
    svc: WebServerService = Depends(service),
) -> dict:
    return svc.agent.web_logs(kind, path, lines)


@router.post("/webservers/{kind}/test", response_model=WebTestResult)
def test(kind: WebKind, svc: WebServerService = Depends(service)) -> dict:
    return svc.agent.web_test(kind)


# --- changes ---


@router.post("/webservers/{kind}/control/{action}", response_model=WebResult)
def control(
    kind: WebKind,
    action: Literal["reload", "restart"],
    who: Actor = Depends(current_actor),
    svc: WebServerService = Depends(service),
) -> dict:
    return svc.change(
        kind,
        action,
        "",
        lambda: svc.agent.web_control(kind, action),
        actor=who.name,
        source=who.source,
    )


@router.put("/webservers/{kind}/file", response_model=WebResult)
def write_file(
    kind: WebKind,
    body: WebFileWrite,
    who: Actor = Depends(current_actor),
    svc: WebServerService = Depends(service),
) -> dict:
    return svc.change(
        kind,
        "edit",
        body.path,
        lambda: svc.agent.web_write(kind, body.path, body.content, body.sha256),
        actor=who.name,
        source=who.source,
    )


@router.post("/webservers/{kind}/restore", response_model=WebResult)
def restore(
    kind: WebKind,
    body: WebRestoreIn,
    who: Actor = Depends(current_actor),
    svc: WebServerService = Depends(service),
) -> dict:
    return svc.change(
        kind,
        "restore",
        f"{body.path} @ {body.backup}",
        lambda: svc.agent.web_restore(kind, body.path, body.backup),
        actor=who.name,
        source=who.source,
    )


@router.post("/webservers/{kind}/enabled", response_model=WebResult)
def set_enabled(
    kind: WebKind,
    body: WebEnabledIn,
    who: Actor = Depends(current_actor),
    svc: WebServerService = Depends(service),
) -> dict:
    return svc.change(
        kind,
        "enable" if body.enabled else "disable",
        body.path,
        lambda: svc.agent.web_enabled(kind, body.path, body.enabled),
        actor=who.name,
        source=who.source,
    )


@router.post("/webservers/{kind}/maintenance", response_model=WebResult)
def set_maintenance(
    kind: WebKind,
    body: WebMaintenanceIn,
    who: Actor = Depends(current_actor),
    svc: WebServerService = Depends(service),
) -> dict:
    return svc.change(
        kind,
        "maintenance_on" if body.on else "maintenance_off",
        body.path,
        lambda: svc.agent.web_maintenance(kind, body.path, body.on),
        actor=who.name,
        source=who.source,
    )


@router.post("/webservers/{kind}/broken-links/remove", response_model=WebResult)
def remove_broken_links(
    kind: WebKind,
    body: WebPathsIn,
    who: Actor = Depends(current_actor),
    svc: WebServerService = Depends(service),
) -> dict:
    return svc.change(
        kind,
        "remove_broken_links",
        " ".join(body.paths)[:500],
        lambda: svc.agent.web_remove_broken(kind, body.paths),
        actor=who.name,
        source=who.source,
    )


@router.post("/webservers/{kind}/sites", response_model=WebResult, status_code=201)
def create_site(
    kind: WebKind,
    body: WebSiteCreate,
    response: Response,
    who: Actor = Depends(current_actor),
    svc: WebServerService = Depends(service),
) -> dict:
    result = svc.change(
        kind,
        "create",
        " ".join(body.domains),
        lambda: svc.agent.web_create(kind, body.model_dump()),
        actor=who.name,
        source=who.source,
    )
    if not result.get("ok"):
        response.status_code = 200
    return result


@router.post("/webservers/{kind}/certbot/issue", response_model=WebJob, status_code=202)
def certbot_issue(
    kind: WebKind,
    body: CertbotIssueIn,
    who: Actor = Depends(current_actor),
    svc: WebServerService = Depends(service),
) -> dict:
    payload = body.model_dump()
    payload["email"] = payload["email"] or svc.settings.acme_email
    return svc.start_job(
        kind,
        "certbot_issue",
        " ".join(body.domains),
        lambda: svc.agent.web_certbot_issue(kind, payload),
        actor=who.name,
        source=who.source,
    )


@router.post("/webservers/{kind}/certbot/install", response_model=WebJob, status_code=202)
def certbot_install(
    kind: WebKind,
    who: Actor = Depends(current_actor),
    svc: WebServerService = Depends(service),
) -> dict:
    return svc.start_job(
        kind,
        "certbot_install",
        "certbot",
        lambda: svc.agent.web_certbot_install(kind),
        actor=who.name,
        source=who.source,
    )


@router.post("/webservers/-/certbot/renew", response_model=WebJob, status_code=202)
def certbot_renew(
    who: Actor = Depends(current_actor), svc: WebServerService = Depends(service)
) -> dict:
    return svc.start_job(
        "certbot",
        "certbot_renew",
        "",
        svc.agent.web_certbot_renew,
        actor=who.name,
        source=who.source,
    )


# --- settings and audit log ---


@router.get("/webservers/-/settings", response_model=WebServerSettingsIO)
def get_settings(db: Session = Depends(get_db), server: Server = Depends(get_server)) -> dict:
    return _settings_out(WebServerRepository(db).get_settings(server.id))


@router.put("/webservers/-/settings", response_model=WebServerSettingsIO)
def put_settings(
    body: WebServerSettingsIO, db: Session = Depends(get_db), server: Server = Depends(get_server)
) -> dict:
    row = WebServerRepository(db).get_settings_for_update(server.id)
    for field, value in body.model_dump().items():
        setattr(row, field, value)
    db.commit()
    return _settings_out(row)


def _settings_out(row) -> dict:
    return {field: getattr(row, field) for field in WebServerSettingsIO.model_fields}


@router.get("/webservers/-/actions", response_model=WebActionPage)
def actions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    server: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> WebActionPage:
    items, total = WebServerRepository(db).actions_page(page, page_size, server)
    return WebActionPage(
        items=[WebActionItem.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# --- health checks ---

URL_RE = re.compile(r"https?://[^\s/@]+(/\S*)?")


def _checked_url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if not URL_RE.fullmatch(url) or not parts.hostname or "@" in parts.netloc:
        raise ApiError(422, "validation_error", fields={"url": "invalid_url"})
    return url


def _check_items(db: Session, checks: list[WebCheck]) -> list[WebCheckItem]:
    repo = WebServerRepository(db)
    recent = repo.recent_results([c.id for c in checks], RECENT_RESULTS)
    since = utcnow() - timedelta(hours=24)
    out = []
    for check in checks:
        item = WebCheckItem.model_validate(check)
        item.uptime = repo.uptime(check.id, since)
        item.recent = [WebCheckResultItem.model_validate(r) for r in reversed(recent[check.id])]
        out.append(item)
    return out


@router.get("/webservers/-/checks", response_model=WebCheckList)
def list_checks(db: Session = Depends(get_db), server: Server = Depends(get_server)) -> dict:
    return {"checks": _check_items(db, WebServerRepository(db).checks(server.id))}


@router.post("/webservers/-/checks", response_model=WebCheckItem, status_code=201)
def add_check(
    body: WebCheckIn, db: Session = Depends(get_db), server: Server = Depends(get_server)
) -> WebCheckItem:
    url = _checked_url(body.url)
    repo = WebServerRepository(db)
    if repo.check_by_url(server.id, url) is not None:
        raise ApiError(409, "check_exists")
    if len(repo.checks(server.id)) >= MAX_CHECKS:
        raise ApiError(409, "too_many_checks")
    check = WebCheck(server_id=server.id, url=url, enabled=True, failures=0)
    db.add(check)
    db.commit()
    return _check_items(db, [check])[0]


def _owned_check(db: Session, server: Server, check_id: int) -> WebCheck:
    check = WebServerRepository(db).check(check_id)
    if check is None or check.server_id != server.id:
        raise ApiError(404, "check_not_found")
    return check


@router.patch("/webservers/-/checks/{check_id}", response_model=WebCheckItem)
def update_check(
    body: WebCheckUpdate,
    check_id: int = Path(ge=1),
    db: Session = Depends(get_db),
    server: Server = Depends(get_server),
) -> WebCheckItem:
    check = _owned_check(db, server, check_id)
    check.enabled = body.enabled
    db.commit()
    return _check_items(db, [check])[0]


@router.delete("/webservers/-/checks/{check_id}", status_code=204)
def delete_check(
    check_id: int = Path(ge=1), db: Session = Depends(get_db), server: Server = Depends(get_server)
) -> Response:
    db.delete(_owned_check(db, server, check_id))
    db.commit()
    return Response(status_code=204)


@router.post("/webservers/-/checks/{check_id}/run", response_model=WebCheckItem)
def run_check(
    request: Request,
    check_id: int = Path(ge=1),
    db: Session = Depends(get_db),
    server: Server = Depends(get_server),
) -> WebCheckItem:
    _owned_check(db, server, check_id)
    monitor = request.app.state.web_monitor
    for event in monitor.run_checks(only=check_id):
        monitor.notifier.emit(event)
    db.expire_all()
    return _check_items(db, [_owned_check(db, server, check_id)])[0]
