import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";

export type Severity = "info" | "warning" | "error";
export type Channel = "bale" | "telegram" | "webhook";
export const CHANNELS: Channel[] = ["bale", "telegram", "webhook"];

export interface NotificationRule {
  enabled: boolean;
  channels: Channel[];
}

export interface NotificationSettings {
  rules: Record<string, NotificationRule>;
  cooldown_minutes: number;
  stale_hours: number;
  disk_free_percent: number;
  daily_summary_time: string;
  timezone: string;
  webhook_enabled: boolean;
  webhook_url: string;
  has_webhook_secret: boolean;
  events: { name: string; severity: Severity }[];
}

export interface NotificationSettingsInput {
  rules: Record<string, NotificationRule>;
  cooldown_minutes: number;
  stale_hours: number;
  disk_free_percent: number;
  daily_summary_time: string;
  timezone: string;
  webhook_enabled: boolean;
  webhook_url: string;
  /** Empty keeps the stored secret. */
  webhook_secret: string;
  clear_webhook_secret: boolean;
}

export interface NotificationLogItem {
  id: number;
  created_at: string;
  event: string;
  severity: Severity;
  subject: string;
  params: Record<string, unknown>;
  run_id: number | null;
  channels: Record<string, string>;
  suppressed: boolean;
}

export interface NotificationLogPage {
  items: NotificationLogItem[];
  total: number;
  page: number;
  page_size: number;
}

export const notificationKeys = {
  settings: ["notifications", "settings"] as const,
  log: (page: number, severity: string | null) => ["notifications", "log", page, severity] as const,
};

export function useNotificationSettings() {
  return useQuery({
    queryKey: notificationKeys.settings,
    queryFn: () => apiFetch<NotificationSettings>("/notifications/settings"),
  });
}

export function useSaveNotificationSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: NotificationSettingsInput) =>
      apiFetch<NotificationSettings>("/notifications/settings", { method: "PUT", body }),
    onSuccess: (data) => queryClient.setQueryData(notificationKeys.settings, data),
  });
}

export function useTestNotification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (channels: Channel[]) =>
      apiFetch<{ results: Record<string, string> }>("/notifications/test", {
        method: "POST",
        body: { channels },
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications", "log"] }),
  });
}

export function useNotificationLog(page: number, severity: string | null) {
  const params = new URLSearchParams({ page: String(page), page_size: "25" });
  if (severity) params.set("severity", severity);
  return useQuery({
    queryKey: notificationKeys.log(page, severity),
    queryFn: () => apiFetch<NotificationLogPage>(`/notifications/log?${params}`),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
}
