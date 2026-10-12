import { Menu, Text, UnstyledButton } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

import type { Server } from "../api/servers";
import { useCurrentServer } from "../server/CurrentServer";
import { CaretDown, Check, HardDrives } from "./Icons";

/** ok | warn | bad | off, for the status dot. */
export function serverTone(server: Server): string {
  if (!server.paired) return "off";
  if (server.last_error) return "bad";
  return server.last_seen_at ? "ok" : "warn";
}

// Detail pages of one item belong to the server they were opened on.
const DETAIL = /^\/(instances|projects)\/[^/]+/;

/**
 * The server the panel works on, and the way to switch it and to reach the Servers page.
 * `compact`: the header's version for small screens.
 */
export function ServerSwitcher({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { server, servers, select } = useCurrentServer();
  if (!server) return null;

  const choose = (id: number) => {
    if (id === server.id) return;
    select(id);
    const detail = DETAIL.exec(pathname);
    if (detail) navigate(`/${detail[1]}`);
  };

  const label = server.kind === "local" ? t("servers.local") : `${server.host}:${server.port}`;

  return (
    <Menu position={compact ? "bottom-end" : "top-start"} width={260} withinPortal shadow="md">
      <Menu.Target>
        {compact ? (
          <UnstyledButton className="cl-server-chip" aria-label={t("servers.switch")}>
            <span className="cl-dot" data-tone={serverTone(server)} />
            <span className="cl-server-chip-name">{server.name}</span>
            <CaretDown size={12} />
          </UnstyledButton>
        ) : (
          <UnstyledButton className="cl-access cl-server-card" aria-label={t("servers.switch")}>
            <span className="cl-server-card-label">{t("servers.current")}</span>
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="cl-dot" data-tone={serverTone(server)} />
              <span className="cl-server-card-name">{server.name}</span>
              <CaretDown size={12} style={{ marginInlineStart: "auto" }} />
            </span>
            <code dir="ltr" style={{ textAlign: "start" }}>
              {label}
            </code>
          </UnstyledButton>
        )}
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>{t("servers.switch")}</Menu.Label>
        {servers.map((s) => (
          <Menu.Item
            key={s.id}
            disabled={!s.paired}
            onClick={() => choose(s.id)}
            leftSection={<span className="cl-dot" data-tone={serverTone(s)} />}
            rightSection={s.id === server.id ? <Check size={14} /> : null}
          >
            <Text size="sm" fw={s.id === server.id ? 600 : 400}>
              {s.name}
            </Text>
            <Text size="xs" c="dimmed">
              {s.kind === "local"
                ? t("servers.local")
                : s.paired
                  ? `${s.host}:${s.port}`
                  : t("servers.notConnected")}
            </Text>
          </Menu.Item>
        ))}
        <Menu.Divider />
        <Menu.Item leftSection={<HardDrives size={16} />} onClick={() => navigate("/servers")}>
          {t("servers.manage")}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
