import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";

export type AuthType = "none" | "token" | "ssh_key";
export type DeployStatus = "queued" | "running" | "success" | "failed";

export interface DeploymentSummary {
  id: number;
  project_id: number | null;
  project_name: string;
  status: DeployStatus;
  step: string | null;
  ref: string;
  commit_sha: string | null;
  commit_message: string | null;
  trigger: string;
  actor: string;
  error_code: string | null;
  error_detail: string | null;
  backup_run_ids: number[];
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface DeploymentDetail extends DeploymentSummary {
  log: string;
  log_size: number;
}

export interface Project {
  id: number;
  name: string;
  server_id: number;
  server_name: string;
  repo_url: string;
  branch: string;
  compose_file: string;
  auth_type: AuthType;
  has_credential: boolean;
  env_names: string[];
  backup_instance_id: number | null;
  backup_databases: string[];
  backup_required: boolean;
  created_at: string;
  updated_at: string;
  last_deployment: DeploymentSummary | null;
  last_success: DeploymentSummary | null;
}

export interface ProjectInput {
  name: string;
  /** null: the panel's own server (new project) or unchanged. */
  server_id: number | null;
  repo_url: string;
  branch: string;
  compose_file: string;
  auth_type: AuthType;
  /** Empty keeps the stored credential. */
  credential: string;
  clear_credential: boolean;
  /** value null keeps the stored value. */
  env: { name: string; value: string | null }[];
  backup_instance_id: number | null;
  backup_databases: string[];
  backup_required: boolean;
}

export interface ProjectState {
  available: boolean;
  error_code: string | null;
  exists: boolean;
  commit_sha: string | null;
  commit_message: string | null;
}

export const projectKeys = {
  all: ["projects"] as const,
  list: ["projects", "list"] as const,
  one: (id: number) => ["projects", id] as const,
  state: (id: number) => ["projects", id, "state"] as const,
  deployments: (id: number, page: number) => ["projects", id, "deployments", page] as const,
  deployment: (id: number) => ["deployments", id] as const,
};

export const isActive = (d: DeploymentSummary | null | undefined) =>
  d?.status === "queued" || d?.status === "running";

export function useProjects() {
  return useQuery({
    queryKey: projectKeys.list,
    queryFn: () => apiFetch<Project[]>("/projects"),
    refetchInterval: (query) =>
      query.state.data?.some((p) => isActive(p.last_deployment)) ? 3000 : false,
  });
}

export function useProject(id: number, enabled = true) {
  return useQuery({
    queryKey: projectKeys.one(id),
    queryFn: () => apiFetch<Project>(`/projects/${id}`),
    enabled,
    refetchInterval: (query) => (isActive(query.state.data?.last_deployment) ? 2000 : false),
  });
}

export function useProjectState(id: number) {
  return useQuery({
    queryKey: projectKeys.state(id),
    queryFn: () => apiFetch<ProjectState>(`/projects/${id}/state`),
  });
}

export function useSaveProject(id?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectInput) => {
      const payload = {
        ...body,
        credential: body.credential ? body.credential : null,
      };
      return id
        ? apiFetch<Project>(`/projects/${id}`, { method: "PUT", body: payload })
        : apiFetch<Project>("/projects", { method: "POST", body: payload });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: projectKeys.all }),
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, down }: { id: number; down: boolean }) =>
      apiFetch<void>(`/projects/${id}?down=${down}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: projectKeys.all }),
  });
}

export function useDeploy(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ref: string | null) =>
      apiFetch<DeploymentSummary>(`/projects/${id}/deploy`, { method: "POST", body: { ref } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: projectKeys.all }),
  });
}

export function useDeployments(id: number, page: number, live: boolean) {
  return useQuery({
    queryKey: projectKeys.deployments(id, page),
    queryFn: () =>
      apiFetch<{ items: DeploymentSummary[]; total: number; page: number; page_size: number }>(
        `/projects/${id}/deployments?page=${page}&page_size=15`,
      ),
    placeholderData: keepPreviousData,
    refetchInterval: live ? 2000 : false,
  });
}

/** A deployment with its whole log; refreshed while it runs. */
export function useDeployment(id: number | null) {
  return useQuery({
    queryKey: projectKeys.deployment(id ?? 0),
    queryFn: () => apiFetch<DeploymentDetail>(`/deployments/${id}`),
    enabled: id !== null,
    refetchInterval: (query) => (isActive(query.state.data) ? 1500 : false),
  });
}
