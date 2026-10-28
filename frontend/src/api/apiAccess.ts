import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";

/** The external API (/api/v1): keys, settings, request log and webhooks. */

export const API_BASE = "/api/v1";

export interface ApiSettings {
  enabled: boolean;
  cors_origins: string[];
  log_retention_days: number;
}

export interface ApiArea {
  area: string;
  read: number;
  write: number;
}

export interface ApiCatalog {
  base_path: string;
  areas: ApiArea[];
  scopes: string[];
  events: string[];
}

export interface ApiKey {
  id: number;
  name: string;
  prefix: string;
  scopes: string[];
  allowed_ips: string[];
  rate_limit: number;
  enabled: boolean;
  expires_at: string | null;
  expired: boolean;
  created_at: string;
  rotated_at: string | null;
  last_used_at: string | null;
  last_used_ip: string | null;
  request_count: number;
  requests_24h: number;
  errors_24h: number;
}

export interface ApiKeyFields {
  name: string;
  scopes: string[];
  allowed_ips: string[];
  rate_limit: number;
  expires_at: string | null;
}

export interface ApiKeySecret {
  key: ApiKey;
  secret: string;
}

export interface ApiRequest {
  id: number;
  key_id: number;
  key_name: string;
  created_at: string;
  method: string;
  path: string;
  status: number;
  ip: string;
  duration_ms: number;
  error: string | null;
}

export interface ApiRequestPage {
  items: ApiRequest[];
  next_before: number | null;
}

export interface Webhook {
  id: number;
  name: string;
  url: string;
  events: string[];
  enabled: boolean;
  created_at: string;
  last_delivery_at: string | null;
  last_status: string | null;
  failures: number;
}

export interface WebhookFields {
  name: string;
  url: string;
  events: string[];
  enabled: boolean;
}

export interface WebhookSecret {
  webhook: Webhook;
  secret: string;
}

export interface WebhookDelivery {
  id: number;
  webhook_id: number;
  uuid: string;
  created_at: string;
  event: string;
  payload: Record<string, unknown>;
  status: "pending" | "sent" | "failed";
  attempts: number;
  response_status: number | null;
  detail: string | null;
  duration_ms: number | null;
  finished_at: string | null;
}

/** The OpenAPI document, for the reference in the panel. */
export interface OpenApiOperation {
  summary?: string;
  description?: string;
  tags?: string[];
  operationId?: string;
  "x-required-scope"?: string;
}

export interface OpenApiDocument {
  info: { title: string; version: string };
  paths: Record<string, Record<string, OpenApiOperation>>;
  tags?: { name: string; description: string }[];
}

export const apiAccessKeys = {
  all: ["api-access"] as const,
  settings: ["api-access", "settings"] as const,
  catalog: ["api-access", "catalog"] as const,
  keys: ["api-access", "keys"] as const,
  requests: (keyId: number | null, errors: boolean) =>
    ["api-access", "requests", keyId, errors] as const,
  webhooks: ["api-access", "webhooks"] as const,
  deliveries: (id: number) => ["api-access", "webhooks", id, "deliveries"] as const,
  spec: ["api-access", "openapi"] as const,
};

export function useApiSettings() {
  return useQuery({
    queryKey: apiAccessKeys.settings,
    queryFn: () => apiFetch<ApiSettings>("/api-access/settings"),
  });
}

export function useSaveApiSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ApiSettings) =>
      apiFetch<ApiSettings>("/api-access/settings", { method: "PUT", body }),
    onSuccess: (data) => queryClient.setQueryData(apiAccessKeys.settings, data),
  });
}

export function useApiCatalog() {
  return useQuery({
    queryKey: apiAccessKeys.catalog,
    queryFn: () => apiFetch<ApiCatalog>("/api-access/catalog"),
    staleTime: Infinity,
  });
}

export function useApiKeys() {
  return useQuery({
    queryKey: apiAccessKeys.keys,
    queryFn: () => apiFetch<ApiKey[]>("/api-access/keys"),
  });
}

export function useKeyMutations() {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: apiAccessKeys.all });
  return {
    create: useMutation({
      mutationFn: (body: ApiKeyFields & { password: string }) =>
        apiFetch<ApiKeySecret>("/api-access/keys", { method: "POST", body }),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: Partial<ApiKeyFields> & { id: number; enabled?: boolean }) =>
        apiFetch<ApiKey>(`/api-access/keys/${id}`, { method: "PATCH", body }),
      onSuccess: refresh,
    }),
    rotate: useMutation({
      mutationFn: ({ id, password }: { id: number; password: string }) =>
        apiFetch<ApiKeySecret>(`/api-access/keys/${id}/rotate`, {
          method: "POST",
          body: { password },
        }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: number) => apiFetch<void>(`/api-access/keys/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

export async function fetchRequests(
  keyId: number | null,
  errors: boolean,
  before: number | null,
): Promise<ApiRequestPage> {
  const params = new URLSearchParams({ limit: "50" });
  if (keyId !== null) params.set("key_id", String(keyId));
  if (errors) params.set("errors", "true");
  if (before !== null) params.set("before", String(before));
  return apiFetch<ApiRequestPage>(`/api-access/requests?${params}`);
}

export function useWebhooks() {
  return useQuery({
    queryKey: apiAccessKeys.webhooks,
    queryFn: () => apiFetch<Webhook[]>("/webhooks"),
  });
}

export function useWebhookDeliveries(id: number | null) {
  return useQuery({
    queryKey: apiAccessKeys.deliveries(id ?? 0),
    queryFn: () => apiFetch<WebhookDelivery[]>(`/webhooks/${id}/deliveries?limit=100`),
    enabled: id !== null,
  });
}

export function useWebhookMutations() {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: apiAccessKeys.webhooks });
  return {
    create: useMutation({
      mutationFn: (body: WebhookFields) =>
        apiFetch<WebhookSecret>("/webhooks", { method: "POST", body }),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: Partial<WebhookFields> & { id: number }) =>
        apiFetch<Webhook>(`/webhooks/${id}`, { method: "PATCH", body }),
      onSuccess: refresh,
    }),
    rotate: useMutation({
      mutationFn: (id: number) =>
        apiFetch<WebhookSecret>(`/webhooks/${id}/rotate-secret`, { method: "POST" }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: number) => apiFetch<void>(`/webhooks/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
    test: useMutation({
      mutationFn: (id: number) =>
        apiFetch<WebhookDelivery>(`/webhooks/${id}/test`, { method: "POST" }),
      onSuccess: refresh,
    }),
    redeliver: useMutation({
      mutationFn: (deliveryId: number) =>
        apiFetch<WebhookDelivery>(`/webhooks/deliveries/${deliveryId}/redeliver`, {
          method: "POST",
        }),
      onSuccess: refresh,
    }),
  };
}

export function useOpenApi() {
  return useQuery({
    queryKey: apiAccessKeys.spec,
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/openapi.json`);
      if (!response.ok) throw new Error(String(response.status));
      return (await response.json()) as OpenApiDocument;
    },
    staleTime: Infinity,
  });
}

/** The scopes of one area: none, read, or write (download is separate). */
export type Level = "none" | "read" | "write";

export function levelOf(scopes: string[], area: string): Level {
  if (scopes.includes("*") || scopes.includes(`${area}:write`)) return "write";
  if (scopes.includes(`${area}:read`)) return "read";
  return "none";
}

export function withLevel(scopes: string[], area: string, level: Level): string[] {
  const rest = scopes.filter((s) => s !== `${area}:read` && s !== `${area}:write` && s !== "*");
  return level === "none" ? rest : [...rest, `${area}:${level}`];
}
