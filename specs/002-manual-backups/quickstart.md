# Quickstart: Validating Manual Backups

**Feature**: [spec.md](./spec.md) | **Contracts**: [contracts/openapi.yaml](./contracts/openapi.yaml)
| **Data model**: [data-model.md](./data-model.md)

This guide proves the feature works end to end. It assumes feature 001 is in place and the layout
in [plan.md](./plan.md).

## Prerequisites

- Docker, Python 3.12 + `uv`, Node.js 22
- Dump tools for running integration tests on the host (research §9):

  ```bash
  cd backend
  ./scripts/install-dump-tools.sh          # copies Oracle mysqldump 8.4 into backend/.tools/
  sudo apt-get install -y mariadb-client   # provides /usr/bin/mariadb-dump
  export MBP_MYSQLDUMP_PATH=$PWD/.tools/mysqldump MBP_MARIADB_DUMP_PATH=/usr/bin/mariadb-dump
  ```

## 1. Automated checks

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run pytest                    # unit + API, incl. fault injection with the fake dump tool
uv run pytest -m integration     # real backups + restore on mysql:8.4 and mariadb:11.8

cd ../frontend
npm run lint && npm run format:check && npm test && npm run build
```

**Expected**: all pass. Notable tests:

| Test | Proves |
|------|--------|
| fault injection (crash, denied, no marker, disk full, corruption, restart) | every failed run is `failed` with the right code, no temp or partial files remain (SC-003) |
| restore round-trip on MySQL and MariaDB | data, routines, triggers and events restore (SC-002, SC-009) |
| concurrent start requests for the same database | exactly one run created (SC-007) |
| 1 GiB fake dump | max RSS growth < 300 MB (SC-004) |
| process args inspection during a run | password never on the command line (Principle I) |

## 2. Run the stack

```bash
docker compose up -d --build
docker compose exec backend sh -c '/usr/local/bin/mysqldump --version && /usr/bin/mariadb-dump --version'
```

Expected: `mysqldump Ver 8.4.x … MySQL Community Server` and `mariadb-dump from 11.8.x-MariaDB`.

Then start two throwaway servers on the panel network:

```bash
docker run -d --name t-mysql   --network mbp-net -e MYSQL_ROOT_PASSWORD=secret1   mysql:8.0
docker run -d --name t-mariadb --network mbp-net -e MARIADB_ROOT_PASSWORD=secret2 mariadb:11.8
# seed: create databases shop and blog with a few rows, a procedure, a trigger and an event
```

Open the panel through the SSH tunnel or locally, and register both instances (host = container
name, port 3306). Mark `shop` and `blog` for backup on each.

## 3. Manual validation scenarios

| # | Steps | Expected | Spec ref |
|---|-------|----------|----------|
| 1 | Instance page → "Back up all marked databases" | 2 runs appear (queued/running → success) without reload | US1-1, SC-005 |
| 2 | Back up only `shop` | exactly 1 new run | US1-2 |
| 3 | Instance with nothing marked | "back up all" disabled, hint shown | US1-3 |
| 4 | Click "back up all" twice quickly | second click reports both databases skipped (already in progress) | US3-2/3 |
| 5 | Start backups on both instances | runs execute in parallel; extra runs show `queued` | US3-4 |
| 6 | `docker exec t-mysql …` revoke the user's SELECT, run backup | `failed`: missing privileges | US2-2 |
| 7 | `docker stop t-mariadb` during a large backup | `failed`: connection lost; no `.mbp-partial` left (`docker compose exec backend find /backups -name '*.mbp-partial'`) | US2-3 |
| 8 | `docker compose restart backend` during a backup | run becomes `failed` "interrupted"; no partial files | US2-6 |
| 9 | History: filter by instance + status=failed, then sort by size | correct subset and order | US4-1/2 |
| 10 | Download a successful run; `sha256sum` it | matches the checksum shown | US4-3 |
| 11 | `gunzip -c file.sql.gz \| docker exec -i t-mysql mysql -uroot -psecret1 restored` | restore succeeds | SC-002 |
| 12 | Delete a run (confirm) | row gone; file gone from `/backups` | US4-5 |
| 13 | Delete a file on disk by hand, reload history | run shows "file missing", download disabled | US4-7 |
| 14 | Settings: pattern without `{database}` | rejected with message | US5-3 |
| 15 | Settings: storage dir `../etc` | rejected | US5-5 |
| 16 | Instance override compression = none, back up | `.sql` file, compression "none" in history | US5-4 |
| 17 | `ps -ef` inside the backend container during a backup | no password in any command line | Principle I |
| 18 | Switch language fa ↔ en on history and settings | full translation, RTL/LTR, dates in locale format | SC-010 |
| 19 | Delete an instance that has backups | its runs stay in history under the old name; files remain | FR-027 |

## 4. Cleanup

```bash
docker rm -f t-mysql t-mariadb
```
