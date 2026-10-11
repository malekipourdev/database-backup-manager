import {
  Alert,
  Anchor,
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
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ConnectionResult } from "../components/ConnectionResult";
import { DatabaseSelector } from "../components/DatabaseSelector";
import { InstanceBackupSettingsPanel, InstanceBackups } from "../components/InstanceBackups";
import { formatDateTime } from "../i18n";

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
      <Group justify="space-between" wrap="wrap">
        <Stack gap={0}>
          <Anchor component={Link} to="/instances" size="sm">
            {t("nav.instances")}
          </Anchor>
          <Title order={2}>{data.name}</Title>
        </Stack>
        <Group gap="xs">
          <Button variant="default" component={Link} to={`/instances/${instanceId}/edit`}>
            {t("common.edit")}
          </Button>
          <Button color="red" variant="light" onClick={() => setConfirmOpen(true)}>
            {t("common.delete")}
          </Button>
        </Group>
      </Group>

      <Paper withBorder p="lg" radius="md">
        <Title order={4} mb="sm">
          {t("instances.details")}
        </Title>
        <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
          <Field label={t("instances.columns.address")}>
            <span dir="ltr">
              {data.host}:{data.port}
            </span>
          </Field>
          <Field label={t("instances.fields.username")}>
            <span dir="ltr">{data.username}</span>
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

      <Paper withBorder p="lg" radius="md">
        <Group justify="space-between" mb="sm">
          <Title order={4}>{t("connection.title")}</Title>
          <Button
            variant="light"
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

      <Paper withBorder p="lg" radius="md">
        <Title order={4} mb="sm">
          {t("databases.title")}
        </Title>
        <DatabaseSelector instanceId={instanceId} />
      </Paper>

      <InstanceBackups instanceId={instanceId} />

      <InstanceBackupSettingsPanel instanceId={instanceId} />

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
