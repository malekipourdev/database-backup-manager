import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";

export type Platform = "bale" | "telegram";
export type NotifyLevel = "info" | "warning" | "error" | "off";
export const PLATFORMS: Platform[] = ["bale", "telegram"];

export interface BotSettings {
  platform: Platform;
  enabled: boolean;
  has_token: boolean;
  api_base_url: string;
  proxy_url: string;
  allow_file_download: boolean;
  max_file_mb: number;
  bot_username: string | null;
  running: boolean;
  last_ok_at: string | null;
  last_error: string | null;
}

export interface BotSettingsInput {
  enabled: boolean;
  /** Empty keeps the stored token. */
  token: string;
  api_base_url: string;
  proxy_url: string;
  allow_file_download: boolean;
  max_file_mb: number;
}

export interface BotTestResult {
  ok: boolean;
  username: string | null;
  error_code: string | null;
  error_detail: string | null;
}

export interface BotAdmin {
  id: number;
  platform: Platform;
  user_id: number;
  display_name: string;
  enabled: boolean;
  notify_level: NotifyLevel;
  language: "fa" | "en";
  last_seen_at: string | null;
  created_at: string;
}

export interface LinkCode {
  code: string;
  expires_at: string;
  bot_username: string | null;
  deep_link: string | null;
}

export const botKeys = {
  settings: ["bots"] as const,
  admins: ["bot-admins"] as const,
};

export function useBots() {
  return useQuery({
    queryKey: botKeys.settings,
    queryFn: () => apiFetch<BotSettings[]>("/bots"),
    // Shows whether the bot is connected; cheap to refresh.
    refetchInterval: 15_000,
  });
}

export function useSaveBot(platform: Platform) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: BotSettingsInput) =>
      apiFetch<BotSettings>(`/bots/${platform}`, { method: "PUT", body }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: botKeys.settings }),
  });
}

export function useTestBot(platform: Platform) {
  return useMutation({
    mutationFn: (body: BotSettingsInput) =>
      apiFetch<BotTestResult>(`/bots/${platform}/test`, { method: "POST", body }),
  });
}

export function useBotAdmins() {
  return useQuery({
    queryKey: botKeys.admins,
    queryFn: () => apiFetch<BotAdmin[]>("/bot-admins"),
  });
}

export function useAddBotAdmin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { platform: Platform; user_id: number; display_name: string }) =>
      apiFetch<BotAdmin>("/bot-admins", { method: "POST", body }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: botKeys.admins }),
  });
}

export function useUpdateBotAdmin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<BotAdmin> }) =>
      apiFetch<BotAdmin>(`/bot-admins/${id}`, { method: "PATCH", body }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: botKeys.admins }),
  });
}

export function useDeleteBotAdmin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/bot-admins/${id}`, { method: "DELETE" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: botKeys.admins }),
  });
}

export function useCreateLinkCode(platform: Platform) {
  return useMutation({
    mutationFn: (display_name: string) =>
      apiFetch<LinkCode>(`/bots/${platform}/link-codes`, {
        method: "POST",
        body: { display_name },
      }),
  });
}
