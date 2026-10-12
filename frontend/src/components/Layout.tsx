import { Alert, Button, Loader, SegmentedControl, UnstyledButton } from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Icon as PhosphorIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { ME_KEY, logout, useMe } from "../api/auth";
import { errorMessage } from "../api/client";
import { CurrentServerProvider, useCurrentServer } from "../server/CurrentServer";
import { ServerSwitcher } from "./ServerSwitcher";
import { LANGUAGES } from "../i18n";
import {
  Archive,
  Bell,
  CaretLeft,
  CaretRight,
  Cloud,
  CloudCheck,
  ClockCountdown,
  Cube,
  Database,
  GearSix,
  Question,
  Robot,
  RocketLaunch,
  ShieldCheck,
  SignOut,
} from "./Icons";

type Icon = PhosphorIcon;

const NAV: { to: string; label: string; icon: Icon }[] = [
  { to: "/instances", label: "nav.instances", icon: Database },
  { to: "/backups", label: "nav.backups", icon: Archive },
  { to: "/schedules", label: "nav.schedules", icon: ClockCountdown },
  { to: "/containers", label: "nav.containers", icon: Cube },
  { to: "/projects", label: "nav.projects", icon: RocketLaunch },
  { to: "/notifications", label: "nav.notifications", icon: Bell },
  { to: "/bots", label: "nav.bots", icon: Robot },
  { to: "/settings/backups", label: "nav.settings", icon: GearSix },
  { to: "/account", label: "nav.account", icon: ShieldCheck },
  { to: "/help", label: "nav.help", icon: Question },
];

// Pages reached outside the menu (from the server card), for the header's title.
const OTHER_PAGES = [{ to: "/servers", label: "nav.servers" }];

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

/** Where the panel is being opened from: locally (e.g. through an SSH tunnel) or not. */
export function accessInfo(): { local: boolean; host: string } {
  const { hostname, host } = window.location;
  return { local: LOCAL_HOSTS.has(hostname), host };
}

export function Brand({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  return (
    <Link to="/instances" className="cl-brand">
      <span className="cl-logo">
        <CloudCheck size={19} />
      </span>
      {!compact && (
        <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span className="cl-brand-title">{t("layout.brand")}</span>
          <span className="cl-brand-sub" dir="ltr" style={{ textAlign: "start" }}>
            {t("layout.brandSub")}
          </span>
        </span>
      )}
    </Link>
  );
}

export function LanguageSeg({ short = false }: { short?: boolean }) {
  const { t, i18n } = useTranslation();
  if (short) {
    const next = i18n.language === "fa" ? "en" : "fa";
    return (
      <UnstyledButton
        aria-label={t("language.label")}
        onClick={() => void i18n.changeLanguage(next)}
        c="var(--color-accent)"
        fz={13}
        px={6}
      >
        {t(`language.short.${next}`)}
      </UnstyledButton>
    );
  }
  return (
    <SegmentedControl
      size="sm"
      aria-label={t("language.label")}
      value={i18n.language}
      onChange={(lang) => void i18n.changeLanguage(lang)}
      data={LANGUAGES.map((lang) => ({ value: lang, label: t(`language.${lang}`) }))}
    />
  );
}

export function Layout() {
  return (
    <CurrentServerProvider>
      <PanelLayout />
    </CurrentServerProvider>
  );
}

function PanelLayout() {
  const { t, i18n } = useTranslation();
  const currentServer = useCurrentServer();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { pathname } = useLocation();
  const me = useMe();
  const rtl = i18n.dir(i18n.language) === "rtl";
  const current = [...NAV, ...OTHER_PAGES].find((item) => pathname.startsWith(item.to));
  const Caret = rtl ? CaretLeft : CaretRight;

  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.clear();
      queryClient.setQueryData(ME_KEY, null);
      navigate("/login", { replace: true });
    },
  });
  const username = me.data?.username ?? "";

  return (
    <div className="cl-app" data-glow>
      <aside className="cl-sidebar" aria-label={t("layout.navigation")}>
        <Brand />
        <nav className="cl-nav">
          {NAV.map(({ to, label, icon: ItemIcon }) => (
            <Link
              key={to}
              to={to}
              className="cl-nav-item"
              data-active={pathname.startsWith(to) || undefined}
              aria-current={pathname.startsWith(to) ? "page" : undefined}
            >
              <ItemIcon size={18} />
              <span>{t(label)}</span>
            </Link>
          ))}
        </nav>
        <div style={{ marginTop: "auto" }}>
          <ServerSwitcher />
        </div>
      </aside>

      <div className="cl-main">
        <header className="cl-header">
          <div className="cl-crumbs">
            <span className="cl-mobile-only">
              <Brand compact />
            </span>
            <span className="cl-desktop-only" style={{ display: "contents" }}>
              <Cloud size={15} />
              <span>{t("layout.console")}</span>
              <Caret size={11} />
            </span>
            <span data-current>{current ? t(current.label) : t("notFound.title")}</span>
          </div>
          <div className="cl-header-actions">
            <span className="cl-desktop-only">
              <LanguageSeg />
            </span>
            <span className="cl-mobile-only">
              <ServerSwitcher compact />
            </span>
            <span className="cl-mobile-only">
              <LanguageSeg short />
            </span>
            {username && (
              <Link
                to="/account"
                className="cl-user cl-desktop-only"
                style={{ color: "inherit", textDecoration: "none" }}
                title={t("nav.account")}
              >
                <span className="cl-avatar">{username.slice(0, 1)}</span>
                <span dir="ltr">{username}</span>
                {me.data?.two_factor_enabled && (
                  <ShieldCheck
                    size={14}
                    color="var(--color-success)"
                    aria-label={t("account.on")}
                  />
                )}
              </Link>
            )}
            <Button
              variant="subtle"
              size="compact-sm"
              leftSection={<SignOut size={16} />}
              loading={signOut.isPending}
              onClick={() => signOut.mutate()}
              aria-label={t("auth.signOut")}
            >
              <span className="cl-desktop-only">{t("auth.signOut")}</span>
            </Button>
          </div>
        </header>
        <main className="cl-content">
          <div className="cl-content-inner">
            {currentServer.ready ? (
              <Outlet />
            ) : currentServer.error ? (
              <Alert color="red">{errorMessage(t, currentServer.error)}</Alert>
            ) : (
              <Loader />
            )}
          </div>
        </main>
      </div>

      <nav className="cl-tabbar" aria-label={t("layout.navigation")}>
        {NAV.map(({ to, label, icon: ItemIcon }) => (
          <Link
            key={to}
            to={to}
            className="cl-tab"
            data-active={pathname.startsWith(to) || undefined}
          >
            <span className="cl-tab-icon">
              <ItemIcon size={19} />
            </span>
            {t(label)}
          </Link>
        ))}
      </nav>
    </div>
  );
}
