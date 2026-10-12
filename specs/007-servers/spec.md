# Feature Specification: Several servers in one panel

**Feature Branch**: `007-servers`
**Created**: 2026-10-12
**Status**: Implemented
**Input**: "Install the panel on one server and connect other servers to it, so several servers
can be managed. The Servers menu becomes database management."

## User Scenarios & Testing

### User Story 1 - Connect another server (P1)

An admin adds a server (name, address, agent port). The panel shows the commands to install
the agent there, with a token shown once. After the agent is running, **Connect** checks that
it holds the token and pins its certificate. The server's state (connected, unreachable, not
connected), host name, Docker version and last contact are shown.

### User Story 2 - Manage it like the panel's own server (P1)

1. Containers: pick the server; list, details, logs, start/stop/restart, settings per server.
2. Projects: choose the server when adding a project; deploys run on that server.
3. Databases: choose "connect from" that server; tests, lists and backups are done by its
   agent, so the database port need not be open to the outside.
4. Alerts and the bot name the server; the bot asks which server first when there are several.

### User Story 3 - Rename the menus (P2)

"Servers" (database instances) becomes "Databases"; "Servers" now means machines.

## Requirements

- **FR-001**: The token MUST be shown only once, stored encrypted, never sent over the network.
- **FR-002**: The panel MUST talk to a remote agent only over TLS with the certificate pinned on
  connect, after a challenge the agent can answer only with the token.
- **FR-003**: Requests MUST be signed (HMAC of time, method, path, pinned certificate); a
  signature for another certificate or older than 5 minutes MUST be refused.
- **FR-004**: A remote agent MUST NOT store database credentials; a dump MUST stop when the
  panel stops reading it.
- **FR-005**: A server with projects or databases MUST NOT be deleted; the local server MUST
  NOT be deleted or given a token.
- **FR-006**: Upgrading MUST keep everything on the local server, with the same alert keys.

## Success Criteria

- A database on another server is backed up through its agent and restores identically
  (MySQL 8.4, MariaDB 11.8).
- An agent with another certificate, a wrong token, or a skewed clock is refused with a clear
  reason.
