# Feature Specification: Messenger Bots (Bale, Telegram) and Notifications

**Feature Branch**: `004-bots-notifications`
**Created**: 2026-10-11
**Status**: Implemented
**Input**: "Connect the system to a Bale bot and Telegram. The user creates a bot and registers
its admins in the panel; the bot works only for those admins. Everything that makes sense must
be possible from the bot with inline buttons. Also a strong notification and alert system,
configurable from the panel."

## User Scenarios & Testing

### User Story 1 - Connect a bot and register admins (P1)

1. **Given** a Bale or Telegram bot token, **When** the admin saves it under Bots, **Then** the
   panel connects by long polling and shows "Connected as @bot" (no public address needed).
2. **Given** a numeric user ID or a one-time link code, **Then** that person becomes a bot
   admin; codes are single-use, expire after 15 minutes and are stored only as hashes.
3. **Given** anyone not registered (or disabled), **Then** the bot replies only with their own
   numeric ID. Group chats are ignored.

### User Story 2 - Manage backups from the bot (P1)

Inline-button menus: status overview; servers (details, connection test, back up all marked
databases with confirmation, back up one database chosen from the live list); backup history
and details (retry upload, delete with confirmation, receive the file when allowed); schedules
(enable/disable, run now); retention (preview, apply with confirmation); per-admin alert level
and language. Secrets can never be entered or shown in the bot.

### User Story 3 - Alerts (P1)

1. Events: backup failed, upload failed, no recent backup (stale), low disk space, schedule did
   not run, retention error, backup succeeded, back to normal, daily summary.
2. Per event: on/off and channels (Bale, Telegram, webhook). Thresholds: stale hours, disk %,
   cooldown, summary time, time zone.
3. Condition alerts fire once when the problem starts and once when it clears.
4. The same alert about the same subject is sent at most once per cooldown; repeats are logged.
5. Every alert is logged with per-channel delivery results; the panel shows the history.
6. The webhook sends JSON signed with HMAC-SHA256 (`X-MBP-Signature`).
7. A test button sends a test alert to all channels and shows the results.

## Requirements

- **FR-001**: Bot tokens and webhook secrets MUST be encrypted at rest and never returned or
  logged (httpx request logging, which contains the token in the URL, is silenced and the
  token is registered for redaction).
- **FR-002**: The bot MUST check the sender against registered, enabled admins on every
  message and button press.
- **FR-003**: Destructive bot actions (delete, retention apply, back up all) MUST confirm first.
- **FR-004**: Sending backup files through a bot MUST be off by default and size-limited.
- **FR-005**: Alerts MUST never break the operation that raised them.
- **FR-006**: All new UI and bot text MUST exist in Persian and English.

## Success Criteria

- **SC-001**: A non-admin never receives any data from the bot (tested).
- **SC-002**: A backup failure reaches bot admins and the webhook within seconds (tested).
- **SC-003**: No token or secret appears in API responses, logs, alert history or webhooks (tested).
