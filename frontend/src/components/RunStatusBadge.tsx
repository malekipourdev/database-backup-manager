import { Badge } from "@mantine/core";
import {
  CloudCheck,
  HourglassMedium,
  SpinnerGap,
  WarningCircle,
  CloudArrowUp,
  CloudSlash,
  CloudX,
} from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";

import type { RemoteStatus, RunStatus } from "../api/backups";

const COLORS: Record<RunStatus, string> = {
  queued: "gray",
  running: "accent",
  success: "green",
  failed: "red",
};

const ICONS = {
  queued: HourglassMedium,
  running: SpinnerGap,
  success: CloudCheck,
  failed: WarningCircle,
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const { t } = useTranslation();
  const Icon = ICONS[status];
  return (
    <Badge
      color={COLORS[status]}
      variant="light"
      leftSection={<Icon size={12} className={status === "running" ? "cl-spin" : undefined} />}
    >
      {t(`runStatus.${status}`)}
    </Badge>
  );
}

const REMOTE_COLORS: Record<RemoteStatus, string> = {
  uploading: "accent",
  success: "teal",
  failed: "red",
  deleted: "gray",
};

const REMOTE_ICONS = {
  uploading: CloudArrowUp,
  success: CloudCheck,
  failed: CloudX,
  deleted: CloudSlash,
};

export function RemoteStatusBadge({ status }: { status: RemoteStatus }) {
  const { t } = useTranslation();
  const Icon = REMOTE_ICONS[status];
  return (
    <Badge color={REMOTE_COLORS[status]} variant="outline" leftSection={<Icon size={12} />}>
      {t(`remoteStatus.${status}`)}
    </Badge>
  );
}
