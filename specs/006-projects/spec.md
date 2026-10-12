# Feature Specification: Projects — deploy from git with docker compose (phase 2)

**Feature Branch**: `006-projects`
**Created**: 2026-10-12
**Status**: Implemented
**Input**: "Phase 2 of container management: register projects and deploy them from the panel
or the Bale bot."

## User Scenarios & Testing

### User Story 1 - Register a project (P1)

Name (also the compose project), repository (https or ssh), branch, compose file; private
access with an SSH deploy key or a token; environment variables; databases to back up before
each deploy and whether a failed backup stops it. Secrets are write-only.

### User Story 2 - Deploy and roll back (P1)

1. Deploy runs: backup → fetch → pull/build → up → check, with a live log.
2. A failure names the step and the reason (e.g. "worker: exited with code 3").
3. Any earlier successful deploy can be deployed again by its commit.
4. One deploy per project at a time; the result is an alert.

### User Story 3 - From the bot (P2)

Projects list, details, recent deploys; deploy confirmed with a TOTP code; the result is
reported in the chat that asked.

## Requirements

- **FR-001**: The agent runs only fixed git / docker compose commands as argument lists inside
  the project's directory; git is limited to https and ssh.
- **FR-002**: Tokens and keys MUST NOT appear on any command line, in API responses or logs;
  environment values MUST NOT appear in API responses or logs.
- **FR-003**: The panel's own compose project name MUST be refused.
- **FR-004**: Deploys left running by a panel restart MUST be marked failed.
- **FR-005**: Projects directory mounted at the same host path, so relative bind mounts work.

## Success Criteria

- **SC-001**: A real deploy from a git repository starts the services; a broken commit fails
  with the service named; redeploying the old commit restores it (integration test).
- **SC-002**: A value with quotes, `$`, backslash and newlines reaches the container unchanged.
- **SC-003**: No token or variable value appears in any API response or deploy log (tested).
