# Feature Specification: Container Monitoring and Control (phase 1)

**Feature Branch**: `005-containers`
**Created**: 2026-10-11
**Status**: Implemented
**Input**: "Add a container manager to the panel, step by step, so that eventually projects can
be deployed from the panel or the Bale bot. Phase 1: see and control the server's containers."

## User Scenarios & Testing

### User Story 1 - See the server's containers (P1)

1. **Given** the agent is running, **When** the admin opens Containers, **Then** every
   container is listed, grouped by compose project, problems first, with state, health,
   uptime or exit code, CPU, RAM and automatic restarts, refreshed every few seconds, plus the
   server's CPU, RAM and Docker disk.
2. Details show image, ports, networks, volumes, restart policy, health output and the names
   (never the values) of environment variables. Logs: last 100–5000 lines, stdout/stderr,
   filter, follow, download.
3. **Given** the agent is not installed or cannot use Docker, **Then** the page explains how to
   turn it on (and the rest of the panel works as before).

### User Story 2 - Control containers (P1)

1. Start, stop and restart; stop and restart ask for confirmation.
2. The panel's own containers, and containers locked in the settings, cannot be controlled;
   read-only mode refuses every action; hidden containers are not shown at all.
3. Every attempt is recorded (who, panel or bot, container, action, result).

### User Story 3 - Alerts (P1)

Container went down (error exit or OOM, not a deliberate stop), restart loop, unhealthy,
high CPU/RAM (two checks in a row), server RAM / Docker disk above a limit, agent lost.
Announced once when the problem starts and once when it clears; rules and channels on the
Notifications page; thresholds and watched containers in Containers → Settings.

### User Story 4 - From the bot (P2)

List (problems first), details with usage, server status, logs (only if allowed), start/stop/
restart confirmed with a fresh TOTP code of a panel account with two-step verification on.
Wrong codes are limited (3 per request, 5 per 15 minutes per bot admin).

## Requirements

- **FR-001**: Only the agent has docker.sock; the backend never does. The agent is optional
  (compose profile), listens only on the internal network, authenticates the backend, and
  implements only list/inspect/stats/logs/start/stop/restart.
- **FR-002**: Environment variable values MUST never leave the agent.
- **FR-003**: The panel's own containers (label `mbp.role`) MUST NOT be controllable, enforced in
  the agent and the backend.
- **FR-004**: Every control attempt MUST be audited, including refused and failed ones.
- **FR-005**: Bot actions MUST require a TOTP code; bot logs MUST be off by default.
- **FR-006**: A browser request MUST never get a 401 because of an agent problem (it would end
  the admin's session in the UI).
- **FR-007**: All new UI and bot text in Persian and English.

## Success Criteria

- **SC-001**: No environment variable value appears in any API response (tested).
- **SC-002**: A crashed container raises one alert and one recovery (tested).
- **SC-003**: A container cannot be stopped from the bot without a valid, unused TOTP code
  (tested).
