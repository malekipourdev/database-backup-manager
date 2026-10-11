import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";

export type RunStatus = "queued" | "running" | "success" | "failed";
export type Compression = "gzip" | "bzip2" | "none";
export type SortColumn =
  "requested_at" | "duration_ms" | "file_size" | "instance_name" | "database_name" | "status";

export interface BackupRun {
  id: number;
  instance_id: number | null;
  instance_name: string;
  database_name: string;
  trigger: "all" | "single";
  status: RunStatus;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  elapsed_ms: number | null;
  bytes_processed: number;
  file_size: number | null;
  compression: Compression | null;
  checksum_sha256: string | null;
  file_name: string | null;
  file_available: boolean;
  server_type: "mysql" | "mariadb" | null;
  server_version: string | null;
  error_code: string | null;
  error_message: string | null;
}

export interface SkippedDatabase {
  database: string;
  reason: "already_in_progress";
}

export interface StartBackupResponse {
  created: BackupRun[];
  skipped: SkippedDatabase[];
}

export interface RunPage {
  items: BackupRun[];
  total: number;
  page: number;
  page_size: number;
}

export interface RunQuery {
  instanceId?: number;
  database?: string;
  statuses?: RunStatus[];
  from?: string;
  to?: string;
  sort?: SortColumn;
  order?: "asc" | "desc";
  page?: number;
  pageSize?: number;
}

export interface BackupSettings {
  storage_dir: string;
  name_pattern: string;
  compression: Compression;
}

export interface BackupOverrides {
  storage_dir: string | null;
  name_pattern: string | null;
  compression: Compression | null;
}

export interface InstanceBackupSettings {
  overrides: BackupOverrides;
  effective: BackupSettings;
}

/** How often run status is refreshed while any shown run is queued or running. */
export const POLL_MS = 2000;

export const backupKeys = {
  all: ["backups"] as const,
  list: (query: RunQuery) => ["backups", "list", query] as const,
  run: (id: number) => ["backups", "run", id] as const,
  settings: ["backup-settings"] as const,
  instanceSettings: (id: number) => ["backup-settings", id] as const,
};

export function isActive(run: BackupRun): boolean {
  return run.status === "queued" || run.status === "running";
}

export function pollInterval(runs: BackupRun[] | undefined): number | false {
  return runs?.some(isActive) ? POLL_MS : false;
}

export function runQueryString(query: RunQuery): string {
  const params = new URLSearchParams();
  if (query.instanceId !== undefined) params.set("instance_id", String(query.instanceId));
  if (query.database) params.set("database", query.database);
  for (const status of query.statuses ?? []) params.append("status", status);
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);
  if (query.sort) params.set("sort", query.sort);
  if (query.order) params.set("order", query.order);
  if (query.page) params.set("page", String(query.page));
  if (query.pageSize) params.set("page_size", String(query.pageSize));
  return params.toString();
}

export function fetchRuns(query: RunQuery): Promise<RunPage> {
  return apiFetch<RunPage>(`/backups/runs?${runQueryString(query)}`);
}

export function useRunHistory(query: RunQuery) {
  return useQuery({
    queryKey: backupKeys.list(query),
    queryFn: () => fetchRuns(query),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => pollInterval(q.state.data?.items),
  });
}

export function useInstanceRuns(instanceId: number) {
  return useRunHistory({ instanceId, page: 1, pageSize: 10 });
}

export function useRun(runId: number) {
  return useQuery({
    queryKey: backupKeys.run(runId),
    queryFn: () => apiFetch<BackupRun>(`/backups/runs/${runId}`),
    refetchInterval: (q) => pollInterval(q.state.data ? [q.state.data] : undefined),
  });
}

export function useStartBackup(instanceId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { scope: "all" } | { scope: "single"; database: string }) =>
      apiFetch<StartBackupResponse>(`/instances/${instanceId}/backups`, {
        method: "POST",
        body,
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: backupKeys.all }),
  });
}

export function useDeleteRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: number) => apiFetch<void>(`/backups/runs/${runId}`, { method: "DELETE" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: backupKeys.all }),
  });
}

export function downloadUrl(runId: number): string {
  return `/api/backups/runs/${runId}/download`;
}

/** True if no newer successful backup of the same database exists. */
export async function isLatestSuccess(run: BackupRun): Promise<boolean> {
  if (run.status !== "success" || run.instance_id === null) return false;
  const page = await fetchRuns({
    instanceId: run.instance_id,
    database: run.database_name,
    statuses: ["success"],
    pageSize: 1,
  });
  return page.items[0]?.id === run.id;
}

export function useBackupSettings() {
  return useQuery({
    queryKey: backupKeys.settings,
    queryFn: () => apiFetch<BackupSettings>("/backup-settings"),
  });
}

export function useSaveBackupSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: BackupSettings) =>
      apiFetch<BackupSettings>("/backup-settings", { method: "PUT", body }),
    onSuccess: (data) => {
      queryClient.setQueryData(backupKeys.settings, data);
      void queryClient.invalidateQueries({ queryKey: ["backup-settings"] });
    },
  });
}

export function useInstanceBackupSettings(instanceId: number) {
  return useQuery({
    queryKey: backupKeys.instanceSettings(instanceId),
    queryFn: () => apiFetch<InstanceBackupSettings>(`/instances/${instanceId}/backup-settings`),
  });
}

export function useSaveInstanceBackupSettings(instanceId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: BackupOverrides) =>
      apiFetch<InstanceBackupSettings>(`/instances/${instanceId}/backup-settings`, {
        method: "PUT",
        body,
      }),
    onSuccess: (data) => queryClient.setQueryData(backupKeys.instanceSettings(instanceId), data),
  });
}

export function previewPattern(body: BackupSettings): Promise<{ path: string }> {
  return apiFetch<{ path: string }>("/backup-settings/preview", { method: "POST", body });
}
