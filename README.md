# MySQL Backup Panel

A self-hosted web panel for managing backups of MySQL and MariaDB databases.
The UI is available in Persian (right-to-left) and English.

**Current status:** admin sign-in and database instance management. You can register MySQL and
MariaDB servers, test connections and choose which databases to back up. Running, scheduling,
uploading and pruning backups are not built yet.

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
GRANT SELECT, SHOW VIEW, TRIGGER, EVENT, LOCK TABLES, PROCESS ON *.* TO 'mbp_backup'@'%';
FLUSH PRIVILEGES;
```

For MariaDB, use `mariadb` instead of `mysql` in the `docker exec` command.

The panel lists only the databases this user can see. If a database is missing from the list,
check the user's privileges.

### Podman

`host-gateway` (used for `host.docker.internal`) requires Podman 4.7 or later. On older
versions, use the host's IP address instead. Connecting containers with
`podman network connect` works the same way as with Docker.

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
uv run pytest -m integration   # real MySQL 8.4 and MariaDB 11.8 containers (needs Docker)

cd frontend
npm run lint && npm run format:check && npm test && npm run build
```

Specifications, the plan and the task list are in [`specs/`](specs/). The project principles are
in [`.specify/memory/constitution.md`](.specify/memory/constitution.md).
