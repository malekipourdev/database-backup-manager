import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import { backupKeys } from "./backups";

export interface RemoteStorage {
  enabled: boolean;
  provider: "s3";
  endpoint_url: string;
  region: string;
  bucket: string;
  prefix: string;
  access_key_id: string;
  has_secret: boolean;
  force_path_style: boolean;
}

export interface RemoteStorageInput {
  enabled: boolean;
  endpoint_url: string;
  region: string;
  bucket: string;
  prefix: string;
  access_key_id: string;
  /** Empty keeps the stored secret. */
  secret_access_key: string;
  force_path_style: boolean;
}

export interface RemoteTestResult {
  ok: boolean;
  error_code: string | null;
  error_detail: string | null;
}

export interface RetentionPolicy {
  local_keep_last: number | null;
  local_max_age_days: number | null;
  remote_keep_last: number | null;
  remote_max_age_days: number | null;
}

export type RemoteUpload = "inherit" | "enabled" | "disabled";

export interface InstanceStoragePolicy {
  remote_upload: RemoteUpload;
  retention_override: boolean;
  retention: RetentionPolicy;
  effective_upload: boolean;
  effective_retention: RetentionPolicy;
}

export interface RetentionItem {
  run_id: number;
  target: "local" | "remote";
  instance_name: string;
  database_name: string;
  file_name: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
}

export interface RetentionReport {
  dry_run: boolean;
  deleted: RetentionItem[];
  errors: RetentionItem[];
}

export const EMPTY_POLICY: RetentionPolicy = {
  local_keep_last: null,
  local_max_age_days: null,
  remote_keep_last: null,
  remote_max_age_days: null,
};

export const storageKeys = {
  remote: ["remote-storage"] as const,
  retention: ["retention"] as const,
  instancePolicy: (id: number) => ["storage-policy", id] as const,
};

export function useRemoteStorage() {
  return useQuery({
    queryKey: storageKeys.remote,
    queryFn: () => apiFetch<RemoteStorage>("/remote-storage"),
  });
}

export function useSaveRemoteStorage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RemoteStorageInput) =>
      apiFetch<RemoteStorage>("/remote-storage", { method: "PUT", body }),
    onSuccess: (data) => {
      queryClient.setQueryData(storageKeys.remote, data);
      void queryClient.invalidateQueries({ queryKey: ["storage-policy"] });
    },
  });
}

export function useTestRemoteStorage() {
  return useMutation({
    mutationFn: (body: RemoteStorageInput) =>
      apiFetch<RemoteTestResult>("/remote-storage/test", { method: "POST", body }),
  });
}

export function useRetention() {
  return useQuery({
    queryKey: storageKeys.retention,
    queryFn: () => apiFetch<RetentionPolicy>("/retention"),
  });
}

export function useSaveRetention() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RetentionPolicy) =>
      apiFetch<RetentionPolicy>("/retention", { method: "PUT", body }),
    onSuccess: (data) => {
      queryClient.setQueryData(storageKeys.retention, data);
      void queryClient.invalidateQueries({ queryKey: ["storage-policy"] });
    },
  });
}

export function useApplyRetention() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dryRun: boolean) =>
      apiFetch<RetentionReport>("/retention/apply", {
        method: "POST",
        body: { dry_run: dryRun },
      }),
    onSuccess: (report) => {
      if (!report.dry_run) void queryClient.invalidateQueries({ queryKey: backupKeys.all });
    },
  });
}

export function useInstanceStoragePolicy(instanceId: number) {
  return useQuery({
    queryKey: storageKeys.instancePolicy(instanceId),
    queryFn: () => apiFetch<InstanceStoragePolicy>(`/instances/${instanceId}/storage-policy`),
  });
}

export function useSaveInstanceStoragePolicy(instanceId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      remote_upload: RemoteUpload;
      retention_override: boolean;
      retention: RetentionPolicy;
    }) =>
      apiFetch<InstanceStoragePolicy>(`/instances/${instanceId}/storage-policy`, {
        method: "PUT",
        body,
      }),
    onSuccess: (data) => queryClient.setQueryData(storageKeys.instancePolicy(instanceId), data),
  });
}
