"""The agent: the only component with access to docker.sock.

It runs as its own container: next to the panel (compose profile "containers", internal
network only) or on another server the panel manages (docker-compose.agent.yml, HTTPS with
its own certificate and token). It answers only the panel and knows a fixed set of
operations: container list/inspect/stats/logs/start/stop/restart, deploys of the panel's
projects, connection tests, database lists and dumps for backups, and reading the web
servers' configuration (the host's /etc, mounted read-only). It never runs
arbitrary commands or returns environment variable values.
"""

# Bumped when the panel needs operations an older agent does not have.
PROTOCOL = 2
