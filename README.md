# MySQL Backup Panel

A self-hosted web panel for managing backups of MySQL and MariaDB databases.
The UI is available in Persian (right-to-left) and English.

**Current status:** admin sign-in and database instance management. You can register MySQL and
MariaDB servers, test connections and choose which databases to back up. Running, scheduling,
uploading and pruning backups are not built yet.

## Quick start

Requirements: Docker with Compose v2 (Podman with `podman compose` also works, see below).

1. Create a `.env` file from the example:

   ```bash
   cp .env.example .env
   ```

2. Generate an encryption key and put it in `MBP_ENCRYPTION_KEY`:

   ```bash
   docker run --rm python:3.12-slim sh -c \
     "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
   ```

   This key encrypts the stored database passwords. Back it up: if you lose it, the stored
   passwords can't be decrypted and you'll have to re-enter them.

3. Set `MBP_ADMIN_USERNAME` and `MBP_ADMIN_PASSWORD`.

4. Start the panel:

   ```bash
   docker compose up -d --build
   ```

5. Open <http://localhost:8080> and sign in.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `MBP_ENCRYPTION_KEY` | (required) | Fernet key(s) used to encrypt stored passwords. Separate several keys with commas to rotate: the first one encrypts, all of them decrypt. The backend refuses to start without a valid key. |
| `MBP_ADMIN_USERNAME` / `MBP_ADMIN_PASSWORD` | `admin` / (none) | The initial admin account. These are **only read on first start**, when no admin exists yet. Changing them later has no effect. |
| `MBP_DATABASE_URL` | `sqlite:////data/mbp.db` | The panel's own database. Change only this URL to use PostgreSQL (`postgresql+psycopg://user:pass@host/db`) or MySQL (`mysql+pymysql://user:pass@host/db`). |
| `MBP_COOKIE_SECURE` | `true` | Send the session cookie over HTTPS only. Browsers accept it on `http://localhost`. If you open the panel over plain HTTP from another machine, set this to `false`, or sign-in will silently fail. |
| `MBP_HTTP_PORT` | `8080` | The host port the panel is published on. |

The frontend container is the only one with a published port. It serves the web app and forwards
`/api` requests to the backend over a private Compose network.

## Connecting to your database servers

The panel reaches database servers **over the network only**. It never uses the Docker socket.

| Where the server runs | Host to enter |
|-----------------------|---------------|
| Directly on the Docker host | `host.docker.internal`. The server must listen on an address the containers can reach, not only `127.0.0.1`. |
| In another container | Attach that container to the `mbp-net` network (`docker network connect mbp-net <container>`) and enter its container name. Alternatively, publish its port and use `host.docker.internal`. |
| On another machine | Its hostname or IP address. |

Don't enter `localhost`: inside the panel's container, `localhost` is the panel itself.

Give the panel's database user at least permission to connect and to see the databases it should
back up. Only databases visible to that user are listed.

**Podman:** `host-gateway` requires Podman 4.7 or later. On older versions, use the host's IP
address instead of `host.docker.internal`.

## Security notes

- Every page and API endpoint requires the admin to be signed in, except the login page and
  `/api/health`.
- Stored database passwords are encrypted and are never returned by the API or written to logs.
  An edit form shows only that a password is stored.
- After 5 failed sign-ins within 15 minutes, a username is locked for 15 minutes. The error message
  is the same whether the account doesn't exist, the password is wrong, or the account is locked.
- Sessions end after 30 minutes of inactivity.

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
