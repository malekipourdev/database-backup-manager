import { Badge } from "@mantine/core";

import { useCurrentServer } from "../server/CurrentServer";
import { HardDrives } from "./Icons";

/** Next to the title of pages that show one server's items: which server. */
export function ServerBadge() {
  const { server } = useCurrentServer();
  if (!server) return null;
  return (
    <Badge
      variant="light"
      color="gray"
      leftSection={<HardDrives size={12} />}
      style={{ textTransform: "none" }}
      data-testid="server-badge"
    >
      {server.name}
    </Badge>
  );
}
