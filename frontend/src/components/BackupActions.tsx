import { Button, Group, Select, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type StartBackupResponse, useStartBackup } from "../api/backups";
import { errorMessage } from "../api/client";
import { useDatabases } from "../api/instances";
import { formatNumber } from "../i18n";

interface BackupActionsProps {
  instanceId: number;
  /** Databases that currently have a queued or running backup. */
  activeDatabases: Set<string>;
}

export function BackupActions({ instanceId, activeDatabases }: BackupActionsProps) {
  const { t, i18n } = useTranslation();
  const databases = useDatabases(instanceId);
  const start = useStartBackup(instanceId);
  const [database, setDatabase] = useState<string | null>(null);

  const entries = databases.data?.databases ?? [];
  const markedCount = entries.filter((d) => d.selected).length;
  const options = entries.filter((d) => d.selectable && !d.missing).map((d) => d.name);

  const report = (result: StartBackupResponse) => {
    if (result.created.length > 0) {
      notifications.show({
        color: "green",
        message: t("backups.started", {
          formattedCount: formatNumber(result.created.length, i18n.language),
        }),
      });
    }
    for (const skipped of result.skipped) {
      notifications.show({
        color: "orange",
        message: t("backups.skipped", { database: skipped.database }),
      });
    }
  };

  const onError = (error: unknown) =>
    notifications.show({ color: "red", message: errorMessage(t, error) });

  return (
    <Stack gap="sm">
      <Group align="flex-end" wrap="wrap">
        <Button
          disabled={markedCount === 0}
          loading={start.isPending && start.variables?.scope === "all"}
          onClick={() => start.mutate({ scope: "all" }, { onSuccess: report, onError })}
        >
          {t("backups.backUpAll")}
        </Button>
        <Select
          label={t("backups.pickDatabase")}
          placeholder={t("backups.pickDatabase")}
          data={options}
          value={database}
          onChange={setDatabase}
          searchable
          nothingFoundMessage={t("databases.noMatches")}
          style={{ flex: "1 1 220px" }}
        />
        <Button
          variant="light"
          disabled={!database || activeDatabases.has(database)}
          loading={start.isPending && start.variables?.scope === "single"}
          onClick={() =>
            database && start.mutate({ scope: "single", database }, { onSuccess: report, onError })
          }
        >
          {t("backups.backUpOne")}
        </Button>
      </Group>
      {databases.isSuccess && markedCount === 0 && (
        <Text size="xs" c="dimmed">
          {t("backups.nothingMarked")}
        </Text>
      )}
    </Stack>
  );
}
