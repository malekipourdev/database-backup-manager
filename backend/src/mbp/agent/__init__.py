"""The agent: the only component with access to docker.sock.

It runs as its own container: next to the panel (compose profile "containers", internal
network only) or on another server the panel manages (docker-compose.agent.yml, HTTPS with
its own certificate and token). It answers only the panel and knows a fixed set of
operations: container list/inspect/stats/logs/start/stop/restart, deploys of the panel's
projects, connection tests, database lists and dumps for backups, and managing the host's
web servers (mbp.agent.webmanage: fixed commands such as `nginx -t` and `systemctl reload`,
run on the host by a short-lived helper container, every change tested and undone on
failure). It never runs arbitrary commands or returns environment variable values.
"""

# Bumped when the panel needs operations an older agent does not have.
PROTOCOL = 2
