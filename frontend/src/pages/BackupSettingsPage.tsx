import { Alert, Loader, Paper, Stack, Tabs, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { type BackupSettings, useBackupSettings, useSaveBackupSettings } from "../api/backups";
import { errorMessage } from "../api/client";
import { BackupSettingsForm } from "../components/BackupSettingsForm";
import { Broom, CloudArrowUp, SlidersHorizontal } from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { RemoteStorageForm } from "../components/RemoteStorageForm";
import { RetentionSettings } from "../components/RetentionSettings";

export function BackupSettingsPage() {
  const { t } = useTranslation();
  const settings = useBackupSettings();
  const save = useSaveBackupSettings();
  const [params, setParams] = useSearchParams();
  const tab = ["backups", "remote", "retention"].includes(params.get("tab") ?? "")
    ? (params.get("tab") as string)
    : "backups";

  return (
    <Stack gap="md">
      <PageHeader
        help="backup-settings"
        title={t("settings.title")}
        subtitle={t("settings.globalHint")}
      />
      <Tabs
        variant="pills"
        value={tab}
        onChange={(value) => value && setParams({ tab: value }, { replace: true })}
        keepMounted={false}
      >
        <Tabs.List mb="md">
          <Tabs.Tab value="backups" leftSection={<SlidersHorizontal size={16} />}>
            {t("settings.tabs.backups")}
          </Tabs.Tab>
          <Tabs.Tab value="remote" leftSection={<CloudArrowUp size={16} />}>
            {t("settings.tabs.remote")}
          </Tabs.Tab>
          <Tabs.Tab value="retention" leftSection={<Broom size={16} />}>
            {t("settings.tabs.retention")}
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="backups" maw={720}>
          {settings.isPending && <Loader />}
          {settings.isError && <Alert color="red">{errorMessage(t, settings.error)}</Alert>}
          {settings.data && (
            <Paper withBorder p="lg">
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
        </Tabs.Panel>
        <Tabs.Panel value="remote" maw={720}>
          <Paper withBorder p="lg">
            <Title order={4} mb="sm">
              {t("remote.title")}
            </Title>
            <RemoteStorageForm />
          </Paper>
        </Tabs.Panel>
        <Tabs.Panel value="retention" maw={720}>
          <Paper withBorder p="lg">
            <Title order={4} mb="sm">
              {t("retention.title")}
            </Title>
            <RetentionSettings />
          </Paper>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
