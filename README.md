# MySQL Backup Panel

A self-hosted web panel for managing backups of MySQL and MariaDB databases.
The UI is available in Persian (right-to-left) and English.

**Current status:**

- admin sign-in
- registering MySQL and MariaDB servers, testing connections and choosing databases
- **manual backups**: compressed, verified, with history, download and delete
- **scheduled backups**: cron schedules per server, with time zones
- **remote storage**: upload to AWS S3 or any S3-compatible service (MinIO, RustFS, Ceph,
  Wasabi, ArvanCloud, ...)
- **retention**: automatic deletion of old backups, locally and remotely
- **notifications and alerts**: failures, missing backups, low disk space and a daily summary,
  sent to Bale, Telegram and a signed webhook, with configurable rules and a history
- **Bale and Telegram bots**: manage backups from a chat with inline buttons

## Quick start

Requirements: a Linux server with Docker and Compose v2 (Podman with `podman compose` also
works, see [Podman](#podman)), plus `openssl`.

1. Create `.env` with a generated encryption key and admin password. Run this on the server,
   in the project directory:

   ```bash
   KEY=$(openssl rand -base64 32 | tr '+/' '-_')
   PASS=$(openssl rand -base64 18 | tr -d '/+=')

   cat > .env <<EOF
   MBP_ENCRYPTION_KEY=$KEY
   MBP_ADMIN_USERNAME=admin
   MBP_ADMIN_PASSWORD=$PASS
   MBP_DATABASE_URL=sqlite:////data/mbp.db
   MBP_BIND_ADDRESS=127.0.0.1
   MBP_HTTP_PORT=8080
   MBP_COOKIE_SECURE=true
   EOF

   chmod 600 .env
   echo "Admin password: $PASS"
   ```

   Write down the printed password. **Back up `MBP_ENCRYPTION_KEY` somewhere safe.** It
   encrypts the stored database passwords; if you lose it, you'll have to re-enter every
   password.

2. Start the panel:

   ```bash
   docker compose up -d --build
   ```

3. Check that the panel listens on the loopback interface only:

   ```bash
   ss -tlnp | grep 8080   # expect 127.0.0.1:8080, not 0.0.0.0:8080
   ```

4. Open the panel through an SSH tunnel (see the next section) and sign in.

5. After your first successful sign-in, you can delete the `MBP_ADMIN_PASSWORD` line from `.env`.
   It is only used to create the admin on first start.

## Accessing the panel over an SSH tunnel

By default the panel is published on `127.0.0.1:8080` on the server. It isn't reachable from
the network, so you don't need a domain, TLS certificate or open firewall port.

Only one port needs forwarding: the panel's HTTP port (`MBP_HTTP_PORT`, default `8080`). The
backend has no published port; the frontend forwards `/api` requests to it inside the Compose
network. Database servers don't need forwarding either, because the panel connects to them from
the server.

On your own computer, run:

```bash
ssh -N -L 8080:127.0.0.1:8080 user@SERVER_IP
```

Then open <http://localhost:8080>. If port 8080 is already taken on your computer, pick another
local port, for example `-L 18080:127.0.0.1:8080` and <http://localhost:18080>.

`MBP_COOKIE_SECURE=true` works here even without HTTPS, because browsers treat
`http://localhost` as a secure origin.

**Why not just block the port with a firewall?** Docker writes its own iptables rules for
published ports, and these bypass firewalls such as ufw. A port published on `0.0.0.0` is
exposed even when ufw denies it. Keep `MBP_BIND_ADDRESS=127.0.0.1` unless a TLS reverse proxy or
a trusted private network sits in front of the panel.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `MBP_ENCRYPTION_KEY` | (required) | Fernet key(s) used to encrypt stored passwords. Separate several keys with commas to rotate: the first one encrypts, all of them decrypt. The backend refuses to start without a valid key. |
| `MBP_ADMIN_USERNAME` / `MBP_ADMIN_PASSWORD` | `admin` / (none) | The initial admin account. These are **only read on first start**, when no admin exists yet. Changing them later has no effect. |
| `MBP_DATABASE_URL` | `sqlite:////data/mbp.db` | The panel's own database. Change only this URL to use PostgreSQL (`postgresql+psycopg://user:pass@host/db`) or MySQL (`mysql+pymysql://user:pass@host/db`). |
| `MBP_BIND_ADDRESS` | `127.0.0.1` | The server address the panel is published on. With the default, the panel is reachable only from the server itself. |
| `MBP_HTTP_PORT` | `8080` | The server port the panel is published on. |
| `MBP_BACKUP_CONCURRENCY` | `2` | Maximum number of backups running at the same time. Further ones wait in a queue and start in order. |
| `MBP_RETENTION_INTERVAL_MINUTES` | `60` | How often the retention policy is applied to all backups, in addition to after every backup. `0` turns the periodic run off. |
| `MBP_MONITOR_INTERVAL_MINUTES` | `10` | How often missing backups and disk space are checked for alerts. `0` turns these checks off. |
| `MBP_BOTS_ENABLED` | `true` | Master switch for the Bale and Telegram bots, for example `false` on a standby copy of the panel. Bots are configured in the panel. |
| `MBP_SCHEDULE_MISFIRE_GRACE_SECONDS` | `300` | A scheduled backup whose time passed while the panel was down still starts if the panel is back within this many seconds. Later ones are skipped until the next scheduled time. |
| `MBP_COOKIE_SECURE` | `true` | Send the session cookie over HTTPS only. This works over an SSH tunnel, because the browser sees `http://localhost`. Set it to `false` only if you open the panel over plain HTTP using a non-localhost address, or sign-in will silently fail. |

## Connecting to your database servers

The panel reaches database servers **over the network only**. It never uses the Docker socket.
Don't enter `localhost` or `127.0.0.1` as the host: inside the panel's container, they refer to
the panel itself.

### A server running in a Docker container

Put the panel and the database container on the same Docker network, then enter the
**container name** as the host and the **container's internal port** (normally `3306`) as the
port. Don't use the port it publishes on the host.

1. Start the panel first (this creates the `mbp-net` network), then attach the database
   container to it:

   ```bash
   docker network connect mbp-net <database-container-name>
   ```

   This doesn't restart the database or change its existing networks and published ports.

2. In the panel, enter:

   | Field | Value |
   |-------|-------|
   | Host | the container name, e.g. `mysql_db` |
   | Port | `3306` (the internal port) |

**Example.** For a container listed by `docker ps` as
`127.0.0.1:34507->3306/tcp   mysql_db`, enter host `mysql_db` and port `3306`, not `34507`.
Its published port `127.0.0.1:34507` is bound to the server's loopback interface, which the panel
container can't reach, not even through `host.docker.internal`.

**Keep the connection after the database container is recreated.** `docker network connect` is
lost when the database container is recreated, for example by `docker compose down && up` in its
own project. Either run the command again afterwards, or make it permanent in the database
project's `docker-compose.yml`:

```yaml
services:
  mysql_db:
    networks:
      - default
      - mbp-net

networks:
  mbp-net:
    external: true
```

To see which networks a container is attached to:

```bash
docker inspect <container> --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}'
```

### A server installed directly on the host

Enter `host.docker.internal` as the host and the server's port. The server must listen on an
address the containers can reach. A server that listens only on `127.0.0.1` isn't reachable;
check `bind-address` in the MySQL/MariaDB configuration.

### A server on another machine

Enter its hostname or IP address and port. That machine's firewall must allow connections from
this server.

### A dedicated database user for the panel

Avoid using `root`. Create a dedicated user with the privileges needed for backups:

```bash
docker exec -it <database-container-name> mysql -uroot -p
```

```sql
CREATE USER 'mbp_backup'@'%' IDENTIFIED BY 'a-strong-password';
GRANT SELECT, SHOW VIEW, TRIGGER, EVENT, LOCK TABLES ON *.* TO 'mbp_backup'@'%';
FLUSH PRIVILEGES;
```

`PROCESS` is not needed: the panel dumps with `--no-tablespaces`. These grants are tested
against MySQL 8.0/8.4 and MariaDB 11.8.

For MariaDB, use `mariadb` instead of `mysql` in the `docker exec` command.

The panel lists only the databases this user can see. If a database is missing from the list,
check the user's privileges.

### Podman

`host-gateway` (used for `host.docker.internal`) requires Podman 4.7 or later. On older
versions, use the host's IP address instead. Connecting containers with
`podman network connect` works the same way as with Docker.

## Backups

On an instance's page you can:

- back up **all databases marked for backup**, or
- back up **one database**, which doesn't need to be marked.

Each database gets its own file. You can follow progress on the instance page and on the
**Backups** page, which lists every run. On that page you can filter by instance, database, status
and date, sort the results, download files and delete backups.

### How a backup is made

1. The panel connects to the server and detects whether it is MySQL or MariaDB.
2. It runs the matching dump tool:
   - Oracle `mysqldump` 8.4 for MySQL
   - `mariadb-dump` for MariaDB
   - The options are `--single-transaction --quick --routines --triggers --events --hex-blob --no-tablespaces`, plus `--set-gtid-purged=OFF` for MySQL.
   - The password is passed only through a temporary file readable by the panel alone. It never
     appears on a command line or in the environment.
3. The output is compressed as it streams (gzip, bzip2 or none) into a hidden temporary file. The
   panel never holds the dump in memory, so large databases work.
4. The file is **verified**: SHA-256 checksum, full decompression, and the dump's
   `-- Dump completed` marker.
5. Only then does it get its final name. Failed or interrupted backups never leave a file, and are
   shown as failed with the reason.

Two backups of the same database never run at the same time. The backend must run as a
**single process** (the default), because the backup queue lives in memory.

### Where files are stored

Backups are stored in the `mbp-backups` Docker volume, mounted at `/backups` in the backend
container. To list them:

```bash
docker compose exec backend find /backups -type f
```

To keep them in a host directory instead, replace `mbp-backups:/backups` in
`docker-compose.yml` with a bind mount such as `./backups:/backups`. Then make the directory
writable by the panel's user:

```bash
mkdir -p backups && sudo chown 10001:10001 backups
```

### Settings

Change these under **Settings**. Each instance can override any of them on its own page:

- **Storage directory**: relative to the backup volume.
- **File name pattern**: the default is `{instance}/{database}_{date}_{time}`.
  - Available placeholders: `{instance}`, `{database}`, `{date}`, `{time}`, `{datetime}`,
    `{server_type}`.
  - `/` creates subfolders.
  - Times are in UTC.
  - The extension is added automatically, and an existing file is never overwritten.
- **Compression**: gzip (the default), bzip2 or none.

Changing settings affects new backups only.

### Scheduled backups

Add schedules on a server's page or under **Schedules**. Each schedule has:

- a **cron expression** with five fields: `minute hour day-of-month month day-of-week`. There
  are presets for hourly, daily, weekly and monthly backups. For example, `30 1 * * *` runs
  every day at 01:30, and `0 */6 * * *` runs every six hours.
- a **time zone**, such as `UTC` or `Asia/Tehran`. The form shows the next five run times.
- what to back up: **all databases marked for backup**, or **one database**.

Scheduled backups go through the same queue as manual ones and appear in the history marked
"Scheduled". If a backup of a database is still running when its schedule fires again, that
database is skipped. Each schedule shows the result of its last run, for example "No databases
marked".

The scheduler runs inside the backend process, so the backend must stay a single process.

### Remote storage (S3)

Under **Settings → Remote storage**, enter the endpoint, bucket, key prefix and access keys,
then use **Test connection**. The test checks that the panel can write to and delete from the
bucket.

- Leave **Endpoint URL** empty for AWS S3. For other services, enter their URL, for example
  `https://s3.ir-thr-at1.arvanstorage.ir` or `http://minio:9000`.
- **Path-style addressing** is needed by most self-hosted services (MinIO, RustFS, Ceph).
- The secret key is stored encrypted, like database passwords, and is never shown again.

When **Upload backups to remote storage** is on, every verified backup is uploaded after it is
created. A server can override this on its page: **Always**, **Never**, or the global setting.
Large files are uploaded in 64 MiB parts, so memory use stays small. The panel then checks the
size of the stored object. The object key is `<prefix>/<file path>`, and the file's SHA-256 is
stored in its `sha256` metadata.

A failed upload doesn't fail the backup: the local file is kept, the run shows "Upload failed"
with the reason, and **Retry upload** tries again. If the local file has been removed (for
example by retention), **Download** streams the remote copy instead.

**Remote copies are protected for 7 days.** The panel never deletes a remote copy, by retention or
by hand, until 7 days after it was uploaded. This guards against a mistake, or someone with panel
access, wiping the offsite copies along with the local ones. Within those 7 days a copy can only be
deleted in the storage provider itself, for example in the ArvanCloud console.

**Deleting a backup** in the panel or the bot deletes only the file on the server by default. The
remote copy is kept, and the backup stays in the history so it can still be downloaded. To delete
the remote copy too, tick **Also delete the remote copy**. While the copy is protected, the box is
disabled and shows the date it becomes deletable.

For protection that holds even if the panel itself is compromised, also enable *Object Lock* or a
retention or lifecycle rule on the bucket in your storage provider.

To use an access key with minimal permissions, allow `s3:PutObject`, `s3:GetObject`,
`s3:DeleteObject` and `s3:ListBucket` on the bucket.

### Retention

Under **Settings → Retention**, set separate rules for local files and remote copies:

- **Keep the last N** backups of each database.
- **Delete after N days**.

Leave a field empty to turn that rule off. When both rules are set, a backup is deleted if it
breaks either one. **The newest backup of each database is never deleted**, even if it is older
than the age limit. Only successful backups are affected. **Remote copies younger than 7 days are
never deleted**, whatever the policy, so the remote age limit can't be set below 7 days.

Retention runs after every backup (for that database) and every hour for all backups. A server
can have its own policy on its page. **Preview and apply now** lists what would be deleted under
the saved policy before deleting anything.

The backup's record stays in the history: it shows when retention removed the local file, or
that the remote copy was deleted. If a remote copy can't be deleted (for example, the storage is
unreachable), the error is shown on the run and the deletion is retried on the next run.

### Notifications and alerts

Under **Notifications**, choose which events raise an alert and where each one goes: Bale,
Telegram and/or a webhook.

| Event | Severity | When |
|-------|----------|------|
| Backup failed | error | A backup ends with an error. |
| Upload failed | error | A backup can't be uploaded to remote storage. |
| No recent backup | error | A database marked for backup has had no successful backup for longer than the limit (default 26 hours). |
| Low disk space | warning (error below half the limit) | Free space in the backup area falls below the limit (default 10%). |
| Schedule did not run | warning | A schedule fires but can't start, for example because no databases are marked. |
| Retention could not delete | warning | An old remote copy can't be deleted. |
| Backup succeeded | info | After every successful backup. |
| Back to normal | info | A "no recent backup" or "low disk space" alert has cleared. |
| Daily summary | info | Every day at the time you set: successes, failures, uploads, missing backups and free space. |

- **Cooldown:** the same alert about the same database is sent at most once per cooldown period
  (default 60 minutes). Repeats are still recorded.
- **Condition alerts:** "No recent backup" and "Low disk space" are announced once when the
  problem starts and once when it clears, not on every check. The checks run every 10 minutes.
- **History:** every alert is kept for 90 days, with where it was delivered and whether the
  cooldown held it back. **Send a test alert** checks all channels at once.
- **Webhook:** each alert is POSTed as JSON:

  ```json
  {"event": "backup_failed", "severity": "error", "subject": "backup_failed:1:shop",
   "message": "Backup of “shop” on “prod” failed: ...", "params": {...},
   "run_id": 42, "created_at": "2026-10-11T08:00:00+00:00", "source": "mysql-backup-panel"}
  ```

  With a signing secret, the `X-MBP-Signature` header is `sha256=` followed by the
  HMAC-SHA256 of the request body, so the receiver can check that the alert came from the
  panel.

### Bale and Telegram bots

Manage backups from a chat. Bots connect out to the messenger (long polling), so the panel still
needs no public address, domain or open port.

1. In Bale, open `@botfather` (in Telegram, `@BotFather` and `/newbot`), create a bot and copy
   its token.
2. Under **Bots**, turn the bot on, paste the token, use **Test token**, then **Save**. The badge
   shows "Connected as @yourbot" once it is running.
3. Register who may use it under **Bot admins**, in either of two ways:
   - Enter the person's **numeric user ID**. If they send any message to the bot, it replies
     with their ID.
   - Use **Create link code**. The person sends the one-time code to the bot (valid for 15
     minutes) and is registered automatically.

**What the bot can do** (inline buttons, Persian or English per admin):

- **Status:** servers, running backups, the last 24 hours, the last successful backup, free disk
  space, remote storage and the next scheduled run.
- **Servers:** details, test the connection, back up all marked databases (asks for
  confirmation) or pick one database.
- **Backups:** history, details, retry an upload, delete (asks for confirmation), and receive
  the file, if you allow it.
- **Schedules:** enable, disable, run now.
- **Retention:** preview what would be deleted, then apply.
- **Notifications and language:** each admin picks their alert level (everything, warnings and
  errors, errors only, off) and their language.

**Security:**

- Only registered, active admins get any answer, and only in private chats; group messages are
  ignored. Everyone else only sees their own numeric ID.
- Server passwords and storage keys can't be entered or shown through the bot. Manage servers and
  credentials in the panel.
- **Sending backup files through the bot is off by default:** it copies your database to the
  messenger's servers. If you turn it on, set a size limit; Bale and Telegram limit bot uploads
  (about 20 MB and 50 MB).
- Bot tokens are stored encrypted and are never shown again or written to logs. Every bot action
  is logged with the admin's ID.
- If Telegram is blocked on your server, set an `http://`, `https://` or `socks5://` proxy under
  **Advanced settings**. Proxy URLs with a username and password aren't accepted, because the URL
  is stored in plain text.

### Restoring a backup

Restore into an existing, empty database with the server's own client:

```bash
gunzip -c shop_2026-10-11_140804.sql.gz | mysql -h HOST -u root -p shop    # MySQL
gunzip -c shop_2026-10-11_140804.sql.gz | mariadb -h HOST -u root -p shop  # MariaDB
```

For bzip2 files use `bunzip2 -c`, and for uncompressed `.sql` files use `cat`.

To restore a backup that only exists in remote storage, download it from the **Backups** page
(the panel streams it from the bucket), or fetch it with any S3 client, for example
`aws s3 cp s3://BUCKET/PREFIX/prod/shop_2026-10-11_140804.sql.gz .`.

The dump has no `CREATE DATABASE`/`USE`, so you can restore it under another name. One exception:
MariaDB stores trigger definitions exactly as written. A trigger that was created with a schema
prefix (`CREATE TRIGGER olddb.t …`) is recreated in that original schema. In that case, restore
under the original name.

## Security notes

- Every page and API endpoint requires the admin to be signed in, except the login page and
  `/api/health`.
- Stored database passwords and the S3 secret key are encrypted and are never returned by the API
  or written to logs. An edit form shows only that a secret is stored.
- Database names that start with `-` or contain control characters are rejected, so a name can
  never be read as an option by the dump tool.
- Bale/Telegram bots answer only admins registered in the panel, only in private chats (see
  [Bale and Telegram bots](#bale-and-telegram-bots)). Bot tokens and the webhook secret are
  stored encrypted.
- After 5 failed sign-ins within 15 minutes, a username is locked for 15 minutes. The error message
  is the same whether the account doesn't exist, the password is wrong, or the account is locked.
- Sessions end after 30 minutes of inactivity.
- By default the panel is reachable only from the server itself (see
  [Accessing the panel over an SSH tunnel](#accessing-the-panel-over-an-ssh-tunnel)).

## Development

```bash
# Backend (http://localhost:8000)
cd backend
uv sync
export MBP_ENCRYPTION_KEY=... MBP_ADMIN_USERNAME=admin MBP_ADMIN_PASSWORD=... \
       MBP_DATABASE_URL=sqlite:///./dev.db MBP_COOKIE_SECURE=false
uv run alembic upgrade head
uv run uvicorn mbp.main:app --reload

# Frontend (http://localhost:5173, proxies /api to the backend)
cd frontend
npm ci
npm run dev
```

### Tests and checks

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run pytest                  # unit and API tests (SQLite)
./scripts/install-dump-tools.sh   # copies mysqldump/mariadb-dump from the official images
uv run pytest -m integration   # real MySQL 8.4, MariaDB 11.8 and S3 (RustFS) containers

cd frontend
npm run lint && npm run format:check && npm test && npm run build
```

Specifications, the plan and the task list are in [`specs/`](specs/). The project principles are
in [`.specify/memory/constitution.md`](.specify/memory/constitution.md).
