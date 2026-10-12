import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useCurrentServer } from "../server/CurrentServer";
import { apiFetch } from "./client";

export type ServerType = "mysql" | "mariadb";
export type ConnectionErrorCode = string;

export interface Instance {
  id: number;
  name: string;
  host: string;
  port: number;
  username: string;
  notes: string;
  /** Another server whose agent reaches the database; null: the panel connects itself. */
  server_id: number | null;
  has_password: true;
  server_type: ServerType | null;
  server_version: string | null;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_error_code: ConnectionErrorCode | null;
  created_at: string;
  updated_at: string;
}

export interface InstanceCreate {
  name: string;
  host: string;
  port: number;
  username: string;
  password: string;
  notes: string;
  server_id: number | null;
}

export type InstanceUpdate = Partial<InstanceCreate>;

export interface ConnectionParams {
  host: string;
  port: number;
  username: string;
  password: string;
  server_id: number | null;
}

export interface ConnectionTestResult {
  ok: boolean;
  tested_at: string;
  server_type: ServerType | null;
  server_version: string | null;
  error_code: ConnectionErrorCode | null;
  error_detail: string | null;
}

export interface DatabaseEntry {
  name: string;
  is_system: boolean;
  selectable: boolean;
  selected: boolean;
  missing: boolean;
}

export interface DatabaseList {
  reachable: boolean;
  error_code: ConnectionErrorCode | null;
  error_detail: string | null;
  databases: DatabaseEntry[];
}

export const instanceKeys = {
  all: ["instances"] as const,
  detail: (id: number) => ["instances", id] as const,
  databases: (id: number) => ["instances", id, "databases"] as const,
};

/** The current server's databases, or every server's with `all`. */
export function useInstances({ all = false }: { all?: boolean } = {}) {
  const current = useCurrentServer().id;
  const server = all ? null : current;
  return useQuery({
    queryKey: [...instanceKeys.all, "list", server] as const,
    queryFn: () =>
      apiFetch<Instance[]>(server === null ? "/instances" : `/instances?server=${server}`),
  });
}

export function useInstance(id: number, enabled = true) {
  return useQuery({
    queryKey: instanceKeys.detail(id),
    queryFn: () => apiFetch<Instance>(`/instances/${id}`),
    enabled,
  });
}

export function useCreateInstance() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: InstanceCreate) =>
      apiFetch<Instance>("/instances", { method: "POST", body }),
    onSuccess: (instance) => {
      queryClient.setQueryData(instanceKeys.detail(instance.id), instance);
      void queryClient.invalidateQueries({ queryKey: instanceKeys.all, exact: true });
    },
  });
}

export function useUpdateInstance(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: InstanceUpdate) =>
      apiFetch<Instance>(`/instances/${id}`, { method: "PATCH", body }),
    onSuccess: (instance) => {
      queryClient.setQueryData(instanceKeys.detail(id), instance);
      void queryClient.invalidateQueries({ queryKey: instanceKeys.all, exact: true });
      void queryClient.invalidateQueries({ queryKey: instanceKeys.databases(id) });
    },
  });
}

export function useDeleteInstance() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/instances/${id}`, { method: "DELETE" }),
    onSuccess: (_data, id) => {
      queryClient.removeQueries({ queryKey: instanceKeys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: instanceKeys.all, exact: true });
    },
  });
}

export function testConnectionParams(body: ConnectionParams): Promise<ConnectionTestResult> {
  return apiFetch<ConnectionTestResult>("/instances/test-connection", { method: "POST", body });
}

export function useTestConnectionParams() {
  return useMutation({ mutationFn: testConnectionParams });
}

export function useTestInstance(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<ConnectionTestResult>(`/instances/${id}/test-connection`, { method: "POST" }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: instanceKeys.detail(id), exact: true });
      void queryClient.invalidateQueries({ queryKey: instanceKeys.all, exact: true });
    },
  });
}

export function useDatabases(id: number) {
  return useQuery({
    queryKey: instanceKeys.databases(id),
    queryFn: () => apiFetch<DatabaseList>(`/instances/${id}/databases`),
    retry: false,
    staleTime: 0,
  });
}

export function useSaveSelection(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (databases: string[]) =>
      apiFetch<DatabaseList>(`/instances/${id}/selection`, {
        method: "PUT",
        body: { databases },
      }),
    onSuccess: (list) => queryClient.setQueryData(instanceKeys.databases(id), list),
  });
}
