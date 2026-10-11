import { useQuery } from "@tanstack/react-query";

import { apiFetch, isApiError } from "./client";

export interface Me {
  username: string;
}

export const ME_KEY = ["me"] as const;

export function login(username: string, password: string): Promise<Me> {
  return apiFetch<Me>("/auth/login", { method: "POST", body: { username, password } });
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
