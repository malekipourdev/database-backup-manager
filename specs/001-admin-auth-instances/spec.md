# Feature Specification: Admin Authentication and Database Instance Management

**Feature Branch**: `001-admin-auth-instances`

**Created**: 2026-10-11

**Status**: Draft

**Input**: User description: "Admin authentication and MySQL instance management.
An admin logs in with username and password. The admin can add, edit and delete MySQL instances
(name, host, port, username, password, notes). Instances can be MySQL on the host machine or in a
Docker container reachable over the network. For each instance the admin can test the connection
and see a clear success/error message, and see the list of databases on that instance (excluding
system schemas by default), and mark which databases are included in backups. Passwords are never
shown again after saving."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Admin signs in and out (Priority: P1)

An admin opens the panel, is presented with a login page, enters their username and password,
and reaches the panel. Every other page and action is unavailable until they sign in. They can
sign out at any time, after which the panel is locked again.

**Why this priority**: Nothing else in the product may be reachable without authentication
(Constitution Principle I). Every later story depends on it.

**Independent Test**: Start a fresh installation, attempt to open any panel page or action
without signing in (blocked), sign in with valid credentials (succeeds), sign out (blocked
again).

**Acceptance Scenarios**:

1. **Given** the admin is not signed in, **When** they open any panel page or call any action,
   **Then** they are redirected to (or told to use) the login page and no data is shown.
2. **Given** the login page, **When** the admin enters the correct username and password,
   **Then** they are signed in and taken to the instance list.
3. **Given** the login page, **When** the admin enters a wrong username or wrong password,
   **Then** the same generic "invalid username or password" message is shown, without revealing
   which part was wrong.
4. **Given** a signed-in admin, **When** they sign out, **Then** their session ends and any
   further access requires signing in again.
5. **Given** a signed-in admin who has been inactive longer than the session timeout, **When**
   they perform an action, **Then** they are asked to sign in again.

---

### User Story 2 - Register and maintain database instances (Priority: P1)

The admin adds a database instance by providing a name, host, port, username, password and
optional notes. The instance may be a server on the host machine or one running in a container,
as long as it is reachable over the network from the panel. The admin can later edit any field or
delete the instance. After saving, the password is never displayed again; when editing, the admin
can leave the password untouched or replace it.

**Why this priority**: Instances are the foundation for every backup feature; without them the
product has nothing to protect.

**Independent Test**: Sign in, add an instance, see it in the list, edit its notes and port,
replace its password, confirm the password is never displayed, then delete it and confirm it
disappears.

**Acceptance Scenarios**:

1. **Given** a signed-in admin on the instance list, **When** they submit a new instance with
   name, host, port, username and password, **Then** the instance is saved and appears in the
   list showing name, host, port and username — but not the password.
2. **Given** an instance form, **When** a required field is missing or the port is not a number
   between 1 and 65535, **Then** the form is not saved and the invalid fields are indicated.
3. **Given** an existing instance named "prod", **When** the admin creates or renames another
   instance to "prod", **Then** saving is rejected with a message that the name is already used.
4. **Given** an existing instance, **When** the admin opens it for editing, **Then** the password
   field is empty with an indication that a password is stored, and saving with the field left
   empty keeps the existing password.
5. **Given** an existing instance, **When** the admin enters a new password and saves, **Then**
   the new password replaces the old one and is likewise never displayed.
6. **Given** an existing instance, **When** the admin chooses delete, **Then** they are asked to
   confirm, and on confirmation the instance and its database selections are removed.

---

### User Story 3 - Test the connection to an instance (Priority: P2)

For any instance — saved, or still being filled in on the form — the admin can test the
connection. The panel reports either success (including the detected server type, e.g. MySQL or
MariaDB, and its version) or a clear, specific error explaining what went wrong.

**Why this priority**: Admins need confidence that the panel can reach the server before relying
on it for backups, and need actionable errors to fix network or credential problems.

**Independent Test**: Test a reachable instance with correct credentials (success with server
type and version), then with a wrong password, a wrong host, and a closed port (each with a
distinct, understandable error).

**Acceptance Scenarios**:

1. **Given** a reachable server and correct credentials, **When** the admin tests the
   connection, **Then** a success message shows the server type and version, and these are
   recorded on the saved instance.
2. **Given** wrong credentials, **When** the admin tests the connection, **Then** an error states
   that authentication was rejected by the server.
3. **Given** a host name that cannot be resolved, **When** the admin tests, **Then** an error
   states that the host could not be found.
4. **Given** a host that is reachable but refuses or does not answer on the port, **When** the
   admin tests, **Then** an error states that the connection was refused or timed out, within the
   connection time limit.
5. **Given** an unsaved instance form, **When** the admin tests the connection, **Then** the test
   uses the values currently in the form without saving them.
6. **Given** any test result, **Then** the message never contains the password.

---

### User Story 4 - Choose which databases to back up (Priority: P2)

For a saved instance, the admin views the list of databases on that server. System schemas are
hidden by default, with an option to show them. The admin marks which databases are included in
backups and saves the selection. The selection is remembered and shown the next time the instance
is opened.

**Why this priority**: Backup jobs in later features need to know what to back up; this story
provides that input.

**Independent Test**: Open a saved, reachable instance with several user databases; confirm
system schemas are hidden; select two databases, save, reload the page and confirm the same two
are still selected.

**Acceptance Scenarios**:

1. **Given** a saved, reachable instance, **When** the admin opens its databases view, **Then**
   all user databases on the server are listed and system schemas are not shown.
2. **Given** the databases view, **When** the admin turns on "show system schemas", **Then**
   system schemas are also listed and visually marked as system schemas.
3. **Given** the databases view, **When** the admin marks databases as included and saves,
   **Then** the selection is stored and shown as included on later visits.
4. **Given** a database that was previously included but no longer exists on the server, **When**
   the admin opens the databases view, **Then** it is shown as "missing on server" (still
   included) so the admin can decide to remove it.
5. **Given** an instance that is unreachable, **When** the admin opens the databases view,
   **Then** a clear error is shown and the previously saved selection is still displayed.

---

### Edge Cases

- Repeated failed login attempts: after 5 consecutive failures for a username within 15 minutes,
  further attempts for that username are temporarily refused for 15 minutes, with a generic
  message.
- A connection test or database listing against a server that hangs MUST stop after the
  connection time limit and report a timeout, never leaving the page waiting indefinitely.
- Host values such as `localhost` or `127.0.0.1` refer to the panel's own environment; if the
  panel runs in a container this will not reach the host machine. The form shows a hint explaining
  how to address a server on the host or in another container.
- The configured database user lacks permission to list some databases: only visible databases
  are shown, and the view notes that the list depends on the user's privileges.
- A server with a very large number of databases (hundreds): the list remains usable, with a
  filter by name.
- The admin deletes an instance while a connection test for it is in progress: the deletion
  completes and the test result is discarded.
- Notes containing very long text: notes are limited to 2,000 characters.
- Special characters (including non-Latin characters) in names, notes, usernames and passwords
  are accepted and preserved exactly.

## Requirements *(mandatory)*

### Functional Requirements

**Authentication**

- **FR-001**: System MUST require an authenticated admin session for every page and every action
  except the login page and a data-free health check.
- **FR-002**: System MUST authenticate the admin with a username and password.
- **FR-003**: System MUST show the same generic message for any failed login, without revealing
  whether the username exists.
- **FR-004**: System MUST store the admin password only in a non-reversible (hashed) form.
- **FR-005**: System MUST end sessions on sign-out and after 30 minutes of inactivity.
- **FR-006**: System MUST temporarily refuse login attempts for a username after 5 consecutive
  failures within 15 minutes, for 15 minutes.
- **FR-007**: System MUST create the initial admin account from deployment configuration on first
  start when no admin account exists.

**Instance management**

- **FR-008**: Admin MUST be able to create an instance with: name (required, unique), host
  (required, hostname or IP address), port (required, 1–65535, default 3306), username
  (required), password (required on create), and notes (optional, up to 2,000 characters).
- **FR-009**: Admin MUST be able to view a list of all instances showing name, host, port,
  username, detected server type/version (if known), and result/time of the last connection test.
- **FR-010**: Admin MUST be able to edit any instance field. Leaving the password empty when
  editing MUST keep the stored password; entering a value MUST replace it.
- **FR-011**: Admin MUST be able to delete an instance after an explicit confirmation; deleting
  removes the instance and its database selections.
- **FR-012**: System MUST store instance passwords encrypted and MUST NEVER display or return a
  stored password after it is saved, nor include it in logs or error messages.
- **FR-013**: System MUST reach instances only over the network by host and port, whether the
  server runs on the host machine or in a container.

**Connection testing**

- **FR-014**: Admin MUST be able to test the connection of a saved instance and of unsaved form
  values.
- **FR-015**: A successful test MUST report the detected server type (MySQL or MariaDB) and
  version; for saved instances these MUST be recorded along with the test time and outcome.
- **FR-016**: A failed test MUST report a distinct, human-readable reason for at least these
  cases: host not found, connection refused, timeout, authentication rejected, and other server
  errors (with the server's message, stripped of any secret).
- **FR-017**: Connection tests and database listing MUST give up after 10 seconds and report a
  timeout.

**Database selection**

- **FR-018**: Admin MUST be able to view the databases on a saved instance as seen by the
  instance's configured user.
- **FR-019**: System schemas (`information_schema`, `performance_schema`, `mysql`, `sys`) MUST be
  hidden by default and shown, clearly marked, when the admin enables the option.
- **FR-020**: Admin MUST be able to mark any user database, and the `mysql` system schema, as
  included in backups, and save the selection. `information_schema`, `performance_schema` and
  `sys` MUST NOT be selectable.
- **FR-021**: The saved selection MUST persist and be shown on later visits, including when the
  server is unreachable.
- **FR-022**: A selected database that no longer exists on the server MUST be shown as "missing
  on server" and remain selected until the admin removes it.
- **FR-023**: Admin MUST be able to filter the database list by name.

**General**

- **FR-024**: All pages, messages and errors in this feature MUST be available in Persian (RTL)
  and English (LTR), and dates/times MUST be shown in the selected language's format.

### Key Entities

- **Admin Account**: The person operating the panel. Attributes: username, hashed password,
  failed-attempt tracking, last sign-in time.
- **Session**: An authenticated period of use by the admin. Attributes: start time, last activity
  time, ended flag.
- **Database Instance**: A MySQL or MariaDB server the panel can reach over the network.
  Attributes: name, host, port, username, encrypted password, notes, detected server type and
  version, last connection test time and outcome, created/updated times.
- **Database Selection**: A database name on an instance that the admin has marked as included
  in backups. Belongs to exactly one instance; unique per instance and name.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An admin can sign in and register a new instance, including a successful
  connection test, in under 2 minutes.
- **SC-002**: 100% of panel pages and actions other than login and health check are refused
  without a valid session (verified by checking every page and action).
- **SC-003**: A stored instance password never appears in any page, response, log entry or error
  message (verified by searching all of them for a known test password).
- **SC-004**: Every connection test returns a result within 12 seconds, including unreachable
  hosts.
- **SC-005**: For each of the five failure cases in FR-016, an admin can identify the cause from
  the message alone, without consulting logs.
- **SC-006**: The database list and selection work for servers with at least 500 databases,
  with the list shown within 5 seconds.
- **SC-007**: Connection testing, database listing and selection work against both MySQL 8 and
  the current MariaDB LTS release.
- **SC-008**: Every screen in this feature is fully usable in both Persian (right-to-left) and
  English (left-to-right), with no untranslated text.

## Assumptions

- There is a single admin account in the MVP; multiple admins and roles are out of scope.
  Its initial username and password are supplied in deployment configuration on first start.
- Changing the admin password from the UI and password reset are out of scope for this feature.
- Server type is detected automatically; the admin does not choose MySQL or MariaDB. The user
  description says "MySQL instances"; per the constitution, MariaDB servers are handled the same
  way.
- Encrypted (TLS) connections to target servers and SSH tunnels are out of scope for this
  feature; connections use the server's default settings.
- The configured database user is expected to have at least privileges to connect and list
  databases; required privileges for backups are covered by the backup feature.
- Deleting an instance in this feature only removes its configuration and selections. How
  existing backups and schedules of a deleted instance are treated is decided in the backup
  feature.
- Backups, schedules, retention and remote storage are out of scope for this feature.
