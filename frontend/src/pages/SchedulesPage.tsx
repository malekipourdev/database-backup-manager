import { Paper, Stack } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { PageHeader } from "../components/PageHeader";
import { ServerBadge } from "../components/ServerBadge";
import { ScheduleList } from "../components/ScheduleList";

export function SchedulesPage() {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <PageHeader
        help="schedules"
        title={t("schedules.title")}
        badge={<ServerBadge />}
        subtitle={t("schedules.hint")}
      />
      <Paper withBorder p="lg">
        <ScheduleList />
      </Paper>
    </Stack>
  );
}
