import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { errorMessage } from "../api/client";
import { type Instance, useInstances } from "../api/instances";
import { formatDateTime } from "../i18n";

function ServerCell({ instance }: { instance: Instance }) {
  const { t } = useTranslation();
  if (!instance.server_type) return <Text c="dimmed">{t("common.notAvailable")}</Text>;
  return (
    <span dir="ltr">
      {t(`connection.serverType.${instance.server_type}`)} {instance.server_version}
    </span>
  );
}

function LastTestCell({ instance }: { instance: Instance }) {
  const { t, i18n } = useTranslation();
  if (!instance.last_test_at) return <Text c="dimmed">{t("instances.notTested")}</Text>;
  return (
    <Group gap={6} wrap="nowrap">
      <Badge color={instance.last_test_ok ? "green" : "red"} variant="light">
        {instance.last_test_ok
          ? t("instances.testOk")
          : t(`errors.${instance.last_test_error_code ?? "server_error"}`)}
      </Badge>
      <Text size="xs" c="dimmed">
        {formatDateTime(instance.last_test_at, i18n.language)}
      </Text>
    </Group>
  );
}

export function InstancesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const instances = useInstances();

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>{t("instances.title")}</Title>
        <Button component={Link} to="/instances/new">
          {t("instances.add")}
        </Button>
      </Group>

      {instances.isPending && <Loader />}
      {instances.isError && <Alert color="red">{errorMessage(t, instances.error)}</Alert>}

      {instances.data && instances.data.length === 0 && (
        <Paper withBorder p="xl" radius="md">
          <Stack align="center" gap="xs">
            <Text fw={600}>{t("instances.empty")}</Text>
            <Text c="dimmed" size="sm" ta="center">
              {t("instances.emptyHint")}
            </Text>
          </Stack>
        </Paper>
      )}

      {instances.data && instances.data.length > 0 && (
        <Paper withBorder radius="md">
          <Table.ScrollContainer minWidth={720}>
            <Table highlightOnHover verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("instances.columns.name")}</Table.Th>
                  <Table.Th>{t("instances.columns.address")}</Table.Th>
                  <Table.Th>{t("instances.columns.username")}</Table.Th>
                  <Table.Th>{t("instances.columns.server")}</Table.Th>
                  <Table.Th>{t("instances.columns.lastTest")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {instances.data.map((instance) => (
                  <Table.Tr
                    key={instance.id}
                    style={{ cursor: "pointer" }}
                    onClick={() => navigate(`/instances/${instance.id}`)}
                  >
                    <Table.Td>
                      <Link
                        to={`/instances/${instance.id}`}
                        onClick={(e) => e.stopPropagation()}
                        style={{ color: "inherit", fontWeight: 600 }}
                      >
                        {instance.name}
                      </Link>
                    </Table.Td>
                    <Table.Td>
                      <span dir="ltr">
                        {instance.host}:{instance.port}
                      </span>
                    </Table.Td>
                    <Table.Td>
                      <span dir="ltr">{instance.username}</span>
                    </Table.Td>
                    <Table.Td>
                      <ServerCell instance={instance} />
                    </Table.Td>
                    <Table.Td>
                      <LastTestCell instance={instance} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
    </Stack>
  );
}
