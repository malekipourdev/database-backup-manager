import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { ServerRef } from "./containers";

export type WebServerKind = "nginx" | "apache";

export interface WebBackend {
  kind: "proxy" | "fastcgi" | "uwsgi" | "grpc" | "scgi";
  target: string;
  /** The servers of an nginx upstream named by the target. */
  servers: string[];
}

/** One server block (nginx) or VirtualHost (Apache). */
export interface WebSite {
  server: WebServerKind;
  /** Empty for a catch-all block. */
  names: string[];
  ports: number[];
  ssl: boolean;
  default_server: boolean;
  root: string | null;
  redirect: string | null;
  backends: WebBackend[];
  certificate: string | null;
  file: string;
  line: number;
  /** False: in sites-available but not loaded by the server. */
  enabled: boolean;
}

export interface WebServer {
  kind: WebServerKind;
  config: string;
  error: string | null;
  warnings: string[];
  files: number;
  sites: WebSite[];
}

export interface WebServerList {
  /** False: the host's /etc is not mounted in the agent. */
  available: boolean;
  servers: WebServer[];
}

export const webServerKeys = {
  list: (server: ServerRef) => ["webservers", server] as const,
};

export function useWebServers(server: ServerRef) {
  return useQuery({
    queryKey: webServerKeys.list(server),
    queryFn: () =>
      apiFetch<WebServerList>(server === null ? "/webservers" : `/webservers?server=${server}`),
  });
}

/** One row of the domains list: every block of the same name on the same web server. */
export interface Domain {
  /** The name; "" for catch-all blocks. */
  name: string;
  server: WebServerKind;
  sites: WebSite[];
  ports: number[];
  ssl: boolean;
  enabled: boolean;
}

export function domainsOf(servers: WebServer[]): Domain[] {
  const byKey = new Map<string, Domain>();
  for (const ws of servers) {
    for (const site of ws.sites) {
      for (const name of site.names.length ? site.names : [""]) {
        const key = `${ws.kind}\u0000${site.enabled}\u0000${name}`;
        let domain = byKey.get(key);
        if (!domain) {
          domain = {
            name,
            server: ws.kind,
            sites: [],
            ports: [],
            ssl: false,
            enabled: site.enabled,
          };
          byKey.set(key, domain);
        }
        domain.sites.push(site);
        domain.ssl ||= site.ssl;
        domain.ports = [...new Set([...domain.ports, ...site.ports])].sort((a, b) => a - b);
      }
    }
  }
  return [...byKey.values()].sort(
    (a, b) =>
      Number(b.enabled) - Number(a.enabled) ||
      Number(a.name === "") - Number(b.name === "") ||
      a.name.localeCompare(b.name) ||
      a.server.localeCompare(b.server),
  );
}

/** What a domain serves: the first block that is not only a redirect. */
export function servedBy(domain: Domain): WebSite {
  return domain.sites.find((s) => !s.redirect) ?? domain.sites[0];
}
