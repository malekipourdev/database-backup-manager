# Quickstart: Validating Admin Authentication and Instance Management

**Feature**: [spec.md](./spec.md) | **Contracts**: [contracts/openapi.yaml](./contracts/openapi.yaml)
| **Data model**: [data-model.md](./data-model.md)

This guide proves the feature works end to end. It assumes the layout in [plan.md](./plan.md).

## Prerequisites

- Docker (or Podman with compose support) for the stack and integration tests
- Python 3.12 + `uv`, Node.js 22 (for running tests outside containers)
- A Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## 1. Automated checks

```bash
# Backend: lint, format check, unit + API tests (SQLite)
cd backend
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest

# Backend integration tests against real MySQL 8.4 and MariaDB 11.8 containers
uv run pytest -m integration

# Frontend: lint, format, tests (includes fa/en key parity check)
cd ../frontend
npm ci
npm run lint && npm run format:check
npm test
```

**Expected**: all pass. Notable tests:
- route-coverage test → every route except `/api/health` and `/api/auth/login` returns 401
  without a session (SC-002)
- secret-leak test → a known instance password never appears in responses or logs (SC-003)
- connection tests parametrized over MySQL and MariaDB, including each failure code (SC-005,
  SC-007)

## 2. Run the stack

```bash
cp .env.example .env
# set MBP_ENCRYPTION_KEY, MBP_ADMIN_USERNAME, MBP_ADMIN_PASSWORD in .env
docker compose up -d --build
```

Open `http://localhost:8080`.

To have target servers to test with, start two throwaway servers reachable from the panel's
network (or on the host, reachable as `host.docker.internal`):

```bash
docker run -d --name t-mysql   -e MYSQL_ROOT_PASSWORD=secret1 -p 3307:3306 mysql:8.4
docker run -d --name t-mariadb -e MARIADB_ROOT_PASSWORD=secret2 -p 3308:3306 mariadb:11.8
docker exec t-mysql mysql -uroot -psecret1 -e "CREATE DATABASE shop; CREATE DATABASE blog;"
```

## 3. Manual validation scenarios

| # | Steps | Expected | Spec ref |
|---|-------|----------|----------|
| 1 | Open `/instances` without signing in | Redirected to login, no data | US1-1 |
| 2 | Sign in with wrong password | Generic "invalid username or password" | US1-3 |
| 3 | Fail 5 times, then use the correct password | Still refused for 15 min, same message | FR-006 |
| 4 | Sign in correctly (fresh username or after lockout) | Instance list shown | US1-2 |
| 5 | Add instance `host.docker.internal:3307`, root / secret1, test before saving | Success, "MySQL 8.4.x" | US3-1, US3-5 |
| 6 | Save it; reopen edit form | Password field empty, "password stored" hint | US2-4 |
| 7 | Change notes only, save; test connection | Still succeeds (password kept) | FR-010 |
| 8 | Test with wrong password / host `nosuchhost` / port 3399 | `auth_rejected` / `host_not_found` / `connection_refused`, each clearly worded | US3-2..4 |
| 9 | Test against a blackholed IP (e.g. `10.255.255.1`) | Timeout message within ~10 s | FR-017, SC-004 |
| 10 | Create a second instance with the same name (different case) | "Name already used" | US2-3 |
| 11 | Open Databases for the MySQL instance | `shop`, `blog` listed; system schemas hidden | US4-1 |
| 12 | Toggle "show system schemas" | 4 schemas shown and marked; only `mysql` checkable | FR-019/020 |
| 13 | Select `shop` + `blog`, save, reload | Both still selected | US4-3 |
| 14 | `DROP DATABASE blog` on the server, reload | `blog` shown "missing on server", still selected | US4-4 |
| 15 | `docker stop t-mysql`, reload Databases | Error shown; saved selection still visible | US4-5 |
| 16 | Repeat 5 and 11 with the MariaDB instance (port 3308) | "MariaDB 11.8.x"; same behaviour | SC-007 |
| 17 | Switch language to English and back to Persian | Full LTR ↔ RTL switch, no untranslated text, dates in locale format | FR-024, SC-008 |
| 18 | Search browser devtools network responses and `docker compose logs backend` for `secret1` | No occurrences | SC-003 |
| 19 | Sign out, press browser Back | Redirected to login | US1-4 |
| 20 | Delete the MariaDB instance (confirm dialog) | Removed from list | US2-6 |

## 4. Cleanup

```bash
docker rm -f t-mysql t-mariadb
docker compose down -v
```
