import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { errorMessage } from "../api/client";
import {
  type ConnectionTestResult,
  useDeleteInstance,
  useInstance,
  useTestInstance,
} from "../api/instances";
import { PencilSimple, PlugsConnected, Trash } from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ConnectionResult } from "../components/ConnectionResult";
import { DatabaseSelector } from "../components/DatabaseSelector";
import { InstanceBackupSettingsPanel, InstanceBackups } from "../components/InstanceBackups";
import { InstanceStoragePolicyPanel } from "../components/InstanceStoragePolicyPanel";
import { ScheduleList } from "../components/ScheduleList";
import { formatDateTime } from "../i18n";
import { RouteLabel } from "../components/RouteLabel";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm">{children}</Text>
    </div>
  );
}

export function InstanceDetailPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const instanceId = Number(useParams().id);
  const instance = useInstance(instanceId);
  const remove = useDeleteInstance();
  const test = useTestInstance(instanceId);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  if (instance.isPending) return <Loader />;
  if (instance.isError) return <Alert color="red">{errorMessage(t, instance.error)}</Alert>;
  const data = instance.data;

  const onDelete = () =>
    remove.mutate(instanceId, {
      onSuccess: () => {
        notifications.show({ color: "green", message: t("instances.deleted") });
        navigate("/instances", { replace: true });
      },
      onError: (error) => {
        setConfirmOpen(false);
        notifications.show({ color: "red", message: errorMessage(t, error) });
      },
    });

  return (
    <Stack gap="md">
      <PageHeader
        title={data.name}
        back={{ to: "/instances", label: t("nav.instances") }}
        badge={
          data.last_test_at ? (
            <Badge color={data.last_test_ok ? "green" : "red"} variant="light">
              {data.last_test_ok ? t("instances.testOk") : t("instances.testFailed")}
            </Badge>
          ) : undefined
        }
        actions={
          <>
            <Button
              variant="default"
              component={Link}
              to={`/instances/${instanceId}/edit`}
              leftSection={<PencilSimple size={15} />}
            >
              {t("common.edit")}
            </Button>
            <Button
              color="red"
              onClick={() => setConfirmOpen(true)}
              leftSection={<Trash size={15} />}
            >
              {t("common.delete")}
            </Button>
          </>
        }
      />

      <Paper withBorder p="lg">
        <Title order={4} mb="sm">
          {t("instances.details")}
        </Title>
        <SimpleGrid cols={{ base: 1, sm: 2, md: 5 }}>
          <Field label={t("instances.columns.address")}>
            <code dir="ltr">
              {data.host}:{data.port}
            </code>
          </Field>
          <Field label={t("instances.fields.username")}>
            <code dir="ltr">{data.username}</code>
          </Field>
          <Field label={t("instances.fields.route")}>
            <RouteLabel serverId={data.server_id} />
          </Field>
          <Field label={t("instances.columns.server")}>
            {data.server_type ? (
              <span dir="ltr">
                {t(`connection.serverType.${data.server_type}`)} {data.server_version}
              </span>
            ) : (
              t("common.notAvailable")
            )}
          </Field>
          <Field label={t("instances.columns.lastTest")}>
            {data.last_test_at
              ? `${
                  data.last_test_ok
                    ? t("instances.testOk")
                    : t(`errors.${data.last_test_error_code ?? "server_error"}`)
                } · ${formatDateTime(data.last_test_at, i18n.language)}`
              : t("instances.notTested")}
          </Field>
        </SimpleGrid>
        <Text size="xs" c="dimmed" mt="md">
          {t("instances.fields.notes")}
        </Text>
        <Text size="sm" style={{ whiteSpace: "pre-wrap" }} c={data.notes ? undefined : "dimmed"}>
          {data.notes || t("instances.noNotes")}
        </Text>
      </Paper>

      <Paper withBorder p="lg">
        <Group justify="space-between" mb="sm">
          <Title order={4}>{t("connection.title")}</Title>
          <Button
            leftSection={<PlugsConnected size={16} />}
            loading={test.isPending}
            onClick={() =>
              test.mutate(undefined, {
                onSuccess: setTestResult,
                onError: (error) =>
                  notifications.show({ color: "red", message: errorMessage(t, error) }),
              })
            }
          >
            {t("connection.test")}
          </Button>
        </Group>
        {testResult && <ConnectionResult result={testResult} />}
      </Paper>

      <Paper withBorder p="lg">
        <Title order={4} mb="sm">
          {t("databases.title")}
        </Title>
        <DatabaseSelector instanceId={instanceId} />
      </Paper>

      <InstanceBackups instanceId={instanceId} />

      <Paper withBorder p="lg">
        <Title order={4} mb="sm">
          {t("schedules.instanceTitle")}
        </Title>
        <ScheduleList instanceId={instanceId} />
      </Paper>

      <InstanceBackupSettingsPanel instanceId={instanceId} />

      <InstanceStoragePolicyPanel instanceId={instanceId} />

      <ConfirmDialog
        opened={confirmOpen}
        title={t("instances.deleteTitle")}
        body={t("instances.deleteConfirm", { name: data.name })}
        confirmLabel={t("common.delete")}
        loading={remove.isPending}
        onConfirm={onDelete}
        onCancel={() => setConfirmOpen(false)}
      />
    </Stack>
  );
}
