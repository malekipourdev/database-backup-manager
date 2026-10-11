import { AppShell, Button, Group, Title, UnstyledButton } from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { ME_KEY, logout } from "../api/auth";
import { LanguageSwitcher } from "./LanguageSwitcher";

const NAV = [
  { to: "/instances", label: "nav.instances" },
  { to: "/backups", label: "nav.backups" },
  { to: "/schedules", label: "nav.schedules" },
  { to: "/settings/backups", label: "nav.settings" },
];

export function Layout() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { pathname } = useLocation();

  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.clear();
      queryClient.setQueryData(ME_KEY, null);
      navigate("/login", { replace: true });
    },
  });

  return (
    <AppShell header={{ height: 60 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="lg" wrap="nowrap">
            <UnstyledButton component={Link} to="/instances" visibleFrom="md">
              <Title order={4}>{t("common.appName")}</Title>
            </UnstyledButton>
            <Group gap={4} wrap="nowrap">
              {NAV.map((item) => (
                <Button
                  key={item.to}
                  component={Link}
                  to={item.to}
                  variant={pathname.startsWith(item.to) ? "light" : "subtle"}
                  size="xs"
                >
                  {t(item.label)}
                </Button>
              ))}
            </Group>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <LanguageSwitcher />
            <Button
              variant="subtle"
              size="xs"
              loading={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              {t("auth.signOut")}
            </Button>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <div style={{ maxWidth: 1100, marginInline: "auto" }}>
          <Outlet />
        </div>
      </AppShell.Main>
    </AppShell>
  );
}
