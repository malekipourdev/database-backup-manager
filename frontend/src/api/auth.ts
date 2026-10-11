import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch, isApiError } from "./client";

export interface Me {
  username: string;
  two_factor_enabled?: boolean;
}

export interface LoginResponse {
  username: string;
  /** Password accepted; a second step with an authenticator code is needed. */
  two_factor_required?: boolean;
  challenge?: string | null;
}

export interface TwoFactorStatus {
  enabled: boolean;
  recovery_codes_left: number;
}

export interface TwoFactorSetup {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

export const ME_KEY = ["me"] as const;
export const TWO_FACTOR_KEY = ["two-factor"] as const;

export function login(username: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/auth/login", { method: "POST", body: { username, password } });
}

export function loginSecondFactor(challenge: string, code: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/auth/login/2fa", { method: "POST", body: { challenge, code } });
}

export function logout(): Promise<void> {
  return apiFetch<void>("/auth/logout", { method: "POST" });
}

/** Current admin, or null when not signed in. */
export async function fetchMe(): Promise<Me | null> {
  try {
    return await apiFetch<Me>("/auth/me");
  } catch (error) {
    if (isApiError(error, "not_authenticated")) return null;
    throw error;
  }
}

export function useMe() {
  return useQuery({ queryKey: ME_KEY, queryFn: fetchMe, retry: false, staleTime: 60_000 });
}

export function useTwoFactorStatus() {
  return useQuery({
    queryKey: TWO_FACTOR_KEY,
    queryFn: () => apiFetch<TwoFactorStatus>("/auth/2fa"),
  });
}

function useRefresh() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: TWO_FACTOR_KEY });
    void queryClient.invalidateQueries({ queryKey: ME_KEY });
  };
}

export function useStartTwoFactorSetup() {
  return useMutation({
    mutationFn: (password: string) =>
      apiFetch<TwoFactorSetup>("/auth/2fa/setup", { method: "POST", body: { password } }),
  });
}

export function useEnableTwoFactor() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (code: string) =>
      apiFetch<{ recovery_codes: string[] }>("/auth/2fa/enable", {
        method: "POST",
        body: { code },
      }),
    onSuccess: refresh,
  });
}

export function useDisableTwoFactor() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: { password: string; code: string }) =>
      apiFetch<void>("/auth/2fa/disable", { method: "POST", body }),
    onSuccess: refresh,
  });
}

export function useRegenerateRecoveryCodes() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: { password: string; code: string }) =>
      apiFetch<{ recovery_codes: string[] }>("/auth/2fa/recovery-codes", {
        method: "POST",
        body,
      }),
    onSuccess: refresh,
  });
}
