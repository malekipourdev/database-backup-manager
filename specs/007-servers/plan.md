# Implementation Plan: Several servers

## Architecture

- **Agent remote mode** (`MBP_AGENT_TOKEN` set): HTTPS with a self-signed certificate made on
  first start (`mbp.agent.tls`, kept in `/data`); requests verified by
  `mbp.security.agent_auth` (HMAC-SHA256 of `ts`, method, path and certificate fingerprint;
  5-minute window; `agent_clock_skew` when only the time is off). `POST /v1/hello` answers a
  nonce with `HMAC(token, nonce, fingerprint)`. Local mode is unchanged (bearer token derived
  from `MBP_ENCRYPTION_KEY`, internal network).
- **Databases through an agent** (`mbp.agent.mysql`): `/v1/mysql/test`, `/v1/mysql/databases`
  (the panel's own probe code), `/v1/mysql/dump`: the dump tool with the panel's options and a
  private option file, streamed as frames (`mbp.backups.frames`: data frames, then an end frame
  with the exit code and stderr tail). A container name as host resolves to its IP. Closing the
  stream kills the tool.
- **Agent image** gains `mysqldump` and `mariadb-dump`; `docker-compose.agent.yml` runs it on
  another server (host network, read-only, no capabilities, data volume for the certificate).
- **Backend**: `servers` table (migration 0008; the local server inserted, existing projects,
  actions and container settings attached to it); `AgentRegistry` (one client per server,
  rebuilt when its address, token or certificate changes); `ServerService` (create with a
  token, connect with challenge and pinning, new token, delete with usage check);
  `db_access` (test/list directly or through an agent); `AgentDumpProcess` (same interface as
  `DumpProcess`, writes through the shared `write_stream`). Container settings rows are keyed by
  server id; the containers API takes `?server=`; projects and instances get `server_id`.
- **Monitor**: every connected server is checked; alert keys of other servers end with
  `@<id>`, so the local server's keys are unchanged; events carry `server` for rendering.
- **Bot**: a server picker before the containers list when there are several; container
  tokens carry the server.
- **Frontend**: Servers page (cards, add with install commands shown once, connect, edit, new
  token, delete), server picker on Containers, server field on projects, "Connect from" on
  databases, menu renamed to Databases.

## Constitution Check (v3.0.0)

| Principle | Status |
|-----------|--------|
| I. Security | Amended: pinned certificates, signed requests, tokens encrypted and shown once, no stored database credentials on agents. Routes require the session. |
| II. Trustworthy backups | Remote dumps are verified like local ones (checksum, completion marker); a cut stream fails the run. |
| IV. Simple | No new service: the same agent in another mode. |
| V. DB-agnostic | Migration 0008 cycled on SQLite, MySQL 8.4, PostgreSQL 16. |
| VI. Containers | Amended: remote agent mode and database operations in the allow-list. |
| VIII. Bilingual | fa/en for the page, the bot and alerts. |
| IX/X | Real TLS agent in API tests; real MySQL/MariaDB integration test; vitest; ruff, ESLint, Prettier. |
