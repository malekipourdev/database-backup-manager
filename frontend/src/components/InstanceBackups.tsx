import {
  Anchor,
  Button,
  Code,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import {
  type BackupOverrides,
  isActive,
  useInstanceBackupSettings,
  useInstanceRuns,
  useSaveInstanceBackupSettings,
} from "../api/backups";
import { BackupActions } from "./BackupActions";
import { BackupSettingsForm } from "./BackupSettingsForm";
import { RunTable } from "./RunTable";

/** Backups section of the instance page: start backups and watch recent runs. */
export function InstanceBackups({ instanceId }: { instanceId: number }) {
  const { t } = useTranslation();
  const runs = useInstanceRuns(instanceId);
  const items = runs.data?.items ?? [];
  const active = new Set(items.filter(isActive).map((r) => r.database_name));

  return (
    <Paper withBorder p="lg">
      <Group justify="space-between" mb="sm">
        <Title order={4}>{t("backups.title")}</Title>
        <Anchor component={Link} to={`/backups?instance_id=${instanceId}`} size="sm">
          {t("backups.viewAll")}
        </Anchor>
      </Group>
      <BackupActions instanceId={instanceId} activeDatabases={active} />
      <Text fw={600} mt="lg" mb="xs">
        {t("backups.recent")}
      </Text>
      {runs.isPending ? (
        <Loader size="sm" />
      ) : items.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t("backups.noRuns")}
        </Text>
      ) : (
        <RunTable runs={items} />
      )}
    </Paper>
  );
}

/** Effective backup settings of an instance, with per-field overrides. */
export function InstanceBackupSettingsPanel({ instanceId }: { instanceId: number }) {
  const { t } = useTranslation();
  const settings = useInstanceBackupSettings(instanceId);
  const save = useSaveInstanceBackupSettings(instanceId);
  const [editing, setEditing] = useState(false);

  if (!settings.data) return null;
  const { overrides, effective } = settings.data;
  const inherited = {
    storage_dir: effective.storage_dir,
    name_pattern: effective.name_pattern,
    compression: effective.compression,
  };

  return (
    <Paper withBorder p="lg">
      <Group justify="space-between" mb="sm">
        <Title order={4}>{t("settings.instanceTitle")}</Title>
        <Button size="xs" variant="default" onClick={() => setEditing((v) => !v)}>
          {editing ? t("common.cancel") : t("settings.edit")}
        </Button>
      </Group>
      {editing ? (
        <BackupSettingsForm
          mode="instance"
          initial={effective}
          inherited={inherited}
          initialOverridden={{
            storage_dir: overrides.storage_dir !== null,
            name_pattern: overrides.name_pattern !== null,
            compression: overrides.compression !== null,
          }}
          saving={save.isPending}
          error={save.error}
          onSave={(value) =>
            save.mutate(value as BackupOverrides, {
              onSuccess: () => {
                notifications.show({ color: "green", message: t("settings.saved") });
                setEditing(false);
              },
            })
          }
        />
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              {t("settings.storageDir")}
            </Text>
            <Code dir="ltr">{effective.storage_dir || t("settings.root")}</Code>
          </Stack>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              {t("settings.namePattern")}
            </Text>
            <Code dir="ltr">{effective.name_pattern}</Code>
          </Stack>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              {t("settings.compression")}
            </Text>
            <Text size="sm">{t(`backups.compression.${effective.compression}`)}</Text>
          </Stack>
        </SimpleGrid>
      )}
    </Paper>
  );
}
