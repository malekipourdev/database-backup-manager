import { Badge } from "@mantine/core";
import { useTranslation } from "react-i18next";

import type { ContainerSummary } from "../api/containers";

const COLORS: Record<string, string> = {
  running: "green",
  exited: "gray",
  created: "gray",
  paused: "yellow",
  restarting: "red",
  dead: "red",
};

export function ContainerStateBadge({ c }: { c: ContainerSummary }) {
  const { t } = useTranslation();
  if (c.problem) {
    return (
      <Badge
        color={c.problem === "unhealthy" ? "orange" : "red"}
        variant="light"
        style={{ flexShrink: 0 }}
      >
        {t(`containers.problem.${c.problem}`)}
      </Badge>
    );
  }
  return (
    <Badge color={COLORS[c.state] ?? "gray"} variant="light" style={{ flexShrink: 0 }}>
      {t(`containers.state.${c.state}`, { defaultValue: c.state })}
      {c.health === "healthy" && ` · ${t("containers.health.healthy")}`}
      {c.health === "starting" && ` · ${t("containers.health.starting")}`}
    </Badge>
  );
}
