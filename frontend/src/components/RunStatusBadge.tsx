import { Badge, Loader } from "@mantine/core";
import { useTranslation } from "react-i18next";

import type { RunStatus } from "../api/backups";

const COLORS: Record<RunStatus, string> = {
  queued: "gray",
  running: "blue",
  success: "green",
  failed: "red",
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const { t } = useTranslation();
  return (
    <Badge
      color={COLORS[status]}
      variant="light"
      leftSection={status === "running" ? <Loader size={10} color="blue" /> : undefined}
    >
      {t(`runStatus.${status}`)}
    </Badge>
  );
}
