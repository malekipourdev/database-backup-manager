# Implementation Plan: Messenger Bots and Notifications

**Branch**: `004-bots-notifications` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

## Summary

- `bots/api.py`: a small Bot API client over httpx (sync, optional proxy incl. SOCKS). Bale's
  bot API implements the Telegram Bot API, so one client serves both (`tapi.bale.ai` /
  `api.telegram.org`, overridable for self-hosted API servers and tests).
- `bots/manager.py`: one long-polling thread per enabled bot (offset persisted), updates
  handled in a small thread pool; `broadcast()` sends alerts to admins by level.
- `bots/handler.py`: menus and actions; long values (database names) travel as short
  in-memory tokens because callback data is limited to 64 bytes.
- `bots/texts.py`: Persian/English strings, Persian digits and Jalali dates.
- `notifications/`: `Event` + defaults, `Notifier` (rules, cooldown, history, delivery in the
  background), webhook channel (HMAC), `AlertMonitor` (stale backups, disk, daily summary),
  `render` (event → message per language).
- Hooks: the runner emits backup/upload/retention events; the scheduler emits schedule
  problems and runs the monitor (every 10 min) and the daily summary (cron, in the configured
  zone).
- Migration `0004`: `bot_settings`, `bot_admins`, `bot_link_codes`, `notification_settings`,
  `notification_log`, `alert_states`.
- API: `/bots`, `/bots/{platform}` (+ `/test`, `/token`, `/link-codes`), `/bot-admins`,
  `/notifications/settings`, `/notifications/test`, `/notifications/log`,
  `/schedules/{id}/run`.
- Frontend: Bots page, Notifications page (rules matrix, thresholds, webhook, history),
  "Run now" on schedules.

## Constitution Check (v1.1.0)

| Principle | Status |
|-----------|--------|
| I. Security | Amended for the bot interface; all rules implemented and tested (admin check per update, private chats, confirmations, file sending off by default, encrypted token/secret, no token in logs or errors). All new HTTP routes require the session (route-coverage test). |
| II. Trustworthy | Failures and missing backups now also alert; condition alerts are stateful; delivery results are logged. |
| IV. Simple | Polling and delivery are threads in the backend; no inbound webhook, queue or worker. Constitution amended to say so. |
| V. DB-agnostic | ORM + repositories; JSON columns are portable; migration checked on SQLite, MySQL, PostgreSQL. |
| VIII. Bilingual | Panel and bot texts in fa/en with parity tests; Jalali dates and Persian digits in the bot. |
| IX/X | pytest (fake Bot API over real HTTP, monitors with injected clock/disk), vitest, ruff, ESLint, Prettier. |

New dependencies: `httpx[socks]` (already a dev dependency; now runtime, for the Bot API and
webhooks; SOCKS for proxies). Justified under IV: no service added.
