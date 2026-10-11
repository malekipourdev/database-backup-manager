import { Badge, Loader } from "@mantine/core";
import { useTranslation } from "react-i18next";

import type { RemoteStatus, RunStatus } from "../api/backups";

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

const REMOTE_COLORS: Record<RemoteStatus, string> = {
  uploading: "blue",
  success: "teal",
  failed: "red",
  deleted: "gray",
};

export function RemoteStatusBadge({ status }: { status: RemoteStatus }) {
  const { t } = useTranslation();
  return (
    <Badge
      color={REMOTE_COLORS[status]}
      variant="outline"
      size="sm"
      leftSection={status === "uploading" ? <Loader size={8} color="blue" /> : undefined}
    >
      {t(`remoteStatus.${status}`)}
    </Badge>
  );
}
