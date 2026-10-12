import { Badge, Loader } from "@mantine/core";
import { useTranslation } from "react-i18next";

import type { DeploymentSummary } from "../api/projects";

const COLORS = { queued: "gray", running: "blue", success: "green", failed: "red" } as const;

export function DeployStatusBadge({ d }: { d: DeploymentSummary }) {
  const { t } = useTranslation();
  const running = d.status === "running" || d.status === "queued";
  return (
    <Badge
      color={COLORS[d.status]}
      variant="light"
      style={{ flexShrink: 0 }}
      leftSection={running ? <Loader size={10} color="blue" /> : undefined}
    >
      {t(`projects.status.${d.status}`)}
      {running && d.step ? ` · ${t(`projects.step.${d.step}`, { defaultValue: d.step })}` : ""}
    </Badge>
  );
}
