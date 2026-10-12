import { useTranslation } from "react-i18next";

import { useServers } from "../api/servers";

/** How a database is reached: directly from the panel, or through another server's agent. */
export function RouteLabel({ serverId }: { serverId: number | null }) {
  const { t } = useTranslation();
  const servers = useServers();
  if (serverId === null) return <>{t("instances.columns.routeDirect")}</>;
  const name = servers.data?.find((s) => s.id === serverId)?.name ?? `#${serverId}`;
  return <>{t("instances.routeServer", { name })}</>;
}
