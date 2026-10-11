import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";

export type ScheduleScope = "all" | "single";

export interface Schedule {
  id: number;
  instance_id: number;
  instance_name: string;
  name: string;
  cron: string;
  timezone: string;
  scope: ScheduleScope;
  database: string | null;
  enabled: boolean;
  next_run_at: string | null;
  last_fired_at: string | null;
  last_result: string | null;
  last_detail: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleInput {
  name: string;
  cron: string;
  timezone: string;
  scope: ScheduleScope;
  database: string | null;
  enabled: boolean;
}

export const scheduleKeys = {
  all: ["schedules"] as const,
  list: (instanceId?: number) => ["schedules", "list", instanceId ?? "all"] as const,
};

export function useSchedules(instanceId?: number) {
  return useQuery({
    queryKey: scheduleKeys.list(instanceId),
    queryFn: () =>
      apiFetch<Schedule[]>(
        instanceId === undefined ? "/schedules" : `/instances/${instanceId}/schedules`,
      ),
  });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: scheduleKeys.all });
}

export function useCreateSchedule() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ instanceId, body }: { instanceId: number; body: ScheduleInput }) =>
      apiFetch<Schedule>(`/instances/${instanceId}/schedules`, { method: "POST", body }),
    onSuccess: invalidate,
  });
}

export function useUpdateSchedule() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: ScheduleInput }) =>
      apiFetch<Schedule>(`/schedules/${id}`, { method: "PUT", body }),
    onSuccess: invalidate,
  });
}

export function useDeleteSchedule() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/schedules/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useRunSchedule() {
  const invalidate = useInvalidate();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<Schedule>(`/schedules/${id}/run`, { method: "POST" }),
    onSuccess: () => {
      invalidate();
      void queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
  });
}

export function previewSchedule(cron: string, timezone: string): Promise<{ next_runs: string[] }> {
  return apiFetch<{ next_runs: string[] }>("/schedules/preview", {
    method: "POST",
    body: { cron, timezone },
  });
}

export function toInput(schedule: Schedule): ScheduleInput {
  return {
    name: schedule.name,
    cron: schedule.cron,
    timezone: schedule.timezone,
    scope: schedule.scope,
    database: schedule.database,
    enabled: schedule.enabled,
  };
}
