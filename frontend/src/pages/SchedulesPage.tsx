import { Paper, Stack, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { ScheduleList } from "../components/ScheduleList";

export function SchedulesPage() {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Title order={2}>{t("schedules.title")}</Title>
      <Text c="dimmed" size="sm">
        {t("schedules.hint")}
      </Text>
      <Paper withBorder p="lg" radius="md">
        <ScheduleList />
      </Paper>
    </Stack>
  );
}
