from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from mbp.api import (
    auth,
    backup_settings,
    backups,
    bots,
    containers,
    health,
    instances,
    notifications,
    projects,
    schedules,
    servers,
    storage,
)
from mbp.api.errors import register_error_handlers
from mbp.backups.runner import BackupRunner
from mbp.backups.scheduler import BackupScheduler
from mbp.backups.store import get_store
from mbp.bots.manager import BotManager
from mbp.config import get_settings
from mbp.containers.agent_client import AgentClient
from mbp.containers.monitor import ContainerMonitor
from mbp.db import get_sessionmaker
from mbp.logging import configure_logging
from mbp.notifications.monitor import AlertMonitor
from mbp.notifications.notifier import Notifier
from mbp.projects.runner import DeployRunner
from mbp.repositories.server_repository import ServerRepository
from mbp.security import crypto
from mbp.security.sessions import require_csrf, require_session
from mbp.servers.registry import AgentRegistry, set_registry
from mbp.services.auth_service import bootstrap_admin

API_PREFIX = "/api"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    with get_sessionmaker()() as db:
        bootstrap_admin(db, get_settings())
        ServerRepository(db).local()
    # Runs left queued/running by a previous process are failed and their temp files removed
    # before new work is accepted (single backend process: the queue lives in memory).
    settings, sessions, store = get_settings(), get_sessionmaker(), get_store()
    runner = BackupRunner(settings, sessions, store)
    runner.recover()
    runner.start()
    app.state.backup_runner = runner
    # The local agent's client; other servers' clients come from the registry.
    agent = AgentClient.from_settings(settings)
    app.state.agent = agent
    agents = AgentRegistry(settings, sessions, local=lambda: app.state.agent)
    app.state.agents = agents
    set_registry(agents)
    notifier = Notifier(sessions)
    runner.notifier = notifier
    app.state.notifier = notifier
    monitor = AlertMonitor(sessions, notifier, settings.backup_root)
    scheduler = BackupScheduler(
        settings,
        sessions,
        runner,
        store,
        notifier=notifier,
        monitor=monitor,
        container_monitor=ContainerMonitor(sessions, notifier, agents),
    )
    scheduler.start()
    app.state.backup_scheduler = scheduler
    deploy_runner = DeployRunner(
        sessions, runner, store, agents=lambda: app.state.agents, notifier=notifier
    )
    deploy_runner.recover()
    app.state.deploy_runner = deploy_runner
    bot_manager = BotManager(
        sessions,
        runner,
        store,
        scheduler=scheduler,
        agent=lambda: app.state.agents,
        deploy_runner=lambda: app.state.deploy_runner,
    )
    # Alerts reach the bots' admins; the bots then poll for their admins' commands.
    notifier.bots = bot_manager
    app.state.bot_manager = bot_manager
    if settings.bots_enabled:
        bot_manager.start()
    try:
        yield
    finally:
        bot_manager.stop()
        deploy_runner.stop()
        scheduler.stop()
        runner.stop()
        notifier.close()
        set_registry(None)
        agents.close()
        agent.close()


def create_app() -> FastAPI:
    configure_logging()
    crypto.validate_key()

    app = FastAPI(
        title="MySQL Backup Panel",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    register_error_handlers(app)

    # Unauthenticated: health check (no data) and login only. Everything else requires
    # a valid session and the CSRF header (Constitution Principle I).
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.public_router, prefix=API_PREFIX)
    protected = [Depends(require_session), Depends(require_csrf)]
    app.include_router(auth.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(instances.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(backups.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(backup_settings.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(schedules.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(storage.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(bots.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(notifications.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(containers.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(projects.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(servers.router, prefix=API_PREFIX, dependencies=protected)
    return app


app = create_app()
