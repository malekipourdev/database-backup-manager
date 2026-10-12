"""The Docker agent: the only component with access to docker.sock.

It runs as its own container (compose profile "containers"), listens only on the internal
network, answers only the backend (shared token), and knows a fixed set of operations:
list, inspect, stats, logs, start, stop and restart. It never runs commands, creates or
removes containers, or returns environment variable values.
"""
