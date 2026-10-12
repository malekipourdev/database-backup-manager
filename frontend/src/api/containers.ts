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

export const containerKeys = {
  all: ["containers"] as const,
  list: ["containers", "list"] as const,
  info: ["containers", "info"] as const,
  stats: ["containers", "stats"] as const,
  one: (name: string) => ["containers", "one", name] as const,
  oneStats: (name: string) => ["containers", "one", name, "stats"] as const,
  logs: (name: string, tail: number) => ["containers", "logs", name, tail] as const,
  settings: ["containers", "settings"] as const,
  actions: (page: number) => ["containers", "actions", page] as const,
};

const enc = encodeURIComponent;

export function useContainers() {
  return useQuery({
    queryKey: containerKeys.list,
    queryFn: () => apiFetch<{ containers: ContainerSummary[]; read_only: boolean }>("/containers"),
    refetchInterval: LIVE_MS,
  });
}

export function useServerInfo(enabled = true) {
  return useQuery({
    queryKey: containerKeys.info,
    queryFn: () => apiFetch<ServerInfo>("/containers/-/info"),
    refetchInterval: LIVE_MS,
    enabled,
  });
}

export function useContainerStats(enabled = true) {
  return useQuery({
    queryKey: containerKeys.stats,
    queryFn: () =>
      apiFetch<{ stats: Record<string, ContainerStats | null> }>("/containers/-/stats"),
    refetchInterval: LIVE_MS,
    enabled,
  });
}

export function useContainer(name: string | null) {
  return useQuery({
    queryKey: containerKeys.one(name ?? ""),
    queryFn: () => apiFetch<ContainerDetails>(`/containers/${enc(name ?? "")}`),
    enabled: Boolean(name),
  });
}

export function useContainerLogs(name: string | null, tail: number, follow: boolean) {
  return useQuery({
    queryKey: containerKeys.logs(name ?? "", tail),
    queryFn: () =>
      apiFetch<{ lines: LogLine[]; truncated: boolean }>(
        `/containers/${enc(name ?? "")}/logs?tail=${tail}`,
      ),
    enabled: Boolean(name),
    refetchInterval: follow ? 3000 : false,
    placeholderData: keepPreviousData,
  });
}

export function useContainerAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, action }: { name: string; action: ContainerAction }) =>
      apiFetch<{ container: ContainerSummary }>(`/containers/${enc(name)}/${action}`, {
        method: "POST",
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: containerKeys.all }),
  });
}

export function useContainerSettings() {
  return useQuery({
    queryKey: containerKeys.settings,
    queryFn: () => apiFetch<ContainerSettings>("/containers/-/settings"),
  });
}

export function useSaveContainerSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ContainerSettings) =>
      apiFetch<ContainerSettings>("/containers/-/settings", { method: "PUT", body }),
    onSuccess: (data) => {
      queryClient.setQueryData(containerKeys.settings, data);
      void queryClient.invalidateQueries({ queryKey: containerKeys.list });
    },
  });
}

export function useContainerActions(page: number) {
  return useQuery({
    queryKey: containerKeys.actions(page),
    queryFn: () => apiFetch<ContainerActionPage>(`/containers/-/actions?page=${page}&page_size=20`),
    placeholderData: keepPreviousData,
  });
}
