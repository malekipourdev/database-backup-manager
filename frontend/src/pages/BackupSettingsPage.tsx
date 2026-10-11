import { Alert, Loader, Paper, Stack, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import { type BackupSettings, useBackupSettings, useSaveBackupSettings } from "../api/backups";
import { errorMessage } from "../api/client";
import { BackupSettingsForm } from "../components/BackupSettingsForm";

export function BackupSettingsPage() {
  const { t } = useTranslation();
  const settings = useBackupSettings();
  const save = useSaveBackupSettings();

  return (
    <Stack gap="md" maw={720}>
      <Title order={2}>{t("settings.title")}</Title>
      <Text c="dimmed" size="sm">
        {t("settings.globalHint")}
      </Text>
      {settings.isPending && <Loader />}
      {settings.isError && <Alert color="red">{errorMessage(t, settings.error)}</Alert>}
      {settings.data && (
        <Paper withBorder p="lg" radius="md">
          <BackupSettingsForm
            mode="global"
            initial={settings.data}
            saving={save.isPending}
            error={save.error}
            onSave={(value) =>
              save.mutate(value as BackupSettings, {
                onSuccess: () =>
                  notifications.show({ color: "green", message: t("settings.saved") }),
              })
            }
          />
        </Paper>
      )}
    </Stack>
  );
}
