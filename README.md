# MySQL Backup Panel

A self-hosted web panel for managing backups of MySQL and MariaDB databases.
The UI is available in Persian (right-to-left) and English.

**Current status:**

- admin sign-in
- registering MySQL and MariaDB servers, testing connections and choosing databases
- **manual backups**: compressed, verified, with history, download and delete

Scheduling, S3 upload and retention policies are not built yet.

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

### Restoring a backup

Restore into an existing, empty database with the server's own client:

```bash
gunzip -c shop_2026-10-11_140804.sql.gz | mysql -h HOST -u root -p shop    # MySQL
gunzip -c shop_2026-10-11_140804.sql.gz | mariadb -h HOST -u root -p shop  # MariaDB
```

For bzip2 files use `bunzip2 -c`, and for uncompressed `.sql` files use `cat`.

The dump has no `CREATE DATABASE`/`USE`, so you can restore it under another name. One exception:
MariaDB stores trigger definitions exactly as written. A trigger that was created with a schema
prefix (`CREATE TRIGGER olddb.t …`) is recreated in that original schema. In that case, restore
under the original name.

## Security notes

- Every page and API endpoint requires the admin to be signed in, except the login page and
  `/api/health`.
- Stored database passwords are encrypted and are never returned by the API or written to logs.
  An edit form shows only that a password is stored.
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
uv run pytest -m integration   # real MySQL 8.4 and MariaDB 11.8 containers, backup + restore

cd frontend
npm run lint && npm run format:check && npm test && npm run build
```

Specifications, the plan and the task list are in [`specs/`](specs/). The project principles are
in [`.specify/memory/constitution.md`](.specify/memory/constitution.md).
