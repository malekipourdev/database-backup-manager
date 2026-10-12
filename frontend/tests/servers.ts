import type { Server } from "../src/api/servers";
import type { CurrentServer } from "../src/server/CurrentServer";

const base: Server = {
  id: 1,
  name: "main",
  kind: "local",
  host: null,
  port: null,
  notes: "",
  paired: true,
  cert_fingerprint: null,
  paired_at: null,
  last_seen_at: "2026-10-12T08:00:00Z",
  last_error: null,
  agent_hostname: "panel-host",
  docker_version: "27.3.1",
  projects: 0,
  instances: 0,
  created_at: "2026-10-12T08:00:00Z",
};

export const LOCAL: Server = base;
export const EDGE: Server = {
  ...base,
  id: 4,
  name: "edge",
  kind: "remote",
  host: "203.0.113.7",
  port: 8443,
};
export const NEW: Server = { ...EDGE, id: 5, name: "new", paired: false, last_seen_at: null };

/** A current-server context for rendering a page "on" one server. */
export function currentOn(server: Server, servers = [LOCAL, EDGE, NEW]): CurrentServer {
  return { server, id: server.id, servers, select: () => undefined, ready: true, error: null };
}
