import {
  Alert,
  Button,
  Group,
  List,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, errorMessage } from "../api/client";
import { type ScheduleInput, previewSchedule } from "../api/schedules";
import { formatDateTime } from "../i18n";

export const CRON_PRESETS = [
  { key: "hourly", cron: "0 * * * *" },
  { key: "daily", cron: "0 2 * * *" },
  { key: "weekly", cron: "0 2 * * 6" },
  { key: "monthly", cron: "0 2 1 * *" },
] as const;

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function timezoneOptions(current: string): string[] {
  let all: string[] = [];
  try {
    all =
      (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.(
        "timeZone",
      ) ?? [];
  } catch {
    all = [];
  }
  const first = ["UTC", "Asia/Tehran", browserTimezone(), current];
  return [...new Set([...first, ...all])];
}

export const EMPTY_SCHEDULE: ScheduleInput = {
  name: "",
  cron: "0 2 * * *",
  timezone: "UTC",
  scope: "all",
  database: null,
  enabled: true,
};

interface ScheduleFormProps {
  initial: ScheduleInput;
  saving: boolean;
  error: unknown;
  /** Rendered above the fields, e.g. an instance picker on the global schedules page. */
  header?: React.ReactNode;
  onSave: (value: ScheduleInput) => void;
  onCancel: () => void;
}

export function ScheduleForm(props: ScheduleFormProps) {
  const { t, i18n } = useTranslation();
  const [values, setValues] = useState<ScheduleInput>(props.initial);
  const [nextRuns, setNextRuns] = useState<string[] | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [debounced] = useDebouncedValue({ cron: values.cron, timezone: values.timezone }, 300);
  const zones = useMemo(() => timezoneOptions(props.initial.timezone), [props.initial.timezone]);

  useEffect(() => {
    let cancelled = false;
    previewSchedule(debounced.cron, debounced.timezone)
      .then((result) => {
        if (cancelled) return;
        setNextRuns(result.next_runs);
        setPreviewError(null);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setNextRuns(null);
        setPreviewError(fieldMessage(error) ?? errorMessage(t, error));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced.cron, debounced.timezone]);

  function fieldMessage(error: unknown, field?: string): string | null {
    if (!(error instanceof ApiError) || !error.fields) return null;
    const entries = Object.entries(error.fields).filter(([key]) => !field || key === field);
    if (entries.length === 0) return null;
    return entries
      .map(([, code]) =>
        t(`schedules.validation.${code}`, { defaultValue: t("validation.invalid") }),
      )
      .join(" ");
  }

  const set = <K extends keyof ScheduleInput>(key: K, value: ScheduleInput[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));
  const preset = CRON_PRESETS.find((p) => p.cron === values.cron)?.key ?? "custom";

  return (
    <Stack gap="md">
      {props.header}
      <TextInput
        label={t("schedules.fields.name")}
        placeholder={t("schedules.namePlaceholder")}
        value={values.name}
        onChange={(e) => set("name", e.currentTarget.value)}
        error={fieldMessage(props.error, "name")}
        required
      />

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          {t("schedules.fields.frequency")}
        </Text>
        <SegmentedControl
          value={preset}
          onChange={(key) => {
            const found = CRON_PRESETS.find((p) => p.key === key);
            if (found) set("cron", found.cron);
          }}
          data={[
            ...CRON_PRESETS.map((p) => ({ value: p.key, label: t(`schedules.presets.${p.key}`) })),
            { value: "custom", label: t("schedules.presets.custom") },
          ]}
        />
      </Stack>

      <Group grow align="flex-start">
        <TextInput
          label={t("schedules.fields.cron")}
          description={t("schedules.cronHelp")}
          dir="ltr"
          value={values.cron}
          onChange={(e) => set("cron", e.currentTarget.value)}
          error={fieldMessage(props.error, "cron")}
        />
        <Select
          label={t("schedules.fields.timezone")}
          searchable
          allowDeselect={false}
          data={zones}
          value={values.timezone}
          onChange={(value) => value && set("timezone", value)}
          error={fieldMessage(props.error, "timezone")}
        />
      </Group>

      <Stack gap={2}>
        <Text size="sm" fw={500}>
          {t("schedules.nextRuns")}
        </Text>
        {nextRuns && (
          <List size="sm" data-testid="schedule-preview">
            {nextRuns.map((iso) => (
              <List.Item key={iso}>{formatDateTime(iso, i18n.language)}</List.Item>
            ))}
          </List>
        )}
        {previewError && (
          <Text size="sm" c="red">
            {previewError}
          </Text>
        )}
      </Stack>

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          {t("schedules.fields.scope")}
        </Text>
        <SegmentedControl
          value={values.scope}
          onChange={(value) => set("scope", value as ScheduleInput["scope"])}
          data={[
            { value: "all", label: t("schedules.scope.all") },
            { value: "single", label: t("schedules.scope.single") },
          ]}
        />
      </Stack>
      {values.scope === "single" && (
        <TextInput
          label={t("schedules.fields.database")}
          dir="ltr"
          value={values.database ?? ""}
          onChange={(e) => set("database", e.currentTarget.value)}
          error={fieldMessage(props.error, "database")}
          required
        />
      )}

      <Switch
        label={t("schedules.fields.enabled")}
        checked={values.enabled}
        onChange={(e) => set("enabled", e.currentTarget.checked)}
      />

      {Boolean(props.error) && !fieldMessage(props.error) && (
        <Alert color="red">{errorMessage(t, props.error)}</Alert>
      )}

      <Group justify="flex-end">
        <Button variant="default" onClick={props.onCancel}>
          {t("common.cancel")}
        </Button>
        <Button
          loading={props.saving}
          onClick={() =>
            props.onSave({
              ...values,
              name: values.name.trim(),
              database: values.scope === "single" ? (values.database ?? "").trim() : null,
            })
          }
        >
          {t("common.save")}
        </Button>
      </Group>
    </Stack>
  );
}
