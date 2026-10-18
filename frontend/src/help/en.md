@@category start start Getting started

@@article overview /overview
@title What DevOps Manager does
@summary What the panel is for, and what each part of the menu does.
DevOps Manager backs up **MySQL** and **MariaDB** databases, verifies and keeps the backups, deploys your applications from git, and watches and controls Docker containers, on one server or several. Everything runs on your own server; nothing is sent anywhere else unless you choose to (remote storage, bots).

## The current server

The panel can manage several servers. At the top of the side menu (on a phone, the server name button at the top of the screen) is the **Current server** card: whichever server is chosen there, the Overview, Databases, Backup history, Schedules, Projects and Containers show **only that server's**. Everything else is shared by all servers. ([About the current server](#current-server))

## The menu

The menu is grouped by what you are working on:

| Section              | Item                 | Used for                                                                           |
| -------------------- | -------------------- | ---------------------------------------------------------------------------------- |
|                      | Overview             | (current server) Health, the last day's backups, containers, deploys, and problems |
| Databases & backups  | Databases            | (current server) Add MySQL/MariaDB, test connections, pick databases, take backups |
|                      | Backup history       | (current server) Download, delete, retry uploads                                   |
|                      | Schedules            | (current server) Automatic backups at set times                                    |
|                      | Storage & retention  | Backup settings, remote storage (S3) and retention                                 |
| Applications         | Projects             | (current server) Deploy applications from git with docker compose                  |
|                      | Containers           | (current server) See and control Docker containers                                 |
| Infrastructure       | Servers              | Add, connect and check the servers the panel manages                               |
| Alerts & chat access | Alerts               | Alerts to Bale, Telegram and a webhook                                             |
|                      | Bale & Telegram bots | Manage everything from Bale and Telegram                                           |
| System               | Account security     | Two-step verification and recovery codes                                           |
|                      | Help                 | This guide                                                                         |

**Go to…** (bottom of the side menu, or `Ctrl+K`, or `/`) finds any page or switches server by typing a few letters.

## Where to begin?

If you have just installed the panel, follow [First steps](#first-steps).

@@article install
@title Installation
@summary Install the panel on a Linux server with Docker in a few commands.
Requirements: a Linux server with **Docker**, **Compose v2** and `openssl`.

## 1. Get the code

```bash
git clone https://github.com/malekipourdev/database-backup-manager.git mysql-backup-panel
cd mysql-backup-panel
```

For a private repository, clone with a deploy key or a personal access token, or copy the folder with `scp`.

## 2. Create `.env`

```bash
KEY=$(openssl rand -base64 32 | tr '+/' '-_')
PASS=$(openssl rand -base64 18 | tr -d '/+=')
cat > .env <<EOF
MBP_ENCRYPTION_KEY=$KEY
MBP_ADMIN_USERNAME=admin
MBP_ADMIN_PASSWORD=$PASS
MBP_BIND_ADDRESS=127.0.0.1
MBP_HTTP_PORT=8080
MBP_COOKIE_SECURE=true
EOF
chmod 600 .env
echo "Admin password: $PASS"
```

> ! Keep a copy of `MBP_ENCRYPTION_KEY` somewhere safe (a password manager, for example). Every stored password is encrypted with it and cannot be recovered without it.

## 3. Start

```bash
docker compose up -d --build
ss -tlnp | grep 8080   # expect 127.0.0.1:8080
```

Then open the panel through an [SSH tunnel](#access) and sign in as `admin` with the printed password. After the first sign-in you can remove the `MBP_ADMIN_PASSWORD` line from `.env`; it is only used to create the first admin.

@@article access
@title Secure access over an SSH tunnel
@summary Why the panel listens on 127.0.0.1 only, and how to reach it from your computer.
By default the panel is published on the server's `127.0.0.1:8080` only: it is not reachable from the internet, and you need no domain, TLS certificate or open port.

On your own computer, run this and keep it open while you use the panel:

```bash
ssh -N -L 8080:127.0.0.1:8080 user@SERVER_IP
```

Then open `http://localhost:8080`. If port 8080 is taken on your computer, use for example `-L 18080:127.0.0.1:8080` and `http://localhost:18080`.

> Why not just block the port in the firewall? Docker writes its own iptables rules, which bypass ufw: a port published on `0.0.0.0` is open even when ufw denies it. Keep `MBP_BIND_ADDRESS=127.0.0.1` unless a TLS reverse proxy or a trusted private network sits in front of the panel.

@@article first-steps
@title First steps after signing in
@summary A setup checklist: from the first backup to alerts.

1. **Secure your account:** turn on two-step verification under [Account](/account) ([guide](#two-factor)).
2. **Add a database:** under [Databases](/instances/new), enter the address and user, then **Test connection** ([guide](#add-database)).
3. **Mark databases:** on that database's page, tick the databases to back up and save.
4. **Take a manual backup** and check the result under [Backups](/backups).
5. **Add a schedule** to back up automatically ([guide](#schedules)).
6. **Connect remote storage** for a copy outside the server ([guide](#remote-storage)).
7. **Set a retention policy** so the disk does not fill up ([guide](#retention)).
8. **Set up notifications and a bot** to hear about failures ([guide](#notifications)).
9. Keep a [backup of the panel itself](#panel-backup).

@@article interface
@title Language, layout and mobile
@summary Switching language, using the panel on a phone, and searching this guide.

- **Current server:** the card at the top of the side menu (on a phone, the server name button at the top). [More](#current-server)
- **Go to…:** press Ctrl+K (or /) anywhere, type part of a page or server name and press Enter.
- **Keyboard:** Tab first reaches "Skip to content"; after opening a page, the focus is on its title.
- **Language:** the "فارسی / English" switch at the top. Your choice is remembered in this browser. Each bot admin picks the bot's language in the bot itself.
- **Mobile:** on small screens the bottom bar holds Overview, Databases, Projects and Containers; **Menu** opens every other page, the language and sign out.
- **Session:** after 30 minutes of inactivity you sign in again.
- **Help:** most pages have a "?" button next to their title that opens the guide for that page. This page can also be searched.

@@category databases databases Databases

@@article add-database /instances/new
@title Adding a database
@summary Register a MySQL or MariaDB server and test the connection.
First choose the server the database is on in the **Current server** card, then **Databases → Add database**. The database is added on that server (the form shows its name):

- On **the panel's own server**, the panel connects to the database itself.
- On **another server**, that server's agent tests, lists and backs up the database; its port need not be open to the outside.

| Field                 | Meaning                                                                   |
| --------------------- | ------------------------------------------------------------------------- |
| Name                  | Any display name, e.g. `prod` (also used in backup folder and file names) |
| Host and port         | Where the database is; see [which address to use](#db-host)               |
| Username and password | Preferably a [dedicated backup user](#backup-user)                        |
| Notes                 | Optional                                                                  |

Press **Test connection** before saving. The panel detects the type (MySQL or MariaDB) and version. If it fails, see [Connection errors](#connection-errors).

> The password is stored encrypted and never shown again. When editing, leave the password empty to keep the stored one.

@@article db-host
@title Which host should I enter?
@summary The right host and port for a database in a container, on the host, or on another server.
The panel itself runs in a container, so `localhost` and `127.0.0.1` mean **the panel**, not your server.

## A database in a Docker container (on this server)

Attach the database container to the panel's network:

```bash
docker network connect mbp-net <database-container-name>
```

Then host = the **container name** (e.g. `mysql_db`) and port = the **internal port** (usually `3306`), not the port published on the server.

To keep that connection when the container is recreated, add this to that project's compose file:

```yaml
services:
  mysql_db:
    networks: [default, mbp-net]
networks:
  mbp-net:
    external: true
```

## A database installed directly on this server

Host = `host.docker.internal` and the server's port. The database must listen on an address containers can reach (with `bind-address` set to `127.0.0.1` it is not reachable).

## A database on another server

- **Recommended:** [connect that server](#add-server), choose it in the Current server card, and add the database there. The host is then as seen from that server: `127.0.0.1` for a database published on it, or the **container name** for one in a container. The database port never has to be open to the outside.
- **Directly:** add a database on the panel's own server and enter the other server's IP address or domain and port; that server's firewall must allow connections from this one.

@@article backup-user
@title A dedicated backup user
@summary Create a user with only the privileges backups need, instead of root.
Instead of `root`, create a dedicated user:

```bash
docker exec -it <database-container-name> mysql -uroot -p
```

```sql
CREATE USER 'mbp_backup'@'%' IDENTIFIED BY 'a-strong-password';
GRANT SELECT, SHOW VIEW, TRIGGER, EVENT, LOCK TABLES ON *.* TO 'mbp_backup'@'%';
FLUSH PRIVILEGES;
```

- For MariaDB, use `mariadb` instead of `mysql`.
- The `PROCESS` privilege is not needed.
- The panel lists only the databases this user can see; if one is missing, check the user's privileges.

@@article select-databases /instances
@title Choosing databases to back up
@summary Which databases "Back up all" and schedules include.
On each database server's page, **Databases to back up** lists the server's databases.

- Tick the ones you want and press **Save selection**.
- "Back up all" and schedules for "all marked databases" include only these.
- System schemas (`information_schema`, `performance_schema`, `sys`) cannot be selected; **Show system schemas** displays them.
- A selected database that no longer exists on the server is marked "Not on the server"; untick it.
- A single-database backup does not need the database to be marked.

@@article connection-errors
@title Connection errors
@summary What each connection test error means and how to fix it.

| Error                | Usual cause                                                         | Fix                                                                                   |
| -------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Host not found       | Misspelled name, or a container not attached to the panel's network | Check the name; `docker network connect mbp-net …`                                    |
| Connection refused   | Wrong port, or nothing listening there                              | Use the container's internal port (3306), not the published one; check `bind-address` |
| Timed out            | Firewall or routing                                                 | The database server's firewall, and access from the panel's server                    |
| Credentials rejected | Username/password, or the user may not connect from this address    | Create the user with `'%'` ([guide](#backup-user))                                    |
| Agent unreachable    | For databases on other servers: that server's agent is down         | See [Server troubleshooting](#server-troubleshoot)                                    |

> When editing, if you changed the host or user, enter the password again to test.

@@category backups backups Backups

@@article manual-backup /instances
@title Manual backups
@summary Back up all marked databases, or one database, right now.
On each database server's page, in the **Backups** section:

- **Back up all selected databases**: one backup per marked database.
- **Back up one database**: any database, marked or not.

Progress (size dumped and time) shows there and under [Backups](/backups). Several backups run at once (2 by default); the rest wait in a queue. Two backups of the same database never run at the same time.

Backups can also be started from the bot; see [Using the bot](#bots-usage).

@@article how-backup-works
@title How a backup is made and verified
@summary The steps that produce a backup file and guarantee it is complete.

1. The panel connects and detects whether the server is MySQL or MariaDB.
2. It runs the matching tool (`mysqldump` for MySQL, `mariadb-dump` for MariaDB) with `--single-transaction --quick --routines --triggers --events --hex-blob --no-tablespaces`: tables are not locked, and views, procedures, triggers and events are included.
3. The password reaches the tool only through a private temporary file; it never appears on a command line or in logs.
4. The output is compressed as it streams into a temporary file, so large databases do not fill memory.
5. The file is **verified**: SHA-256 checksum, full decompression, and the dump's `-- Dump completed` marker.
6. Only then does it get its final name. A failed or interrupted backup leaves no file, and its reason is shown.

For databases on another server, step 2 runs on that server by its agent; the output is streamed to the panel, and compressed and verified here.

@@article history /backups
@title History, download and delete
@summary Working with the Backups page.
The [Backups](/backups) page lists every run: status, size, duration, checksum, trigger (manual, scheduled, before a deploy) and upload status.

- **Filter and sort:** by server, database name, status and date range.
- **Download:** if the local file was removed but a remote copy exists, the panel streams it from remote storage.
- **Delete:** by default only the file on the server is deleted; the remote copy and the history entry stay. Tick "Also delete the remote copy" to remove it too ([7-day protection](#remote-protection)).
- **Retry upload:** when an upload failed.
- **Error details:** open a failed backup for its reason and a suggested fix.

@@article backup-settings /settings/backups
@title Folder, file name and compression
@summary Global backup settings, and per-database overrides.
Under **Storage & retention → Backup settings**:

- **Storage directory:** relative to the backup storage (the `mbp-backups` volume).
- **File name pattern:** default `{instance}/{database}_{date}_{time}`. Placeholders: `{instance}` `{database}` `{date}` `{time}` `{datetime}` `{server_type}`. `/` makes subfolders, times are UTC, and the extension is added automatically.
- **Compression:** gzip (default), bzip2 or none.

Each database server can override any of these on its own page. Changes apply to new backups only.

The files are in `/backups` inside the container:

```bash
docker compose exec backend find /backups -type f
```

@@article schedules /schedules
@title Scheduled backups
@summary Automatic backups with cron and a time zone.
Under [Schedules](/schedules), or on a database server's page, **Add schedule**:

- **Frequency:** presets (hourly, daily, weekly, monthly) or a custom five-field cron: `minute hour day-of-month month day-of-week`.
- **Time zone:** e.g. `Asia/Tehran`. The form shows the next five runs so you can check.
- **What:** all marked databases, or one database.

| Cron          | Means                           |
| ------------- | ------------------------------- |
| `30 1 * * *`  | Every day at 01:30              |
| `0 */6 * * *` | Every 6 hours                   |
| `0 3 * * 6`   | Saturdays at 03:00              |
| `0 2 1 * *`   | The 1st of every month at 02:00 |

- Each schedule shows the result of its last run (e.g. "No databases marked").
- If the panel was down at the scheduled time and comes back within 5 minutes, the run still happens; otherwise it waits for the next time.
- If the previous backup of a database is still running, that database is skipped this time.

@@article restore
@title Restoring a backup
@summary Putting a backup file back into a database.
Download the file from [Backups](/backups) and restore it into an **empty** database:

```bash
gunzip -c shop_2026-10-11_140804.sql.gz | mysql -h HOST -u root -p shop     # MySQL
gunzip -c shop_2026-10-11_140804.sql.gz | mariadb -h HOST -u root -p shop   # MariaDB
```

- Use `bunzip2 -c` for bzip2 files and `cat` for uncompressed ones.
- Create the target database first: `CREATE DATABASE shop;`.
- The file has no `CREATE DATABASE` or `USE`, so you can restore under another name, e.g. `shop_test` for a trial.
- If only the remote copy is left, downloading from the panel fetches it; or use any S3 client such as `aws s3 cp`.

> ! Try a restore on a test database before restoring over the real one.

@@category storage storage Remote storage and retention

@@article remote-storage /settings/backups
@title Connecting remote storage (S3)
@summary Upload backups automatically to AWS S3 or any compatible service.
Under **Storage & retention → Remote storage**:

| Field        | Meaning                                                                                |
| ------------ | -------------------------------------------------------------------------------------- |
| Endpoint URL | Empty for AWS; otherwise the service URL, e.g. `https://s3.ir-thr-at1.arvanstorage.ir` |
| Region       | e.g. `ir-thr-at1` or `us-east-1`                                                       |
| Bucket       | The bucket name only, no `s3://` and no slashes                                        |
| Key prefix   | A folder inside the bucket (optional)                                                  |
| Keys         | Access key and secret key                                                              |
| Path-style   | On for MinIO, RustFS, Ceph and ArvanCloud                                              |

1. Press **Test connection**: the panel tries writing to and deleting from the bucket.
2. Turn on **Upload backups to remote storage** and save. Without this switch nothing is uploaded, even when the test succeeds.
3. Each database server can choose "Always / Never / Global setting" on its page.

- Uploads happen after a backup is verified, in 64 MiB parts.
- A failed upload does not fail the backup: the local file stays and you can retry.
- The secret key is stored encrypted and never shown again.

For least privilege, give the key only `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` and `s3:ListBucket` on that bucket.

@@article arvancloud /settings/backups
@title ArvanCloud, step by step
@summary Connect the panel to ArvanCloud Object Storage.

1. In the ArvanCloud console, open **Object Storage** and create a **private** bucket (e.g. `airplus`).
2. Under **Access keys**, create a key pair and copy the access key and secret key. The secret is shown once.
3. Note your region's endpoint in the console, e.g. `https://s3.ir-thr-at1.arvanstorage.ir` (Tehran). The region is its middle part: `ir-thr-at1`.
4. In the panel, **Storage & retention → Remote storage**:

| Field        | Value                                   |
| ------------ | --------------------------------------- |
| Endpoint URL | `https://s3.ir-thr-at1.arvanstorage.ir` |
| Region       | `ir-thr-at1`                            |
| Bucket       | `airplus`                               |
| Key prefix   | `mysql-backup` (optional)               |
| Path-style   | on                                      |

5. **Test connection** must succeed.
6. Turn on **Upload backups to remote storage** and **Save**.
7. Take a backup: its history row shows "Stored remotely", and the file appears in the bucket with the same path and name.

> ! Never paste the secret key into a chat, ticket or messenger; enter it only in the panel. If it leaks, revoke it in the ArvanCloud console and create a new one.

An address like `s3://airplus/mysql-backup/` means bucket `airplus` and prefix `mysql-backup`.

@@article remote-protection
@title 7-day protection of remote copies
@summary Why the panel does not delete a remote copy within 7 days of its upload.
The panel never deletes a remote copy until **7 days after it was uploaded**, neither by retention nor by hand. This protects the offsite copies against a mistake, or someone who got into the panel.

- During those 7 days, "Also delete the remote copy" is disabled and shows when it becomes possible.
- If you really must, delete it in the storage provider's own console (e.g. ArvanCloud).
- The remote "Delete after" in the retention policy cannot be below 7 days.

> For protection that holds even if the panel itself is compromised, turn on _Object Lock_ or a lifecycle/retention rule on the bucket in your storage provider.

@@article retention /settings/backups
@title Retention (automatic cleanup)
@summary Delete old backups automatically so the disk and the bucket do not fill up.
Under **Storage & retention → Retention**, separately for **local files** and **remote copies**:

- **Keep the last N** backups of each database.
- **Delete after N days**.

Good to know:

- An empty field means no limit. With both set, a backup breaking either rule is deleted.
- **The newest backup of each database is never deleted**, even past the age limit.
- Only successful backups are affected.
- Remote copies younger than 7 days are never deleted ([why?](#remote-protection)).
- It runs after each backup (for that database) and hourly for all.
- **Preview and apply now** lists what would be deleted before deleting anything.
- Each database server can have its own policy on its page.

The history entry stays and shows when and why the file was removed.

@@category alerts alerts Notifications and bots

@@article notifications /notifications
@title Notifications and rules
@summary Which events raise an alert, and where it goes.
Under [Notifications](/notifications), turn each event on or off and choose its channels (Bale, Telegram, webhook).

| Event                                                                 | Severity        |
| --------------------------------------------------------------------- | --------------- |
| Backup failed, upload failed                                          | error           |
| No recent backup (default: more than 26 hours)                        | error           |
| Low disk space (default: below 10%)                                   | warning         |
| Schedule did not run, retention could not delete                      | warning         |
| Container down, restart loop, unhealthy, high usage, server resources | error / warning |
| Agent unreachable, deploy failed                                      | error           |
| Backup succeeded, deploy succeeded, back to normal, daily summary     | info            |

- **Cooldown:** the same alert about the same thing is sent at most once per period (default 60 minutes).
- **Condition alerts** (no recent backup, low disk) are sent once when the problem starts and once when it clears.
- **Daily summary** at the time you choose.
- **History:** every alert is kept for 90 days with where it was delivered.
- **Send a test alert** tries all channels at once.

Alerts about other servers start with that server's name.

@@article webhook /notifications
@title Signed webhook
@summary Send alerts to other systems, signed with HMAC.
Under [Notifications](/notifications), enter a webhook URL and, optionally, a **signing secret**. Each alert is POSTed as JSON:

```json
{
  "event": "backup_failed",
  "severity": "error",
  "subject": "backup_failed:1:shop",
  "message": "...",
  "params": {},
  "run_id": 42,
  "created_at": "2026-10-11T08:00:00+00:00",
  "source": "mysql-backup-panel"
}
```

With a secret, the `X-MBP-Signature` header is `sha256=` followed by the HMAC-SHA256 of the body, so the receiver can check that the alert came from the panel.

@@article bots-setup /bots
@title Setting up the Bale and Telegram bots
@summary Create a bot, enter its token, and register admins.
The bot connects out to the messenger (long polling), so the panel needs no public address or open port.

1. In **Bale** open `@botfather` (in **Telegram** `@BotFather` and `/newbot`), create a bot and copy its token.
2. Under [Bots](/bots), turn the bot on, paste the token, press **Test token**, then **Save**. Once running, the badge shows "Connected as @…".
3. Under **Bot admins**, register who may use it, in either way:
   - **Numeric user ID:** if the person messages the bot, it replies with their ID.
   - **Link code:** press "Create link code"; the person sends the code to the bot within 15 minutes and is registered automatically.

> If Telegram is blocked on the server, set an `http://`, `https://` or `socks5://` proxy (without username and password) under "Advanced settings".

@@article bots-usage
@title Using the bot
@summary What you can do from Bale and Telegram.
`/start` (or `/menu`) opens the bot's menu, grouped like the panel's:

- **📊 Overview:** databases, running backups, the last 24 hours, disk space, the next run, connected servers and failed deploys.
- **🗄 Databases & backups → Databases:** details, test the connection, back up all (with confirmation) or one database.
- **🗄 Databases & backups → Latest backups:** history, details, retry upload, delete (with confirmation), and receive the file if allowed.
- **🗄 Databases & backups → Schedules:** enable, disable, run now.
- **🗄 Databases & backups → Retention:** preview, then apply.
- **🚀 Projects:** recent deploys, and deploys with a Google Authenticator code.
- **🐳 Containers:** state, usage, logs (if allowed), and start/stop/restart with a Google Authenticator code. With several servers, you pick the server first.
- **🖥 Servers:** each server's state, with its containers, resources (CPU, RAM, disk), projects and databases.
- **⚙️ Alerts & language:** your own alert level (everything, warnings and errors, errors only, off) and language.
- **❓ Help:** what each section does, and the commands.

Commands, also listed in the messenger's command menu: `/menu`, `/status`, `/backups`, `/projects`, `/containers`, `/servers`, `/settings`, `/help`.

@@article bots-security
@title Bot security
@summary Who can use the bot, and what is never possible through it.

- Only registered, active admins get answers, and only in **private chats**; group messages are ignored. Everyone else sees only their own numeric ID.
- Database passwords and storage keys are never entered or shown through the bot.
- **Sending backup files through the bot is off by default**, because it copies your database to the messenger's servers. If you turn it on, set a size limit (about 20 MB on Bale, 50 MB on Telegram).
- Sensitive actions (container control and deploys) need a **fresh Google Authenticator code** of a panel account with two-step verification. 5 wrong codes in 15 minutes block these from the bot for 15 minutes.
- Bot tokens are stored encrypted, and every bot action is logged with the admin's ID.

@@category servers servers Servers

@@article current-server
@title The current server, and switching
@summary The panel always works on one server; switch it from the card at the top of the menu.
The panel always works on **one server**: the "current server". Its name and state are on the card at the top of the side menu (on a phone, the server name button at the top). Press the card to:

- **Choose another server.** Servers that are not connected yet cannot be chosen.
- Open **Manage all servers**: add, connect, edit and remove servers.

## What depends on the current server?

| Current server only | Shared by all servers                         |
| ------------------- | --------------------------------------------- |
| Databases           | Notifications and alerts                      |
| Backups (history)   | Bale and Telegram bots                        |
| Schedules           | Settings (backups, remote storage, retention) |
| Containers          | Account                                       |
| Projects            | Help                                          |

- The current server's name is also shown next to the title of the pages that depend on it.
- Whatever you add (a database, a project) is added on the current server.
- Your choice is remembered in this browser. If that server is removed or disconnected, the panel goes back to its own server.
- Example: to work with the second server's containers, choose it in the Current server card first, then open [Containers](/containers).

@@article servers-overview /servers
@title Managing several servers
@summary One panel for several machines: their containers, projects and databases.
The panel always has **its own server** (marked "this server"). Any other server connects through a small **agent**. Once connected, choose it in the [Current server card](#current-server) and:

- **Containers** are that server's. Settings and alerts are per server.
- **Projects** are deployed on that server.
- **Databases** are tested, listed and backed up by that server's agent; their port never has to be open to the outside.
- **Alerts and bot:** alerts name the server, and the bot asks which server first.

**Manage all servers** opens from the Current server card.

Each server's card shows its state (connected, unreachable, not connected), host name, Docker version, last contact, certificate fingerprint, and how many projects and databases use it.

@@article add-server /servers
@title Adding a server
@summary Install the agent on another server and connect it.
The new server needs **Docker** with **Compose v2**.

1. Open **Servers** in the menu (or press the Current server card, then **Manage all servers**), then, then **Add server**: a name, the IP address or domain the panel reaches it at, and the agent port (default `8443`).
2. The panel shows the install commands with a **token made for this server. The token is shown only this once.** Copy the commands and run them on the new server:

```bash
git clone https://github.com/malekipourdev/database-backup-manager.git mbp-agent && cd mbp-agent
cat > .env.agent <<EOF
MBP_AGENT_TOKEN=<token>
MBP_AGENT_PORT=8443
MBP_DOCKER_GID=$(stat -c %g /var/run/docker.sock)
EOF
sudo mkdir -p /opt/mbp-projects && sudo chown 10001:10001 /opt/mbp-projects
docker compose -f docker-compose.agent.yml --env-file .env.agent up -d --build
```

3. Open the agent port in the firewall **for the panel server's IP only**:

```bash
sudo ufw allow from <PANEL-IP> to any port 8443 proto tcp
```

4. Press **Connect** in the panel. On success the state becomes "Connected".
5. To work on the new server, press **Work on this server** on its card, or choose it in the Current server card.

> For a private repository, clone it on the new server with your own access, as for the panel. If you lose the token, use "New token".

@@article server-security
@title How server connections are protected
@summary How the panel knows it talks to the real agent.

- On first start, the agent creates its own HTTPS certificate (kept in the `mbp-agent-data` volume).
- On **Connect**, the agent proves it holds the server's token, and the panel **pins** its certificate: from then on it talks to that certificate only.
- **The token never travels over the network.** Every request is signed with it, bound to the time and the pinned certificate, so someone in between can neither learn the token nor reuse a request elsewhere.
- The token is stored encrypted in the panel.
- The agent stores no database passwords; the panel sends them over this protected connection for each operation.
- The agent knows a fixed set of operations, never returns environment variable values, and runs with a read-only filesystem and no capabilities.

> The panel's and the servers' clocks must agree within 5 minutes; keep NTP on.

@@article server-troubleshoot /servers
@title Server connection troubleshooting
@summary What each server error means, and the fix.

| Error                         | Means                                                                | Fix                                                                                                            |
| ----------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Agent unreachable             | The panel cannot reach the address and port                          | Is the agent running: `docker compose -f docker-compose.agent.yml ps`; firewall; address and port in the panel |
| Agent refused the token       | The agent's token differs from the panel's                           | Fix `.env.agent` and run `up -d` again, or use "New token"                                                     |
| Agent has another certificate | The agent was reinstalled (volume removed), or someone is in between | If you reinstalled it yourself, press **Connect** again                                                        |
| Clocks differ                 | More than 5 minutes apart                                            | `timedatectl set-ntp true` on both servers                                                                     |
| Agent outdated                | The agent needs updating                                             | [Update the agent](#server-maintenance)                                                                        |
| Server not connected          | Connect was not pressed, or the token changed                        | Press **Connect**                                                                                              |

The agent's log on that server:

```bash
docker compose -f docker-compose.agent.yml logs --tail 100 agent
```

@@article server-maintenance /servers
@title Updating, new token and removing a server
@summary Looking after the agents of other servers.

## Updating an agent

On that server, in the `mbp-agent` folder:

```bash
git pull
docker compose -f docker-compose.agent.yml --env-file .env.agent up -d --build
```

The certificate stays in its volume, so no new Connect is needed.

## New token

If a token leaked or was lost, press "New token" on the server's card. The old token stops working at once. Put the new one in `.env.agent`, run the `up -d` command above again, then press **Connect**.

## Removing a server

- A server with projects or databases cannot be removed; delete or move them first.
- Removing it from the panel does not remove the agent. On that server run: `docker compose -f docker-compose.agent.yml down -v`
- The panel's own server cannot be removed, but it can be renamed.

@@category containers containers Containers

@@article containers-enable /containers
@title Turning on container management
@summary Run the agent on the panel's own server.
This is off by default. It needs one more container, the **agent**: the only part with access to `docker.sock`. In the panel's folder on the server:

```bash
echo "COMPOSE_PROFILES=containers" >> .env
echo "MBP_DOCKER_GID=$(stat -c %g /var/run/docker.sock)" >> .env
sudo mkdir -p /opt/mbp-projects && sudo chown 10001:10001 /opt/mbp-projects
docker compose up -d --build
```

- `MBP_DOCKER_GID` is the group of the Docker socket, so the agent may use it. If the panel says the agent may not use `docker.sock`, check this value.
- For rootless Docker or Podman, also set `MBP_DOCKER_SOCKET` to the socket path.
- To turn it off, remove `COMPOSE_PROFILES=containers` from `.env` and run `docker compose up -d --remove-orphans`.

> Access to `docker.sock` equals root on the server, so the agent is small and strict: it publishes no port, answers only the panel, never runs commands in containers, and never stops the panel's own containers.

@@article containers-usage /containers
@title Working with containers
@summary State, usage and logs, and controlling containers.

- **Server:** the [current server](#current-server)'s containers are shown; for another server, choose it in the Current server card first.
- **Containers tab:** every container grouped by compose project, problems first: state, health, uptime or exit code, CPU, RAM and restarts, refreshed every 5 seconds. The server's CPU, RAM and Docker disk are at the top.
- **Filters and search:** all, running, problems, stopped.
- **Details (click a container):** image, ports, networks, volumes, restart policy, the last health check output, and the **names** of environment variables (values are never shown).
- **Logs:** the last 100 to 5,000 lines, stderr marked, with filter, live follow and download.
- **Start, stop, restart:** stop and restart ask for confirmation.
- **Activity tab:** every start, stop and restart, from the panel or a bot, who asked and the result.

@@article containers-settings /containers
@title Container settings
@summary Read-only mode, hidden and locked containers, logs in bots, alert limits.
On the **Settings** tab (per server):

- **Read-only mode:** watch only; no container can be controlled from the panel or the bots.
- **Hidden containers:** names or patterns (e.g. `vault*`) never shown.
- **Locked containers:** shown but never controlled. The panel's own containers are always locked.
- **Logs in the bots:** off by default, because logs may hold sensitive data and are copied to the messenger's servers.
- **Alerts:** which containers are watched, and the limits for container CPU and RAM, restart loops, server RAM and Docker disk. `0` turns a check off.

@@article containers-alerts /notifications
@title Container alerts
@summary When containers and server resources raise an alert.
Checked every minute. Each alert is sent once when the problem starts and once when it clears. Turn each on or off and choose channels under [Notifications](/notifications).

| Alert               | When                                                                                           |
| ------------------- | ---------------------------------------------------------------------------------------------- |
| Container went down | It exited with an error, or was killed for running out of memory (not when stopped on purpose) |
| Restart loop        | e.g. 3 restarts in 10 minutes (adjustable)                                                     |
| Unhealthy           | Its health check fails                                                                         |
| High usage          | CPU or RAM above the limit for two checks in a row                                             |
| Server resources    | Server RAM or Docker disk above the limit                                                      |
| Agent unreachable   | The agent worked and stopped answering                                                         |

@@article containers-bot
@title Containers from the bot
@summary See and control containers from Bale and Telegram, with a Google Authenticator code.
Press **Containers** in the bot's menu (with several servers, pick one first). It lists them with problems first and shows details, usage, server status and, if allowed, the last 30 log lines.

**Start, stop and restart from the bot need a Google Authenticator code:**

1. Press the action.
2. The bot asks for the current 6-digit code of a panel account with [two-step verification](#two-factor) on.
3. Send it within 2 minutes.

If no account has two-step verification, containers can only be watched from the bot. After 5 wrong codes in 15 minutes, control from the bot is blocked for 15 minutes. So a stolen messenger account cannot stop your services.

@@category projects projects Projects and deploys

@@article projects-overview /projects
@title How deploys work
@summary What Projects do, and an important security note.
Deploy your own applications from a git repository with a `docker compose` file, from the panel or the bot. The panel keeps every deploy's log, puts an earlier version back with one click, and can back up the application's databases right before each deploy.

Requirements: the [agent is on](#containers-enable) (on the panel's server), or the target server is [connected](#add-server). The projects folder (default `/opt/mbp-projects`) must be owned by user `10001`.

> ! **Whoever can deploy can do anything on that server**, because a compose file can mount the server's files or run privileged containers. Only admins deploy, deploys from the bot need a Google Authenticator code, and each deploy is recorded with who asked.

@@article add-project /projects/new
@title Adding a project
@summary Repository, access, variables and the backup before deploys.
**Projects → New project**:

- **Name:** lowercase letters, digits, `-` and `_`. It is also the compose project name on the server, and cannot change after the first deploy.
- **Server:** the project is built and deployed on the [current server](#current-server) (the form shows its name). It cannot change after the first deploy.
- **Repository, branch, compose file:** `https://…` or `git@host:owner/repo.git`, the branch to deploy, and the compose file's path in the repository (default `docker-compose.yml`).
- **Access to a private repository:**
  - **SSH deploy key (recommended):** create one with `ssh-keygen -t ed25519 -N "" -f deploy_key`, add `deploy_key.pub` to the repository as a read-only deploy key (GitHub: Settings → Deploy keys), and paste the private key into the panel.
  - **Token:** a token with read access (GitHub: Contents: read; GitLab/Gitea: `read_repository`).
- **Environment variables:** written to a `.env` file next to the compose file on every deploy. Use them with `env_file: .env` or `${NAME}`. Values are stored encrypted and never shown again; leave a field empty to keep it.
- **Backup before deploy:** pick a database server and databases. With "Stop the deploy if the backup fails", nothing is deployed without a fresh backup.

> Keys and tokens are stored encrypted, never shown again, and masked in logs.

@@article deploy /projects
@title Deploying, step by step
@summary What happens after you press Deploy.
Press **Deploy** on the project's page (or in the bot). A live log shows:

1. **Backup** of the chosen databases, if set.
2. **Fetch:** the branch's latest commit. Files the repository does not track (data folders) are left alone.
3. **Build:** `docker compose pull` (if pulling fails, images already on the server are used) and `docker compose build`.
4. **Up:** `docker compose up -d --remove-orphans`.
5. **Check:** the services are watched for up to a minute. If one exits with an error, keeps restarting or fails its health check, the deploy fails with the reason (e.g. "worker: exited with code 3").

- One deploy per project at a time.
- The result is sent as a "Deploy succeeded / failed" alert, and a deploy started from the bot reports back in that chat.
- **From the bot:** Projects → project → Deploy, then the Google Authenticator code.
- **Deleting a project** removes it from the panel and, if ticked, stops and removes its containers (`docker compose down`; volumes and data are kept). The deploy history stays.

@@article rollback /projects
@title Rolling back
@summary Put a broken deploy back with one click.

1. On the project's page, open an earlier **successful** deploy in the history.
2. Press **Redeploy this version**: the same commit is deployed again.

If the bad deploy also damaged data, the backup taken right before it is under [Backups](/backups), marked "Before a deploy"; see [Restoring](#restore).

@@article projects-iran
@title Servers in Iran
@summary Getting images and packages when internet access is limited.

- Pulling from Docker Hub may be blocked or rate-limited. Configure a **registry mirror** for Docker:

```json
{ "registry-mirrors": ["https://<mirror>"] }
```

in `/etc/docker/daemon.json`, then `systemctl restart docker`.

- If pulling fails, deploys use the images already on the server.
- Builds that download packages (npm, pip, apt) may need mirrors in the project's own Dockerfile.
- If Telegram is blocked, set a proxy for the bot ([guide](#bots-setup)) or use Bale.

@@category account account Account and security

@@article two-factor /account
@title Two-step verification (Google Authenticator)
@summary Require a 6-digit code to sign in.
After the password, sign-in also asks for a 6-digit code from an authenticator app (Google Authenticator, Microsoft Authenticator, Aegis, 2FAS or any TOTP app).

1. Go to [Account](/account) and press **Turn on**.
2. Confirm your password.
3. Scan the QR code with the app (or type the key).
4. Enter the code the app shows.
5. **8 recovery codes** are shown; keep them somewhere safe, away from the phone. They are shown only once.

- Turning it on signs out the account's other sessions.
- The second step must be finished within 5 minutes of the password.
- Each code works once. Keep the server's and the phone's clocks right (±30 seconds is tolerated).
- **Turning it off** needs your password and a current code (or a recovery code).
- Controlling containers and deploying from the bot need at least one account with two-step verification.

@@article recovery-codes /account
@title Recovery codes and several devices
@summary Signing in without the phone, and adding a second phone.

## Signing in with a recovery code

On the second sign-in step, choose **Use a recovery code**. Each works once. When few are left, create **New recovery codes** (the old ones stop working).

## Several phones or accounts

The same key can be added to several phones or apps; they all show the same codes. Scan the QR on each during setup, or later use **Add another device** (password and a current code) to see the same key again; the key does not change.

## Lost both the phone and the codes

Anyone with shell access to the server can turn two-step verification off:

```bash
docker compose exec backend python -m mbp.cli disable-2fa admin
```

Then sign in with the password and set it up again.

@@article forgot-password
@title Forgotten password or locked out
@summary Getting access back from the server.
On the server, in the panel's folder:

```bash
# Who are the admins?
docker compose exec backend python -m mbp.cli list-admins

# A new password (asked twice; at least 10 characters)
docker compose exec backend python -m mbp.cli reset-password admin

# ...or generate a random one and print it
docker compose exec backend python -m mbp.cli reset-password admin --generate
```

- `reset-password` also ends that admin's sessions and lifts a lockout from failed sign-ins.
- It does not turn off two-step verification; see `disable-2fa` for that.
- After 5 failed sign-ins in 15 minutes, a username is locked for 15 minutes; the lock also ends by itself.

@@article security-notes
@title Security notes
@summary The panel's security measures, and recommendations.

- Every page and API needs a signed-in admin (except the login page and `/api/health`).
- Sessions end after 30 minutes of inactivity. After 5 failed sign-ins, a username is locked for 15 minutes.
- Database passwords, the storage key, bot tokens, server tokens, repository keys and project variables are **stored encrypted** and never appear in responses or logs.
- `docker.sock` is given only to the agent, never to the panel itself.
- By default the panel is reachable only from the server itself ([SSH tunnel](#access)).

Recommendations:

- Turn on two-step verification.
- Keep safe copies of `MBP_ENCRYPTION_KEY` and your recovery codes.
- Never send keys or tokens in a chat or ticket; if you did, revoke and replace them at once.
- Use a [dedicated least-privilege user](#backup-user) for databases.
- Turn on Object Lock or a retention rule on the storage bucket.

@@category maintenance maintenance Maintenance

@@article update
@title Updating the panel
@summary Get the latest version without losing anything.
In the panel's folder on the server:

```bash
git pull
docker compose up -d --build
docker image prune -f   # optional: remove old images
```

- Database migrations run automatically at start; settings, databases, schedules and backups are kept.
- Before large updates, take a [backup of the panel](#panel-backup).
- If the agent is on, the same command updates it. Agents on other servers are [updated on those servers](#server-maintenance).

@@article panel-backup
@title Backing up the panel itself
@summary What to keep a copy of, and how.
Everything the panel knows is in two places:

- **`.env`**, above all `MBP_ENCRYPTION_KEY`. Without it the stored secrets cannot be decrypted. Keep a copy somewhere safe, off the server.
- **The `mbp-data` volume**: the panel's own database (with the default SQLite). With PostgreSQL or MySQL, back up that database instead.

Save the panel's database to a file:

```bash
docker compose stop backend
docker compose run --rm --no-deps -T --entrypoint tar backend czf - -C /data . > mbp-data-$(date +%F).tgz
docker compose start backend
```

The backup files themselves are in the `mbp-backups` volume, and in the bucket when remote storage is on.

@@article move
@title Moving to another server
@summary Move the whole panel.

1. On the old server, take a [backup of the panel](#panel-backup) and copy `.env` and the `.tgz` file to the new server.
2. On the new server, get the code, put the **same** `.env` in its folder (same `MBP_ENCRYPTION_KEY`), and restore:

```bash
docker compose up --no-start --build
docker compose run --rm --no-deps -T --entrypoint tar backend xzf - -C /data < mbp-data-2026-10-12.tgz
docker compose up -d
```

3. Press **Test connection** on each database server. Local backup files are not moved; copy the `mbp-backups` volume the same way (`-C /backups`) if needed, or download them from remote storage.

@@article configuration
@title Configuration variables
@summary The settings in `.env` and what each does.

| Variable                                    | Default                | Purpose                                                                                       |
| ------------------------------------------- | ---------------------- | --------------------------------------------------------------------------------------------- |
| `MBP_ENCRYPTION_KEY`                        | (required)             | Key that encrypts stored secrets; separate several with commas to rotate (the first encrypts) |
| `MBP_ADMIN_USERNAME` / `MBP_ADMIN_PASSWORD` | `admin`                | The first admin; read on first start only                                                     |
| `MBP_DATABASE_URL`                          | SQLite                 | The panel's own database; PostgreSQL or MySQL also work                                       |
| `MBP_BIND_ADDRESS` / `MBP_HTTP_PORT`        | `127.0.0.1` / `8080`   | Where the panel is published                                                                  |
| `MBP_COOKIE_SECURE`                         | `true`                 | Cookie over HTTPS only (works over an SSH tunnel)                                             |
| `MBP_BACKUP_CONCURRENCY`                    | `2`                    | Backups running at the same time                                                              |
| `MBP_RETENTION_INTERVAL_MINUTES`            | `60`                   | How often retention runs                                                                      |
| `MBP_MONITOR_INTERVAL_MINUTES`              | `10`                   | How often missing backups and disk space are checked                                          |
| `MBP_SCHEDULE_MISFIRE_GRACE_SECONDS`        | `300`                  | Grace for a schedule missed while the panel was down                                          |
| `MBP_BOTS_ENABLED`                          | `true`                 | Master switch for the bots                                                                    |
| `COMPOSE_PROFILES`                          | —                      | `containers` turns the agent on                                                               |
| `MBP_DOCKER_GID`                            | `999`                  | Group of the Docker socket                                                                    |
| `MBP_DOCKER_SOCKET`                         | `/var/run/docker.sock` | Socket path (rootless Docker or Podman)                                                       |
| `MBP_PROJECTS_DIR`                          | `/opt/mbp-projects`    | Where deployed projects live                                                                  |
| `MBP_CONTAINER_MONITOR_SECONDS`             | `60`                   | How often containers are checked                                                              |
| `MBP_AGENT_REPO_URL`                        | this repository        | The git URL in the agent install commands                                                     |

After changing `.env`, run `docker compose up -d`.

@@article uninstall
@title Uninstalling
@summary Remove everything, or keep the data.

```bash
docker compose --profile containers down     # remove the containers; data is kept
docker compose --profile containers down -v  # also the volumes: the panel's database and local backup files!
```

> ! With `-v`, all local backups are deleted. Remote copies are not touched; delete them in the provider's console if no longer needed.

Then remove the panel's folder. On other servers, remove the agent with `docker compose -f docker-compose.agent.yml down -v`.

@@category faq faq FAQ

@@article faq
@title Frequently asked questions
@summary Short answers to common questions.

## A backup was made but is not in remote storage.

Check **Upload backups to remote storage** in Settings, and that database server's own choice (Always/Never/Global). The upload status and its error are shown under [Backups](/backups) ([guide](#remote-storage)).

## Why can't I delete a remote copy?

Remote copies are protected for 7 days after upload ([why](#remote-protection)).

## My database is not in the list.

The database user cannot see it; check its [privileges](#backup-user).

## A backup failed with "missing privileges".

Grant the user `SELECT, SHOW VIEW, TRIGGER, EVENT, LOCK TABLES`.

## How do I work on another server?

Press the **Current server** card at the top of the menu and choose the server ([guide](#current-server)).

## A database or project I added is not shown.

Another server is probably current. Choose the server you added it on in the Current server card.

## The bot does not answer.

- Under [Bots](/bots), it must show "Connected".
- You must be registered and active under "Bot admins".
- Message it in a private chat, not a group.
- Telegram on a server in Iran needs a proxy.

## The bot asks for a code to restart a container, but I have none.

At least one panel account needs [two-step verification](#two-factor); send that app's code.

## Can one Google Authenticator key be on several phones?

Yes; see [Recovery codes and several devices](#recovery-codes).

## The Containers page says the agent is unreachable.

On the panel's own server, [turn container management on](#containers-enable). For other servers, see [Server troubleshooting](#server-troubleshoot).

## I reinstalled a server and see "another certificate".

If you reinstalled the agent yourself (and its volume was removed), press **Connect** again under [Servers](/servers).

## A schedule did not run.

Look at the last result next to it; usually it is "No databases marked". Check the time zone too.

## I cannot open the panel from outside the server.

That is by design; the panel listens on the server only. Use an [SSH tunnel](#access).

## I forgot my password.

See [Forgotten password](#forgot-password).
