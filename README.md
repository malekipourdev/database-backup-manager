# DevOps Manager

A self-hosted DevOps panel for one server or several: database backups, Docker containers,
deploys from git, alerts, and control from Bale and Telegram. It started as a backup panel for
MySQL and MariaDB, which is still at its core. The UI is available in Persian (right-to-left)
and English.

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
- **two-step sign-in** with Google Authenticator or any other TOTP app (optional)
- **containers** (optional): see the server's Docker containers, their usage and logs, start,
  stop and restart them from the panel or a bot, and get alerts when one goes down
- **web servers** (optional): the nginx and Apache on each server: domains, status, reload,
  configuration with versions and safe editing, logs, new sites from templates, maintenance
  mode, Let's Encrypt certificates, health checks and expiry alerts
- **projects** (optional): deploy applications from git with docker compose, from the panel
  or a bot, with a backup of their databases before every deploy and one-click rollback
- **several servers**: connect other machines to the same panel through a small agent, then
  manage their containers, deploy projects to them and back up their databases from one place
- **overview**: a home page with the current server's health, the last day's backups, its
  containers and deploys, and everything that needs attention
- **organized menu**: folding groups from the widest scope down (server management, applications,
  databases & backups, alerts & chat access, system), a **Go to…** search (`Ctrl+K`), keyboard and screen-reader friendly
- **built-in guide**: a **Help** page in the panel (Persian and English) that explains every
  feature by topic, with search; the "?" next to a page's title opens its article

## Quick start

Requirements: a Linux server with Docker and Compose v2 (Podman with `podman compose` also
works, see [Podman](#podman)), plus `openssl`.

1. Get the code onto the server:

   ```bash
   git clone https://github.com/malekipourdev/database-backup-manager.git mysql-backup-panel
   cd mysql-backup-panel
   ```

   For a private repository, use a GitHub deploy key or a personal access token, or copy the
   folder to the server with `scp`/`rsync`.

2. Create `.env` with a generated encryption key and admin password. Run this on the server,
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

3. Start the panel:

   ```bash
   docker compose up -d --build
   ```

4. Check that the panel listens on the loopback interface only:

   ```bash
   ss -tlnp | grep 8080   # expect 127.0.0.1:8080, not 0.0.0.0:8080
   ```

5. Open the panel through an SSH tunnel (see the next section) and sign in.

6. After your first successful sign-in, you can delete the `MBP_ADMIN_PASSWORD` line from `.env`.
   It is only used to create the admin on first start.

Optional features you can turn on later: [remote storage](#remote-storage-s3) (with a
[step-by-step ArvanCloud guide](#arvancloud-object-storage-step-by-step)), [bots](#bale-and-telegram-bots),
[two-step verification](#two-step-verification-google-authenticator),
[containers](#containers) and [projects](#projects-deploy-from-git). To keep the panel up to date and safe, see
[Maintenance](#maintenance).

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
| `COMPOSE_PROFILES` | (none) | Set to `containers` to run the agent for [container management](#containers). |
| `MBP_DOCKER_GID` | `999` | The group ID of the Docker socket on the server (`stat -c %g /var/run/docker.sock`); the agent needs it to use the socket. |
| `MBP_DOCKER_SOCKET` | `/var/run/docker.sock` | The Docker socket on the server, e.g. for rootless Docker or Podman (`/run/user/1000/podman/podman.sock`). |
| `MBP_PROJECTS_DIR` | `/opt/mbp-projects` | Where the agent checks out [projects](#projects-deploy-from-git) on the server. It is mounted at the same path in the agent, so relative bind mounts in their compose files work. Must be writable by uid 10001. |
| `MBP_CONTAINER_MONITOR_SECONDS` | `60` | How often containers and server resources are checked for alerts. `0` turns these checks off. |
| `MBP_AGENT_REPO_URL` | this repository | The git URL shown in the commands that install the agent on [another server](#servers). |
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

Two ways:

- **Through that machine's agent (recommended).** [Connect the machine](#servers), choose it
  as the **current server** (the card at the bottom of the menu), and add the database there.
  Its agent tests, lists and dumps
  the database on that machine and streams the backup to the panel; the database port never
  has to be open to the outside. The host is then as seen from that machine: `127.0.0.1` for
  a database published on it, or a container's name for one in a container there.
- **Directly.** Add the database on the panel's own server and enter the other machine's
  hostname or IP address and port. That machine's firewall must allow
  connections from this server.

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

Change these under **Storage & retention**. Each instance can override any of them on its own page:

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

Under **Storage & retention → Remote storage**, enter the endpoint, bucket, key prefix and access keys,
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

#### ArvanCloud Object Storage, step by step

1. In the ArvanCloud console, open **Object Storage** and create a bucket (for example
   `airplus`). Keep it **private**.
2. Under **Access keys**, create a key pair and copy the **Access key** and **Secret key**.
   The secret is shown once. Never paste it into a chat or a ticket; enter it only in the panel.
3. Note the **endpoint** of the bucket's region, shown in the console, for example
   `https://s3.ir-thr-at1.arvanstorage.ir` (Tehran). The region name is the middle part, for
   example `ir-thr-at1`.
4. In the panel, open **Storage & retention → Remote storage** and fill in:

   | Field | Value |
   |-------|-------|
   | Endpoint URL | `https://s3.ir-thr-at1.arvanstorage.ir` (your region's endpoint) |
   | Region | `ir-thr-at1` |
   | Bucket | `airplus` (the bucket name only, no `s3://` and no slashes) |
   | Key prefix | `mysql-backup` (a "folder" inside the bucket; optional) |
   | Access key / Secret key | from step 2 |
   | Use path-style addressing | on |

   An address like `s3://airplus/mysql-backup/` means bucket `airplus`, prefix
   `mysql-backup`.
5. Use **Test connection**. It must succeed before you go on.
6. Turn on **Upload backups to remote storage** and **Save**. Without this switch, backups
   stay local only, even when the connection test succeeds.
7. Run a backup. Its row shows the remote status ("Stored remotely" when done), and the file
   appears in the bucket under the prefix, with the same path and name as on the server (see
   **Storage & retention → Backup settings** for the naming pattern).

If the test succeeds but nothing is uploaded, check step 6 and the server's own setting
(**Always / Never / Global setting**) on its page.

### Retention

Under **Storage & retention → Retention**, set separate rules for local files and remote copies:

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

Under **Alerts**, choose which events raise an alert and where each one goes: Bale,
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

**What the bot can do** (inline buttons, Persian or English per admin). The menu is grouped like
the panel's:

- **Overview:** databases, running backups, the last 24 hours, the last successful backup, free
  disk space, remote storage, the next scheduled run, connected servers and failed deploys.
- **Databases & backups:**
  - **Databases:** details, test the connection, back up all marked databases (asks for
    confirmation) or pick one database.
  - **Latest backups:** history, details, retry an upload, delete (asks for confirmation), and
    receive the file, if you allow it.
  - **Schedules:** enable, disable, run now.
  - **Retention:** preview what would be deleted, then apply.
- **Projects:** last deploys, and deploys confirmed with a Google Authenticator code (see
  [Projects](#projects-deploy-from-git)).
- **Containers:** state, usage and logs (if you allow it); start, stop and restart, each
  confirmed with a Google Authenticator code (see [Containers](#containers)).
- **Servers:** each connected server's state, with its containers, resources (CPU, RAM, disk),
  projects and databases.
- **Alerts and language:** each admin picks their alert level (everything, warnings and errors,
  errors only, off) and their language.
- **Help:** what each section does.

**Commands:** `/menu`, `/status`, `/backups`, `/projects`, `/containers`, `/servers`,
`/settings` and `/help`. The bot registers them in the messenger's command menu (Persian, and
English for users whose app is in English).

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

## Containers

See and control the Docker containers on the panel's server: their state, CPU and memory use,
logs, and start, stop and restart, from the panel and from the Bale or Telegram bot. Alerts
tell you when a container goes down, keeps restarting, fails its health check, uses too much,
or when the server runs low on memory or disk.

This is **off by default**. It needs one more container, the **agent**: the only part of the
panel that can talk to Docker (`docker.sock`). Access to `docker.sock` is equivalent to root
on the server, so the agent is kept small and strict:

- It listens only on the panel's internal Docker network, publishes no port, and answers only
  the panel's backend (with a secret derived from `MBP_ENCRYPTION_KEY`).
- It knows a fixed list of operations: list, details, usage, logs, start, stop, restart. It
  can't run commands in containers, create or remove containers, or pull images.
- It never returns the values of environment variables (they often hold passwords); the panel
  shows their names only.
- It refuses to stop or restart the panel's own containers.
- It runs with a read-only filesystem, no Linux capabilities and `no-new-privileges`.

### Turn it on

In the panel's folder on the server:

```bash
echo "COMPOSE_PROFILES=containers" >> .env
echo "MBP_DOCKER_GID=$(stat -c %g /var/run/docker.sock)" >> .env
sudo mkdir -p /opt/mbp-projects && sudo chown 10001:10001 /opt/mbp-projects   # for projects
docker compose up -d --build
```

Then open **Containers** in the panel. If it says the agent may not use `docker.sock`, check
`MBP_DOCKER_GID`. For rootless Docker or Podman, also set `MBP_DOCKER_SOCKET` to the socket's
path.

To turn it off again, remove `COMPOSE_PROFILES=containers` from `.env` and run
`docker compose up -d --remove-orphans`.

### What you can do

- **Containers tab:** every container, grouped by compose project, with problems first;
  state, health, uptime or exit code, CPU, RAM and automatic restarts, refreshed every 5
  seconds. Filters (running, problems, stopped) and search. Server CPU, RAM and Docker disk
  at the top.
- **Details:** image, ports, networks, volumes, restart policy, the last health check output,
  and the names of the environment variables. **Logs:** the last 100 to 5,000 lines, stdout
  and stderr marked, with filter, follow and download.
- **Start, stop, restart.** Stop and restart ask for confirmation.
- **Activity tab:** every start, stop and restart asked for, from the panel or a bot, by whom,
  and the result.
- **Settings tab:**
  - **Read-only mode:** watch only; no container can be started, stopped or restarted.
  - **Hidden containers:** names or patterns (`vault*`) the panel doesn't show at all.
  - **Locked containers:** shown, but never controlled from the panel or the bots.
  - **Logs in the bots:** off by default, because logs can hold sensitive data and showing
    them in a chat copies them to the messenger's servers.
  - **Alerts:** which containers are watched, and the limits for container CPU and RAM,
    restart loops, server RAM and Docker disk. `0` turns a check off.

### Alerts

Checked every minute (`MBP_CONTAINER_MONITOR_SECONDS`). Each alert is sent once when the
problem starts and once when it clears. Turn each one on or off, and choose its channels, on
the **Notifications** page.

| Alert | When |
|-------|------|
| Container went down | It exited with an error, or was killed for running out of memory. Not when it was stopped on purpose (`docker stop`, or from the panel). |
| Restart loop | Its restart policy restarted it 3 times within 10 minutes (adjustable). |
| Unhealthy | Its health check fails. |
| High usage | Its CPU or RAM (as % of its limit) stays above the limit for two checks in a row. |
| Server resources | The server's RAM or Docker disk is above the limit. |
| Agent unreachable | The agent worked and then stopped answering. |

### From the bot

**Containers** in the bot menu lists them with problems first, shows details, usage and the
server status, and, if allowed in the settings, the last 30 log lines.

**Start, stop and restart from the bot need a Google Authenticator code.** The bot asks for
the current 6-digit code of a panel account that has [two-step
verification](#two-step-verification-google-authenticator) turned on, and the code must arrive
within 2 minutes. If nobody has turned on two-step verification, containers can only be
watched from the bot. After 5 wrong codes in 15 minutes, container control from the bot is
blocked for 15 minutes. So a stolen or borrowed messenger account can't stop your services.

## Web servers (nginx, Apache)

**Web servers** (under Server management) manages the nginx and Apache installed on the
current server:

- **Domains:** every `server_name` / `ServerName` and `ServerAlias`, with ports, HTTPS and the
  days its certificate has left, what it serves (a proxy address with the servers of an nginx
  `upstream`, PHP-FPM, a redirect or a folder) and the file and line it is defined in. Sites
  in `sites-available` that are not enabled are listed under "All".
- **Status:** running or not, version, since when, and the last reload; buttons to test the
  configuration, reload and restart (always after a successful test).
- **A site's drawer:** its configuration with colours and the line of the site highlighted;
  editing; the previous versions with one-click restore; its access and error logs; enable,
  disable and maintenance mode (a 503 page for the same names and certificate).
- **New site** from a template: reverse proxy (to an address or a container's published
  port), PHP through PHP-FPM, static files, or a redirect.
- **Let's Encrypt:** get or renew a certificate with certbot (installed from the panel with
  apt/dnf/yum if missing); the card shows whether automatic renewal (`certbot.timer` or cron)
  is active.
- **Health checks:** the panel requests chosen addresses regularly and records the status
  code and response time; a site that fails several checks in a row is an alert, and its
  recovery too. Certificates that expire within 14 days (configurable) are alerts as well.
  Both go to Bale, Telegram and the webhook like the other alerts.
- **Activity:** every change, who made it and the web server's output.
- **Settings:** read-only mode for a server, the email for Let's Encrypt, alert thresholds.
- **Projects** can name domains and the address of the application: after every successful
  deploy, a reverse-proxy site is created for the domains that have none yet.

### How changes are made safely

Every change is a transaction. The current file is copied to `/var/backups/mbp-webserver` on
the server (the 20 newest copies are kept), the change is made, the configuration is tested
(`nginx -t`, `apachectl configtest`) and the server reloaded (`systemctl reload`). If the test
or the reload fails, everything is put back as it was and reloaded again, and the panel shows
the web server's output. Only files under `/etc/nginx`, `/etc/apache2` or `/etc/httpd` are
ever written; a file changed by someone else since it was opened is not overwritten.

The agent reads the configuration from the host's `/etc`, mounted read-only
(`/etc:/host/etc:ro` in both compose files), starting at `nginx.conf`, `apache2.conf` or
`httpd.conf` and following `include` the way the servers do. To change something it starts a
short-lived helper container from its own image (privileged, with the host's PID and network
namespaces and `/` mounted) that runs one fixed command on the host and is removed. That adds
no power the agent did not have: access to `docker.sock` already is root on the server. The
panel never sends commands, only the operation and checked values (names, paths, addresses).

The page needs the agent (see [Containers](#containers)); after updating the panel, rebuild
it:

```bash
git pull
docker compose up -d --build agent
```

On another server, rebuild its agent as in [Updating or removing an agent](#updating-or-removing-an-agent).
With SELinux enforcing (RHEL, Rocky, Alma), the agent may not be allowed to read `/etc`; the
page then shows "permission denied" warnings.

## Projects (deploy from git)

Deploy your own applications to this server from a git repository with a `docker compose`
file, from the panel or the Bale/Telegram bot. The panel keeps every deploy's log, can put an
earlier version back with one click, and can back up the application's databases right
before each deploy.

It uses the [agent](#containers), so turn that on first, including the projects folder
(`/opt/mbp-projects` by default, owned by uid 10001).

> **Whoever can deploy can run anything on this server.** A compose file can mount the host's
> files or run privileged containers. Only admins can deploy, deploys from a bot need a Google
> Authenticator code, and every deploy is recorded with who asked for it.

### Add a project

**Projects → New project**:

- **Name**: lowercase letters, digits, `-` and `_`. It is also the compose project name on
  the server: if a compose project with this name is already running there (for example one
  you started by hand), deploys take it over. It can't be changed after the first deploy.
- **Repository, branch, compose file**: `https://…` or `git@host:owner/repo.git`, the branch to
  deploy, and the compose file's path in the repository (default `docker-compose.yml`).
- **Repository access** for a private repository:
  - **SSH deploy key** (recommended): generate a key pair with
    `ssh-keygen -t ed25519 -N "" -f deploy_key`, add `deploy_key.pub` to the repository as a
    read-only deploy key (GitHub: Settings → Deploy keys), and paste the private key
    (`deploy_key`) into the panel.
  - **Access token**: a token with read access to the repository (GitHub fine-grained token
    with "Contents: read", GitLab/Gitea token with `read_repository`).

  The key or token is stored encrypted, never shown again, never put on a command line, and
  masked in logs.
- **Environment variables**: written to a `.env` file next to the compose file on every
  deploy (readable only by the agent). Use them in the compose file with `env_file: .env` or
  `${NAME}`. Values are stored encrypted and never shown again; to change one, type the new
  value, to keep it, leave the field empty. **Upload .env file** or **Paste .env** fills them
  from an existing `.env` (read in the browser, as docker compose reads it: comments,
  `export`, quotes and multi-line values): names already listed get the new value, new
  names are added, and lines that are not variables are reported.
- **Folder** (optional): keeps related projects together on the Projects page, e.g. the
  services of one product. Folders open and close and the page has a search. It is only for
  the panel: files on the server stay in `<projects dir>/<name>`.
- **Backup before deploy**: pick a database server and databases. They are backed up right
  before every deploy (shown in the backup history as "Before a deploy"). With **Stop the
  deploy if the backup fails** on, nothing is deployed without a fresh backup.

### Deploy

**Deploy** on the project's page (or in the bot) does this, with a live log:

1. **Backup** of the chosen databases, if set.
2. **Fetch**: the branch's latest commit from git (into `/opt/mbp-projects/<name>`). Files the
   repository doesn't track, such as data directories, are left alone.
3. **Build**: `docker compose pull` (images that are not built; if pulling fails, for example
   without internet access, the images already on the server are used) and
   `docker compose build`.
4. **Up**: `docker compose up -d --remove-orphans`.
5. **Check**: the services are watched for up to a minute. The deploy fails if one exits with
   an error, keeps restarting, or its health check fails.

Only one deploy of a project runs at a time. The result is sent as an alert (**Deploy
succeeded** / **Deploy failed** on the Notifications page), and a deploy started from the bot
reports back in that chat.

**Rollback:** open an earlier successful deploy and use **Redeploy this version**: the same
commit is deployed again (the database backup from before the bad deploy is in the backup
history if you need it).

**From the bot:** **Projects** lists them with their last deploy; open one to see details
and recent deploys, and **Deploy** asks for the current Google Authenticator code of a panel
account with two-step verification on.

**Deleting a project** removes it from the panel and, if you tick the box, stops and removes
its containers (`docker compose down`; volumes and data directories are kept) and deletes its
checkout. The deploy history is kept.

### Building on another server

By default everything happens on the project's server: fetching the code, `docker compose
build` (the heavy part: CPU, memory, downloads) and starting. Under **Where to build** a
project can instead be built on another connected server:

1. The build server fetches the code and runs `docker compose build`; nothing is started there.
2. The built images are streamed, gzip-compressed, from its agent through the panel to the
   project's server (`docker save` → `docker load`; nothing is stored on the panel's disk).
3. The project's server fetches exactly the commit that was built (for its compose file and
   configuration), pulls the images that are not built, and starts everything with
   `up --no-build`.

The deploy log shows each step and how much was sent. Useful when the project's server is small
or its internet is limited; for large images the transfer takes time, and both agents must be
up to date (an older one is reported as outdated instead of deploying another way).

### On a server in Iran

Pulling images from Docker Hub may be blocked or rate-limited. Configure a registry mirror
for Docker on the server (`/etc/docker/daemon.json`, `"registry-mirrors": [...]`, then
`systemctl restart docker`), or use images from a registry you can reach. Builds that
download packages (npm, pip, apt) may need mirrors set in the project's own Dockerfile.

## Servers

One panel can manage several machines. The panel's own server is always there; any other
machine runs a small **agent** (the same one as for [containers](#containers)) that the panel
talks to over HTTPS. Once connected, that machine's containers, [projects](#projects-deploy-from-git)
and databases are managed from the same panel and bot, and its alerts name it.

### Add a server

1. In the panel, open **Manage all servers** (in the current server's card), then **Add server**: a name, the address the panel reaches it at,
   and the agent's port (`8443` by default).
2. The panel shows the commands to run on that machine, with a **token made for it, shown only
   once**. They clone this repository, write `.env.agent` and start
   `docker-compose.agent.yml`:

   ```bash
   git clone https://github.com/malekipourdev/database-backup-manager.git mbp-agent && cd mbp-agent
   cat > .env.agent <<EOF
   MBP_AGENT_TOKEN=<the token from the panel>
   MBP_AGENT_PORT=8443
   MBP_DOCKER_GID=$(stat -c %g /var/run/docker.sock)
   EOF
   sudo mkdir -p /opt/mbp-projects && sudo chown 10001:10001 /opt/mbp-projects
   docker compose -f docker-compose.agent.yml --env-file .env.agent up -d --build
   ```

   The machine needs Docker with Compose v2. For a private repository, clone it with your own
   access, as for the panel.
3. Open the agent's port **only to the panel's IP address**, for example
   `sudo ufw allow from <panel-ip> to any port 8443 proto tcp`. The agent uses the host's
   network, so the host firewall applies to it.
4. Press **Connect**. The panel checks that the agent holds the token and records its
   certificate.

### How the connection is protected

- The agent creates its own TLS certificate on first start (kept in the `mbp-agent-data`
  volume). On **Connect**, the agent proves it holds the server's token, and the panel pins
  its certificate: from then on it talks to that certificate only. A different certificate
  (the agent was reinstalled, or someone is in between) is refused until you connect again.
- The token never travels over the network. Every request is signed with it (HMAC), together
  with the time and the pinned certificate, so a signature cannot be reused elsewhere. The
  panel and the server's clocks must agree within 5 minutes (use NTP).
- The token is stored encrypted in the panel. **New token** replaces it: put the new one in
  `.env.agent` on the server, run the `docker compose ... up -d` command again, then connect
  again.
- The agent has the same limits as the local one (fixed operations, never returns environment
  values, read-only filesystem, no capabilities), plus database tests, lists and dumps for the
  panel. It stores no database passwords: the panel sends them, over the pinned connection,
  for each operation.

### The current server

The panel always works on one server, the **current server**, shown on the card at the bottom
of the side menu (on a phone, the server name at the top). Press it to switch to another
connected server, or to open **Manage all servers**. The choice is remembered per browser.

- **Per server:** Overview, Databases, Backup history, Schedules, Containers and Projects show
  only the current server's items, and what you add is added on it. Its name is shown next to those pages'
  titles. Container settings (read-only, hidden and locked names, alert limits) are per server.
- **Shared:** Servers, Alerts, Bots, Storage & retention (backup settings, remote storage,
  retention), Account security and Help apply to all servers.
- A project cannot move to another server after its first deploy; delete it and add it on the
  other server instead.
- In the bot, **Containers** asks which server first.
- **Alerts:** an unreachable agent, and everything about that server's containers and
  resources, are announced with the server's name.

### Updating or removing an agent

On that machine, in the `mbp-agent` folder:

```bash
git pull
docker compose -f docker-compose.agent.yml --env-file .env.agent up -d --build
```

The certificate stays in its volume, so the panel keeps trusting it. To remove the agent, run
`docker compose -f docker-compose.agent.yml down -v` there (with `-v`, a new certificate is
made next time: connect again), and delete the server in the panel once it has no projects or
databases.

## Two-step verification (Google Authenticator)

Sign-in can also ask for a 6-digit code from an authenticator app on your phone (Google
Authenticator, Microsoft Authenticator, Aegis, 2FAS, or any other TOTP app). It is off by default.

**Turn it on:** open **Account security** (in the menu, or click your name at the top) → **Turn on**,
confirm your password, scan the QR code with the app (or type the key by hand), and enter the code
the app shows. The panel then shows 8 **recovery codes** once. Save them somewhere safe, away from
your phone. If you lose the phone, each code lets you sign in once. To sign in with one, choose
**Use a recovery code** on the second sign-in step.

- After turning it on, the admin's other sessions are signed out.
- The second step must be finished within 5 minutes of entering the password. Wrong codes count as
  failed sign-ins, and the lockout rule below applies to them.
- Each code works only once, so an intercepted code cannot be reused. Codes depend on the time, so
  keep the server's and the phone's clocks correct (a drift of ±30 seconds is tolerated).
- The same key can be added to several phones or apps (they all show the same codes). Scan the QR
  code on each during setup, or later use **Add another device** (password and a current code),
  which shows the current key again without changing it.
- **New recovery codes** replaces all the old ones. **Turn off** needs your password and a current
  code (or a recovery code).
- The authenticator key is stored encrypted, like the other secrets. Recovery codes are stored only
  as hashes.

**Lost both the phone and the recovery codes?** Anyone with shell access to the server can turn
two-step verification off for an admin:

```bash
docker compose exec backend python -m mbp.cli disable-2fa admin
```

Then sign in with the password and set it up again. For a forgotten password, see
[Forgotten password or locked out](#forgotten-password-or-locked-out).

## Maintenance

### Updating the panel

In the panel's folder on the server:

```bash
git pull
docker compose up -d --build
docker image prune -f   # optional: remove the old images
```

Database migrations run automatically when the backend starts; your settings, servers,
schedules and backups are kept. Take a [backup of the panel](#backing-up-the-panel-itself)
first if the update is large. If the agent is on (`COMPOSE_PROFILES=containers`), it is
updated by the same command. Agents on [other servers](#servers) are updated on those
machines.

### Backing up the panel itself

Everything the panel knows is in two places:

- **`.env`**: above all `MBP_ENCRYPTION_KEY`. Without it, the stored database passwords,
  storage keys and bot tokens can't be decrypted. Keep a copy somewhere safe, away from the
  server (a password manager, for example).
- **The `mbp-data` volume**: the panel's own database (servers, schedules, history,
  settings), when `MBP_DATABASE_URL` is the default SQLite. With PostgreSQL or MySQL, back up
  that database instead.

The backup files themselves are in the `mbp-backups` volume; with remote storage on, they
are also in your bucket.

Save the panel's database to a file (the backend is stopped for a moment so the copy is
consistent):

```bash
docker compose stop backend
docker compose run --rm --no-deps -T --entrypoint tar backend czf - -C /data . > mbp-data-$(date +%F).tgz
docker compose start backend
```

### Moving to another server

1. On the old server, make a backup as above and copy `.env` and the `.tgz` file to the new
   server.
2. On the new server, [get the code](#quick-start), put the **same** `.env` in its folder
   (same `MBP_ENCRYPTION_KEY`), and restore:

   ```bash
   docker compose up --no-start --build
   docker compose run --rm --no-deps -T --entrypoint tar backend xzf - -C /data < mbp-data-2026-10-12.tgz
   docker compose up -d
   ```

3. Check that the database servers are reachable from the new server (**Test connection** on
   each server's page). Local backup files are not moved by this; copy the `mbp-backups`
   volume the same way (`-C /backups`) if you need them, or download them from remote
   storage.

### Forgotten password or locked out

Run these on the server, in the panel's folder:

```bash
# Who are the admins?
docker compose exec backend python -m mbp.cli list-admins

# Set a new password (asked twice; at least 10 characters)
docker compose exec backend python -m mbp.cli reset-password admin

# ...or generate a random one and print it
docker compose exec backend python -m mbp.cli reset-password admin --generate

# Lost the phone and the recovery codes: turn two-step verification off
docker compose exec backend python -m mbp.cli disable-2fa admin
```

`reset-password` also ends all of that admin's sessions and lifts a lockout from failed
sign-ins. It does not turn off two-step verification; use `disable-2fa` for that. A lockout
also ends by itself after 15 minutes.

### Uninstalling

```bash
docker compose --profile containers down   # stop and remove the containers; data is kept
docker compose --profile containers down -v # also delete the volumes: the panel's database and local backup files!
```

Copies in remote storage are not touched; delete them in your storage provider if you no
longer need them. Then remove the panel's folder.

## Security notes

- Every page and API endpoint requires the admin to be signed in, except the login page (and its
  two-step verification step) and `/api/health`.
- Optional two-step verification with an authenticator app (see
  [Two-step verification](#two-step-verification-google-authenticator)).
- `docker.sock` is never given to the backend. Only the optional agent has it; see
  [Containers](#containers) for its limits. Agents on other servers are reached over HTTPS
  with a pinned certificate and signed requests; see [Servers](#servers).
- Web server changes are tested before the reload and undone if the test or the reload fails;
  files are backed up first, and only the web servers' own directories are written (see
  [Web servers](#web-servers-nginx-apache)). A server can be made read-only in the panel.
- Deploy credentials and environment variables of [projects](#projects-deploy-from-git) are
  stored encrypted, never returned, never put on a command line, and masked in deploy logs.
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
