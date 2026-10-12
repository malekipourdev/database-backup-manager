# Implementation Plan: Projects (phase 2)

## Architecture

- **Agent** (`mbp.agent.deploy`): `DeployManager` runs jobs in threads (one per project at a
  time): `git init/remote/fetch --depth 1 <ref>/checkout --force --detach FETCH_HEAD`, writes
  `.env` (0600, quoting verified against real compose), `docker compose config/pull
  --ignore-buildable/build/up -d --remove-orphans`, then watches `ps` for up to 60 s. Token via
  `GIT_CONFIG_*` environment (http.extraHeader), SSH key in a 0600 file in a per-job temp home
  (removed after), `GIT_ALLOW_PROTOCOL=https:ssh`. Output masked for secrets, kept per job.
  Endpoints: `POST /v1/deploy`, `GET /v1/deploy/{job}?offset=`, `GET /v1/projects/{name}/state`,
  `POST /v1/projects/{name}/remove`.
- **Image**: Dockerfile stages `base` → `agent` (git, openssh-client, Docker CLI with compose
  and buildx from `docker:27.5.1-cli`) and `runtime` (backend, default target).
- **Backend**: `projects` and `deployments` tables (migration 0007); `ProjectService`
  (validation, encrypted credential and variables); `DeployRunner` (thread pool: pre-deploy
  backups through BackupService/BackupRunner, then the agent job polled into the deployment's
  log; recovery on start; alerts `deploy_succeeded`/`deploy_failed`).
- **Bot**: `ProjectMenu`; code confirmation shared with containers; result sent to the chat.
- **Frontend**: Projects list, form, detail with services, history and a live log drawer.

## Constitution Check (v2.1.0)

| Principle | Status |
|-----------|--------|
| I. Security | Amended: encrypted credentials/variables, no command-line secrets, masking, TOTP for bot deploys, protected panel name. Routes require the session (route-coverage test). |
| II. Trustworthy backups | Pre-deploy backups are normal verified runs, recorded with trigger "deploy". |
| IV. Simple | No new service; the agent gains jobs. Threads in the backend for deploy orchestration. |
| V. DB-agnostic | ORM + repositories; migration 0007 checked on SQLite, MySQL, PostgreSQL. |
| VI. Containers | Amended allow-list; backend never runs Docker; agent image is a separate target. |
| VIII. Bilingual | fa/en for page, bot and alerts. |
| IX/X | Unit tests with scripted commands, API tests, bot tests, real git + compose integration test, vitest; ruff, ESLint, Prettier. |
