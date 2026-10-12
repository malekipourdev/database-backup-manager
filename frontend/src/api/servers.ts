import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";

export interface Server {
  id: number;
  name: string;
  kind: "local" | "remote";
  host: string | null;
  port: number | null;
  notes: string;
  paired: boolean;
  cert_fingerprint: string | null;
  paired_at: string | null;
  last_seen_at: string | null;
  last_error: string | null;
  agent_hostname: string | null;
  docker_version: string | null;
  projects: number;
  instances: number;
  created_at: string;
}

export interface ServerInput {
  name: string;
  host: string;
  port: number;
  notes: string;
}

/** Shown once: the agent's token and the commands that install it. */
export interface ServerSetup {
  server: Server;
  token: string;
  install_command: string;
}

export const serverKeys = {
  all: ["servers"] as const,
};

export function useServers() {
  return useQuery({
    queryKey: serverKeys.all,
    queryFn: () => apiFetch<Server[]>("/servers"),
  });
}

/** Servers whose agent the panel can use (the local one, and connected others). */
export function usableServers(servers: Server[] | undefined): Server[] {
  return (servers ?? []).filter((s) => s.paired);
}

function useServerMutation<T, V>(fn: (vars: V) => Promise<T>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => queryClient.invalidateQueries({ queryKey: serverKeys.all }),
  });
}

export function useCreateServer() {
  return useServerMutation((body: ServerInput) =>
    apiFetch<ServerSetup>("/servers", { method: "POST", body }),
  );
}

export function useUpdateServer() {
  return useServerMutation(({ id, ...body }: Partial<ServerInput> & { id: number }) =>
    apiFetch<Server>(`/servers/${id}`, { method: "PATCH", body }),
  );
}

export function useDeleteServer() {
  return useServerMutation((id: number) => apiFetch<void>(`/servers/${id}`, { method: "DELETE" }));
}

export function useConnectServer() {
  return useServerMutation((id: number) =>
    apiFetch<Server>(`/servers/${id}/connect`, { method: "POST" }),
  );
}

export function useRotateServerToken() {
  return useServerMutation((id: number) =>
    apiFetch<ServerSetup>(`/servers/${id}/token`, { method: "POST" }),
  );
}
