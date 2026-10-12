import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";

export type ContainerProblem = "crashed" | "restarting" | "unhealthy";
export type ContainerAction = "start" | "stop" | "restart";

export interface ContainerPort {
  private: number | null;
  public: number | null;
  type: string;
}

export interface ContainerSummary {
  id: string;
  name: string;
  image: string;
  state: string;
  health: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  oom_killed: boolean;
  restart_count: number;
  restart_policy: string;
  project: string | null;
  service: string | null;
  panel: string | null;
  ports: ContainerPort[];
  locked: boolean;
  monitored: boolean;
  problem: ContainerProblem | null;
}

export interface ContainerDetails extends ContainerSummary {
  image_id: string | null;
  hostname: string | null;
  env_names: string[];
  mounts: {
    type: string | null;
    source: string | null;
    destination: string | null;
    read_only: boolean;
  }[];
  networks: { name: string; ip: string | null }[];
  health_failing_streak: number | null;
  health_last_output: string | null;
  tty: boolean;
}

export interface ContainerStats {
  cpu_percent: number | null;
  memory_usage: number | null;
  memory_limit: number | null;
  memory_percent: number | null;
  net_rx: number | null;
  net_tx: number | null;
  block_read: number | null;
  block_write: number | null;
  pids: number | null;
}

export interface ServerInfo {
  docker: {
    version: string | null;
    api_version: string | null;
    os: string | null;
    kernel: string | null;
    cpus: number | null;
    memory_total: number | null;
    containers: number | null;
    running: number | null;
    stopped: number | null;
    paused: number | null;
    images: number | null;
    name: string | null;
  };
  host: {
    cpu_percent: number | null;
    load: number[] | null;
    memory_total: number | null;
    memory_available: number | null;
    disk_total: number | null;
    disk_free: number | null;
  };
}

export interface LogLine {
  stream: "stdout" | "stderr";
  time: string | null;
  text: string;
}

export interface ContainerSettings {
  read_only: boolean;
  hidden: string[];
  locked: string[];
  monitor_all: boolean;
  monitored: string[];
  cpu_percent: number;
  memory_percent: number;
  restart_count: number;
  restart_window_minutes: number;
  host_memory_percent: number;
  host_disk_percent: number;
  bot_logs: boolean;
}

export interface ContainerActionItem {
  id: number;
  created_at: string;
  actor: string;
  source: string;
  server_id: number | null;
  server_name: string;
  container: string;
  action: ContainerAction;
  result: string;
  detail: string | null;
}

export interface ContainerActionPage {
  items: ContainerActionItem[];
  total: number;
  page: number;
  page_size: number;
}

/** Live numbers refresh this often while the page is open. */
export const LIVE_MS = 5000;

/** null: the panel's own server. */
export type ServerRef = number | null;

export const containerKeys = {
  all: ["containers"] as const,
  list: (server: ServerRef) => ["containers", server, "list"] as const,
  info: (server: ServerRef) => ["containers", server, "info"] as const,
  stats: (server: ServerRef) => ["containers", server, "stats"] as const,
  one: (server: ServerRef, name: string) => ["containers", server, "one", name] as const,
  logs: (server: ServerRef, name: string, tail: number) =>
    ["containers", server, "logs", name, tail] as const,
  settings: (server: ServerRef) => ["containers", server, "settings"] as const,
  actions: (server: ServerRef, page: number) => ["containers", server, "actions", page] as const,
};

const enc = encodeURIComponent;

/** The `server` query parameter, joined to `path` (which may already have a query). */
function withServer(path: string, server: ServerRef): string {
  if (server === null) return path;
  return `${path}${path.includes("?") ? "&" : "?"}server=${server}`;
}

export function useContainers(server: ServerRef = null, enabled = true) {
  return useQuery({
    queryKey: containerKeys.list(server),
    queryFn: () =>
      apiFetch<{ containers: ContainerSummary[]; read_only: boolean }>(
        withServer("/containers", server),
      ),
    refetchInterval: LIVE_MS,
    enabled,
  });
}

export function useServerInfo(server: ServerRef, enabled = true) {
  return useQuery({
    queryKey: containerKeys.info(server),
    queryFn: () => apiFetch<ServerInfo>(withServer("/containers/-/info", server)),
    refetchInterval: LIVE_MS,
    enabled,
  });
}

export function useContainerStats(server: ServerRef, enabled = true) {
  return useQuery({
    queryKey: containerKeys.stats(server),
    queryFn: () =>
      apiFetch<{ stats: Record<string, ContainerStats | null> }>(
        withServer("/containers/-/stats", server),
      ),
    refetchInterval: LIVE_MS,
    enabled,
  });
}

export function useContainer(server: ServerRef, name: string | null) {
  return useQuery({
    queryKey: containerKeys.one(server, name ?? ""),
    queryFn: () => apiFetch<ContainerDetails>(withServer(`/containers/${enc(name ?? "")}`, server)),
    enabled: Boolean(name),
  });
}

export function useContainerLogs(
  server: ServerRef,
  name: string | null,
  tail: number,
  follow: boolean,
) {
  return useQuery({
    queryKey: containerKeys.logs(server, name ?? "", tail),
    queryFn: () =>
      apiFetch<{ lines: LogLine[]; truncated: boolean }>(
        withServer(`/containers/${enc(name ?? "")}/logs?tail=${tail}`, server),
      ),
    enabled: Boolean(name),
    refetchInterval: follow ? 3000 : false,
    placeholderData: keepPreviousData,
  });
}

export function useContainerAction(server: ServerRef) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, action }: { name: string; action: ContainerAction }) =>
      apiFetch<{ container: ContainerSummary }>(
        withServer(`/containers/${enc(name)}/${action}`, server),
        { method: "POST" },
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: containerKeys.all }),
  });
}

export function useContainerSettings(server: ServerRef) {
  return useQuery({
    queryKey: containerKeys.settings(server),
    queryFn: () => apiFetch<ContainerSettings>(withServer("/containers/-/settings", server)),
  });
}

export function useSaveContainerSettings(server: ServerRef) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ContainerSettings) =>
      apiFetch<ContainerSettings>(withServer("/containers/-/settings", server), {
        method: "PUT",
        body,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(containerKeys.settings(server), data);
      void queryClient.invalidateQueries({ queryKey: containerKeys.list(server) });
    },
  });
}

export function useContainerActions(server: ServerRef, page: number) {
  return useQuery({
    queryKey: containerKeys.actions(server, page),
    queryFn: () =>
      apiFetch<ContainerActionPage>(
        withServer(`/containers/-/actions?page=${page}&page_size=20`, server),
      ),
    placeholderData: keepPreviousData,
  });
}
