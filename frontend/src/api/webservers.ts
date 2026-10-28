import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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
  /** False: in sites-available (or a conf.d file turned off) but not loaded by the server. */
  enabled: boolean;
  /** Served by its maintenance page for now. */
  maintenance?: boolean;
  /** The panel's maintenance page itself: not listed. */
  maintenance_page?: boolean;
  logs?: { access?: string | null; error?: string | null };
}

export interface WebProblem {
  kind: "broken_link" | "unreadable" | "include_missing" | "too_deep" | "other";
  path?: string | null;
  /** broken_link: where the link points. */
  target?: string | null;
  /** unreadable: not_found | permission_denied | too_large | unreadable */
  reason?: string | null;
  source?: string | null;
  line?: number | null;
  message?: string | null;
}

export interface WebServer {
  kind: WebServerKind;
  config: string;
  error: string | null;
  warnings: string[];
  problems?: WebProblem[];
  files: number;
  sites: WebSite[];
}

export interface WebServerList {
  /** False: the host's /etc is not mounted in the agent. */
  available: boolean;
  servers: WebServer[];
}

export interface WebServiceStatus {
  kind: WebServerKind;
  service: string;
  state: string;
  sub_state: string | null;
  since: string | null;
  pid: number | null;
  version: string | null;
  last_reload: string | null;
  panel_reload: string | null;
  systemd: boolean;
}

export interface WebResult {
  ok: boolean;
  code: string | null;
  output: string;
  path?: string | null;
}

export interface WebFile {
  path: string;
  content: string;
  sha256: string;
  size: number;
}

export interface WebCertificate {
  subject: string | null;
  names: string[];
  issuer: string | null;
  not_before: string | null;
  not_after: string | null;
  error: string | null;
}

export interface CertbotStatus {
  installed: boolean;
  version: string | null;
  auto_renew: string | null;
  package_manager: string | null;
}

export interface WebJob {
  id: string;
  action: string;
  target: string;
  status: "running" | "success" | "failed";
  output: string;
  started_at: string;
  finished_at: string | null;
}

export interface WebSettings {
  read_only: boolean;
  cert_warning_days: number;
  check_interval_minutes: number;
  check_timeout_seconds: number;
  check_failures: number;
  acme_email: string | null;
}

export interface WebActionItem {
  id: number;
  created_at: string;
  actor: string;
  source: string;
  server_id: number | null;
  server_name: string;
  kind: string;
  action: string;
  target: string;
  result: string;
  output: string | null;
}

export interface WebCheckResult {
  checked_at: string;
  ok: boolean;
  code: number | null;
  ms: number | null;
  error: string | null;
}

export interface WebCheck {
  id: number;
  server_id: number;
  url: string;
  enabled: boolean;
  created_at: string;
  last_checked_at: string | null;
  status: "up" | "down" | null;
  last_code: number | null;
  last_ms: number | null;
  last_error: string | null;
  failures: number;
  down_since: string | null;
  uptime: number | null;
  recent: WebCheckResult[];
}

export type SiteTemplate = "proxy" | "php" | "static" | "redirect";

export interface NewSite {
  template: SiteTemplate;
  domains: string[];
  name?: string | null;
  target?: string | null;
  root?: string | null;
  php_fpm?: string | null;
  permanent?: boolean;
  keep_path?: boolean;
}

export const webKeys = {
  all: ["webservers"] as const,
  list: (server: ServerRef) => ["webservers", server, "list"] as const,
  status: (server: ServerRef) => ["webservers", server, "status"] as const,
  certificates: (server: ServerRef) => ["webservers", server, "certificates"] as const,
  certbot: (server: ServerRef) => ["webservers", server, "certbot"] as const,
  sockets: (server: ServerRef) => ["webservers", server, "sockets"] as const,
  file: (server: ServerRef, kind: string, path: string) =>
    ["webservers", server, "file", kind, path] as const,
  backups: (server: ServerRef, kind: string, path: string) =>
    ["webservers", server, "backups", kind, path] as const,
  logs: (server: ServerRef, kind: string, path: string, lines: number) =>
    ["webservers", server, "logs", kind, path, lines] as const,
  settings: (server: ServerRef) => ["webservers", server, "settings"] as const,
  actions: (server: ServerRef, page: number) => ["webservers", server, "actions", page] as const,
  checks: (server: ServerRef) => ["webservers", server, "checks"] as const,
  job: (server: ServerRef, id: string) => ["webservers", server, "job", id] as const,
};

const enc = encodeURIComponent;

/** The `server` query parameter, joined to `path` (which may already have a query). */
function withServer(path: string, server: ServerRef): string {
  if (server === null) return path;
  return `${path}${path.includes("?") ? "&" : "?"}server=${server}`;
}

export function useWebServers(server: ServerRef) {
  return useQuery({
    queryKey: webKeys.list(server),
    queryFn: () => apiFetch<WebServerList>(withServer("/webservers", server)),
  });
}

export function useWebStatus(server: ServerRef, enabled = true) {
  return useQuery({
    queryKey: webKeys.status(server),
    queryFn: () =>
      apiFetch<{ servers: WebServiceStatus[] }>(withServer("/webservers/-/status", server)),
    enabled,
    refetchInterval: 30_000,
  });
}

export function useCertificates(server: ServerRef, enabled = true) {
  return useQuery({
    queryKey: webKeys.certificates(server),
    queryFn: () =>
      apiFetch<{ certificates: Record<string, WebCertificate> }>(
        withServer("/webservers/-/certificates", server),
      ),
    enabled,
  });
}

export function useCertbot(server: ServerRef, enabled = true) {
  return useQuery({
    queryKey: webKeys.certbot(server),
    queryFn: () => apiFetch<CertbotStatus>(withServer("/webservers/-/certbot", server)),
    enabled,
  });
}

export function usePhpSockets(server: ServerRef, enabled: boolean) {
  return useQuery({
    queryKey: webKeys.sockets(server),
    queryFn: () => apiFetch<{ sockets: string[] }>(withServer("/webservers/-/php-sockets", server)),
    enabled,
  });
}

export function useWebFile(server: ServerRef, kind: string, path: string | null) {
  return useQuery({
    queryKey: webKeys.file(server, kind, path ?? ""),
    queryFn: () =>
      apiFetch<WebFile>(withServer(`/webservers/${kind}/file?path=${enc(path ?? "")}`, server)),
    enabled: Boolean(path),
  });
}

export function useWebBackups(server: ServerRef, kind: string, path: string | null) {
  return useQuery({
    queryKey: webKeys.backups(server, kind, path ?? ""),
    queryFn: () =>
      apiFetch<{ path: string; backups: string[] }>(
        withServer(`/webservers/${kind}/backups?path=${enc(path ?? "")}`, server),
      ),
    enabled: Boolean(path),
  });
}

export function fetchBackup(server: ServerRef, kind: string, path: string, name: string) {
  return apiFetch<{ content: string }>(
    withServer(`/webservers/${kind}/backup?path=${enc(path)}&name=${enc(name)}`, server),
  );
}

export function useWebLogs(server: ServerRef, kind: string, path: string | null, lines: number) {
  return useQuery({
    queryKey: webKeys.logs(server, kind, path ?? "", lines),
    queryFn: () =>
      apiFetch<{ path: string; lines: string[] }>(
        withServer(`/webservers/${kind}/logs?path=${enc(path ?? "")}&lines=${lines}`, server),
      ),
    enabled: Boolean(path),
  });
}

export function useWebSettings(server: ServerRef) {
  return useQuery({
    queryKey: webKeys.settings(server),
    queryFn: () => apiFetch<WebSettings>(withServer("/webservers/-/settings", server)),
  });
}

export function useSaveWebSettings(server: ServerRef) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: WebSettings) =>
      apiFetch<WebSettings>(withServer("/webservers/-/settings", server), { method: "PUT", body }),
    onSuccess: (data) => client.setQueryData(webKeys.settings(server), data),
  });
}

export function useWebActions(server: ServerRef, page: number) {
  return useQuery({
    queryKey: webKeys.actions(server, page),
    queryFn: () =>
      apiFetch<{ items: WebActionItem[]; total: number; page: number; page_size: number }>(
        `/webservers/-/actions?page=${page}${server === null ? "" : `&server=${server}`}`,
      ),
  });
}

/** Every change reloads what it may have changed: sites, status, files, the audit log. */
function useRefresh(server: ServerRef) {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["webservers", server] });
}

export function useWebChange<T>(server: ServerRef, request: (body: T) => Promise<WebResult>) {
  const refresh = useRefresh(server);
  return useMutation({ mutationFn: request, onSettled: refresh });
}

export function useControl(server: ServerRef) {
  return useWebChange(server, ({ kind, action }: { kind: string; action: string }) =>
    apiFetch<WebResult>(withServer(`/webservers/${kind}/control/${action}`, server), {
      method: "POST",
    }),
  );
}

export function useConfigTest(server: ServerRef) {
  return useMutation({
    mutationFn: (kind: string) =>
      apiFetch<{ ok: boolean; output: string }>(withServer(`/webservers/${kind}/test`, server), {
        method: "POST",
      }),
  });
}

export function useSaveFile(server: ServerRef) {
  return useWebChange(
    server,
    ({ kind, ...body }: { kind: string; path: string; content: string; sha256: string | null }) =>
      apiFetch<WebResult>(withServer(`/webservers/${kind}/file`, server), { method: "PUT", body }),
  );
}

export function useRestore(server: ServerRef) {
  return useWebChange(server, ({ kind, ...body }: { kind: string; path: string; backup: string }) =>
    apiFetch<WebResult>(withServer(`/webservers/${kind}/restore`, server), {
      method: "POST",
      body,
    }),
  );
}

export function useSetEnabled(server: ServerRef) {
  return useWebChange(
    server,
    ({ kind, ...body }: { kind: string; path: string; enabled: boolean }) =>
      apiFetch<WebResult>(withServer(`/webservers/${kind}/enabled`, server), {
        method: "POST",
        body,
      }),
  );
}

export function useSetMaintenance(server: ServerRef) {
  return useWebChange(server, ({ kind, ...body }: { kind: string; path: string; on: boolean }) =>
    apiFetch<WebResult>(withServer(`/webservers/${kind}/maintenance`, server), {
      method: "POST",
      body,
    }),
  );
}

export function useRemoveBrokenLinks(server: ServerRef) {
  return useWebChange(server, ({ kind, paths }: { kind: string; paths: string[] }) =>
    apiFetch<WebResult & { removed?: string[] | null }>(
      withServer(`/webservers/${kind}/broken-links/remove`, server),
      { method: "POST", body: { paths } },
    ),
  );
}

export function useCreateSite(server: ServerRef) {
  return useWebChange(server, ({ kind, ...body }: NewSite & { kind: string }) =>
    apiFetch<WebResult>(withServer(`/webservers/${kind}/sites`, server), {
      method: "POST",
      body,
    }),
  );
}

export function useStartJob(server: ServerRef) {
  const refresh = useRefresh(server);
  return useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) =>
      apiFetch<WebJob>(withServer(path, server), { method: "POST", body }),
    onSettled: refresh,
  });
}

/** A certbot job, polled until it ends. */
export function useWebJob(server: ServerRef, id: string | null) {
  const refresh = useRefresh(server);
  return useQuery({
    queryKey: webKeys.job(server, id ?? ""),
    queryFn: async () => {
      const job = await apiFetch<WebJob>(withServer(`/webservers/-/jobs/${enc(id ?? "")}`, server));
      if (job.status !== "running") void refresh();
      return job;
    },
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });
}

export function useWebChecks(server: ServerRef) {
  return useQuery({
    queryKey: webKeys.checks(server),
    queryFn: () => apiFetch<{ checks: WebCheck[] }>(withServer("/webservers/-/checks", server)),
    refetchInterval: 30_000,
  });
}

export function useCheckMutations(server: ServerRef) {
  const client = useQueryClient();
  const onSettled = () => client.invalidateQueries({ queryKey: webKeys.checks(server) });
  return {
    add: useMutation({
      mutationFn: (url: string) =>
        apiFetch<WebCheck>(withServer("/webservers/-/checks", server), {
          method: "POST",
          body: { url },
        }),
      onSettled,
    }),
    toggle: useMutation({
      mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
        apiFetch<WebCheck>(withServer(`/webservers/-/checks/${id}`, server), {
          method: "PATCH",
          body: { enabled },
        }),
      onSettled,
    }),
    remove: useMutation({
      mutationFn: (id: number) =>
        apiFetch<void>(withServer(`/webservers/-/checks/${id}`, server), { method: "DELETE" }),
      onSettled,
    }),
    run: useMutation({
      mutationFn: (id: number) =>
        apiFetch<WebCheck>(withServer(`/webservers/-/checks/${id}/run`, server), {
          method: "POST",
        }),
      onSettled,
    }),
  };
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
  maintenance: boolean;
}

export function domainsOf(servers: WebServer[]): Domain[] {
  const byKey = new Map<string, Domain>();
  for (const ws of servers) {
    for (const site of ws.sites) {
      if (site.maintenance_page) continue;
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
            maintenance: false,
          };
          byKey.set(key, domain);
        }
        domain.sites.push(site);
        domain.ssl ||= site.ssl;
        domain.maintenance ||= Boolean(site.maintenance);
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

/** Whole days until a certificate expires (negative once expired). */
export function daysLeft(cert: WebCertificate | undefined, now = Date.now()): number | null {
  if (!cert?.not_after) return null;
  return Math.floor((new Date(cert.not_after).getTime() - now) / 86_400_000);
}
