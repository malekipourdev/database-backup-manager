# Implementation Plan: Container Monitoring and Control (phase 1)

## Architecture

- **Agent** (`mbp.agent`, `python -m mbp.agent`, same image as the backend, compose profile
  `containers`): FastAPI app on `:8090`, internal network only. Talks to the Docker Engine API
  over the Unix socket with httpx (no Docker SDK dependency). Bearer token =
  HMAC-SHA256(first MBP_ENCRYPTION_KEY, "mbp-agent-v1"). Endpoints: `/health`, `/v1/info`,
  `/v1/containers`, `/v1/containers/{ref}`, `/{ref}/stats`, `/v1/stats`, `/{ref}/logs`,
  `POST /{ref}/{start|stop|restart}`. CPU% from one-shot stats and the previous sample; host
  numbers from /proc and statvfs. Refuses containers labelled `mbp.role`.
- **Backend**: `AgentClient` (errors mapped to API codes; a 401 from the agent becomes 502),
  `ContainerService` (hidden/locked/read-only rules, audit), `/api/containers…` (fixed routes
  under `/containers/-/…` so no container name can collide), `ContainerSettings` and
  `ContainerAction` tables (migration 0006), `ContainerMonitor` job (APScheduler, every 60 s)
  using `AlertState` rows, six new alert events.
- **Bot**: `ContainerMenu` mixin; pending actions per chat with a 2-minute expiry; TOTP check
  against panel accounts with two-step verification, updating `totp_last_step` (no replay).
- **Frontend**: Containers page (containers / activity / settings tabs), details drawer with
  logs, alert rendering, nav item; scrollable mobile tab bar.

## Constitution Check (v2.0.0)

| Principle | Status |
|-----------|--------|
| I. Security | Amended for containers; agent limits, protection of the panel's containers, audit log, read-only/hidden/locked, env values never returned, TOTP for bot actions, bot logs off by default. All new routes require the session (route-coverage test). |
| IV. Simple | One optional service (the agent), justified by isolating docker.sock; amended. No queue or worker. |
| V. DB-agnostic | ORM + repositories; migration 0006 checked on SQLite, MySQL, PostgreSQL. |
| VI. Containers | Backend/frontend still never mount docker.sock; agent read-only FS, cap_drop ALL, no-new-privileges, no published port. Amended. |
| VIII. Bilingual | fa/en for the page, alerts and bot; parity tests. |
| IX/X | pytest (agent over an in-memory Docker API, monitor with injected clock, bot over the fake Bot API, real-Docker integration test), vitest, ruff, ESLint, Prettier. |

No new dependencies.
