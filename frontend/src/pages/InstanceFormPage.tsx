import {
  Alert,
  Button,
  Group,
  Loader,
  NumberInput,
  Paper,
  PasswordInput,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import type { TFunction } from "i18next";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import { ApiError, errorMessage } from "../api/client";
import {
  type ConnectionTestResult,
  type Instance,
  type InstanceUpdate,
  useCreateInstance,
  useInstance,
  useTestConnectionParams,
  useTestInstance,
  useUpdateInstance,
} from "../api/instances";
import { useServers } from "../api/servers";
import { PageHeader } from "../components/PageHeader";
import { ConnectionResult } from "../components/ConnectionResult";

const NOTES_MAX = 2000;
const HOST_RE = /^[A-Za-z0-9._:-]+$/;

interface FormValues {
  name: string;
  host: string;
  port: number | string;
  username: string;
  password: string;
  notes: string;
  /** "" for the panel itself, else a server id. */
  server: string;
}

function buildSchema(t: TFunction, requirePassword: boolean) {
  const required = t("validation.required");
  const tooLong = (max: number) => t("validation.tooLong", { max });
  return z.object({
    name: z.string().trim().min(1, required).max(100, tooLong(100)),
    host: z
      .string()
      .trim()
      .min(1, required)
      .max(255, tooLong(255))
      .regex(HOST_RE, t("validation.hostInvalid")),
    port: z.coerce
      .number({ invalid_type_error: t("validation.portRange") })
      .int(t("validation.portRange"))
      .min(1, t("validation.portRange"))
      .max(65535, t("validation.portRange")),
    username: z.string().min(1, required).max(255, tooLong(255)),
    password: requirePassword
      ? z.string().min(1, required).max(1024, tooLong(1024))
      : z.string().max(1024, tooLong(1024)),
    notes: z.string().max(NOTES_MAX, tooLong(NOTES_MAX)),
    server: z.string(),
  });
}

function toFormValues(instance?: Instance): FormValues {
  return {
    name: instance?.name ?? "",
    host: instance?.host ?? "",
    port: instance?.port ?? 3306,
    username: instance?.username ?? "",
    password: "",
    notes: instance?.notes ?? "",
    server: instance?.server_id ? String(instance.server_id) : "",
  };
}

export function InstanceFormPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const params = useParams();
  const instanceId = params.id ? Number(params.id) : undefined;
  const isEdit = instanceId !== undefined;

  const existing = useInstance(instanceId ?? 0, isEdit);
  const create = useCreateInstance();
  const update = useUpdateInstance(instanceId ?? 0);
  const testParams = useTestConnectionParams();
  const testSaved = useTestInstance(instanceId ?? 0);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [testMessage, setTestMessage] = useState<string | null>(null);
  const servers = useServers();
  const remoteServers = (servers.data ?? []).filter((s) => s.kind === "remote");

  const form = useForm<FormValues>({
    initialValues: toFormValues(),
    validate: (values) => {
      const result = buildSchema(t, !isEdit).safeParse(values);
      if (result.success) return {};
      const errors: Record<string, string> = {};
      for (const issue of result.error.issues) {
        const key = String(issue.path[0]);
        errors[key] ??= issue.message;
      }
      return errors;
    },
  });

  // Load the instance into the form once when editing.
  const loaded = existing.data;
  useEffect(() => {
    if (loaded) {
      form.setValues(toFormValues(loaded));
      form.resetDirty(toFormValues(loaded));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded?.id]);

  const applyServerErrors = (error: unknown) => {
    if (!(error instanceof ApiError)) return;
    if (error.code === "name_taken") {
      form.setFieldError("name", t("errors.name_taken"));
      return;
    }
    if (error.fields) {
      for (const field of Object.keys(error.fields)) {
        if (field in form.values) form.setFieldError(field, t("validation.invalid"));
      }
    }
  };

  const onSubmit = (values: FormValues) => {
    const body = {
      name: values.name.trim(),
      host: values.host.trim(),
      port: Number(values.port),
      username: values.username,
      notes: values.notes,
      server_id: values.server ? Number(values.server) : null,
    };
    if (isEdit) {
      const patch: InstanceUpdate = { ...body };
      // An empty password keeps the stored one, so it is not sent at all.
      if (values.password) patch.password = values.password;
      update.mutate(patch, {
        onSuccess: (instance) => {
          notifications.show({ color: "green", message: t("instances.updated") });
          navigate(`/instances/${instance.id}`);
        },
        onError: applyServerErrors,
      });
    } else {
      create.mutate(
        { ...body, password: values.password },
        {
          onSuccess: (instance) => {
            notifications.show({ color: "green", message: t("instances.created") });
            navigate(`/instances/${instance.id}`);
          },
          onError: applyServerErrors,
        },
      );
    }
  };

  const onTest = () => {
    setTestResult(null);
    setTestMessage(null);
    const checked = form.validate();
    const connectionFields = ["host", "port", "username", "password"];
    if (connectionFields.some((f) => checked.errors[f])) return;

    const values = form.values;
    const handlers = {
      onSuccess: (result: ConnectionTestResult) => setTestResult(result),
      onError: (error: unknown) => setTestMessage(errorMessage(t, error)),
    };

    if (isEdit && !values.password) {
      // Without a new password, only the saved connection settings can be tested.
      const unchanged =
        loaded !== undefined &&
        values.host.trim() === loaded.host &&
        Number(values.port) === loaded.port &&
        values.username === loaded.username &&
        (values.server ? Number(values.server) : null) === loaded.server_id;
      if (!unchanged) {
        form.setFieldError("password", t("connection.passwordNeeded"));
        return;
      }
      testSaved.mutate(undefined, handlers);
      return;
    }
    testParams.mutate(
      {
        host: values.host.trim(),
        port: Number(values.port),
        username: values.username,
        password: values.password,
        server_id: values.server ? Number(values.server) : null,
      },
      handlers,
    );
  };

  if (isEdit && existing.isPending) return <Loader />;
  if (isEdit && existing.isError) {
    return <Alert color="red">{errorMessage(t, existing.error)}</Alert>;
  }

  const saving = create.isPending || update.isPending;
  const testing = testParams.isPending || testSaved.isPending;
  const saveError = create.error ?? update.error;

  return (
    <Stack gap="md">
      <PageHeader
        title={
          isEdit ? t("instances.editTitle", { name: loaded?.name }) : t("instances.createTitle")
        }
        back={{
          to: isEdit ? `/instances/${instanceId}` : "/instances",
          label: isEdit ? (loaded?.name ?? t("common.back")) : t("nav.instances"),
        }}
      />

      <Paper withBorder p="lg">
        <form onSubmit={form.onSubmit(onSubmit)} noValidate>
          <Stack gap="md">
            {saveError && !(saveError instanceof ApiError && saveError.code === "name_taken") && (
              <Alert color="red">{errorMessage(t, saveError)}</Alert>
            )}
            <TextInput
              label={t("instances.fields.name")}
              required
              maxLength={100}
              {...form.getInputProps("name")}
            />
            {remoteServers.length > 0 && (
              <Select
                label={t("instances.fields.route")}
                description={t("instances.routeHint")}
                allowDeselect={false}
                data={[
                  { value: "", label: t("instances.routeDirect") },
                  ...remoteServers.map((s) => ({
                    value: String(s.id),
                    label: s.paired
                      ? t("instances.routeServer", { name: s.name })
                      : `${t("instances.routeServer", { name: s.name })} (${t("servers.notConnected")})`,
                  })),
                ]}
                {...form.getInputProps("server")}
              />
            )}
            <Group grow align="flex-start">
              <TextInput
                label={t("instances.fields.host")}
                required
                dir="ltr"
                description={
                  form.values.server ? t("instances.hostHintServer") : t("instances.hostHint")
                }
                {...form.getInputProps("host")}
              />
              <NumberInput
                label={t("instances.fields.port")}
                required
                dir="ltr"
                min={1}
                max={65535}
                clampBehavior="none"
                allowDecimal={false}
                allowNegative={false}
                hideControls
                maw={140}
                {...form.getInputProps("port")}
              />
            </Group>
            <TextInput
              label={t("instances.fields.username")}
              required
              dir="ltr"
              autoComplete="off"
              {...form.getInputProps("username")}
            />
            <PasswordInput
              label={t("instances.fields.password")}
              required={!isEdit}
              dir="ltr"
              autoComplete="new-password"
              description={isEdit ? t("instances.passwordStored") : undefined}
              {...form.getInputProps("password")}
            />
            <Textarea
              label={t("instances.fields.notes")}
              autosize
              minRows={3}
              maxRows={10}
              {...form.getInputProps("notes")}
              description={t("instances.notesCount", {
                count: form.values.notes.length,
                max: NOTES_MAX,
              })}
            />

            {testResult && <ConnectionResult result={testResult} />}
            {testMessage && <Alert color="red">{testMessage}</Alert>}

            <Group justify="space-between">
              <Button variant="light" onClick={onTest} loading={testing} disabled={saving}>
                {t("connection.test")}
              </Button>
              <Group gap="xs">
                <Button
                  variant="default"
                  component={Link}
                  to={isEdit ? `/instances/${instanceId}` : "/instances"}
                >
                  {t("common.cancel")}
                </Button>
                <Button type="submit" loading={saving}>
                  {t("common.save")}
                </Button>
              </Group>
            </Group>
            {testing && (
              <Text size="xs" c="dimmed">
                {t("common.loading")}
              </Text>
            )}
          </Stack>
        </form>
      </Paper>
    </Stack>
  );
}
