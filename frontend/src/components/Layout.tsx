import {
  Alert,
  Button,
  Drawer,
  Kbd,
  Loader,
  SegmentedControl,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { Spotlight, type SpotlightActionData, spotlight } from "@mantine/spotlight";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { ME_KEY, logout, useMe } from "../api/auth";
import { errorMessage } from "../api/client";
import { LANGUAGES } from "../i18n";
import { NAV_GROUPS, type NavItem, TAB_ITEMS, isActive, locate } from "../navigation";
import { CurrentServerProvider, useCurrentServer } from "../server/CurrentServer";
import {
  CaretDown,
  CaretLeft,
  CaretRight,
  HardDrives,
  InfinityIcon,
  List,
  MagnifyingGlass,
  ShieldCheck,
  SignOut,
} from "./Icons";
import { ServerSwitcher, serverTone } from "./ServerSwitcher";

// The key shown next to "Go to" for its shortcut.
const MOD_KEY = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

/** Where the panel is being opened from: locally (e.g. through an SSH tunnel) or not. */
export function accessInfo(): { local: boolean; host: string } {
  const { hostname, host } = window.location;
  return { local: LOCAL_HOSTS.has(hostname), host };
}

export function Brand({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  return (
    <Link
      to="/overview"
      className="cl-brand"
      aria-label={compact ? t("common.appName") : undefined}
    >
      <span className="cl-logo" aria-hidden>
        <InfinityIcon size={20} weight="bold" />
      </span>
      {!compact && (
        <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span className="cl-brand-title">{t("common.appName")}</span>
          <span className="cl-brand-sub">{t("layout.brandSub")}</span>
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
        className="cl-icon-button"
        aria-label={`${t("language.label")}: ${t(`language.${next}`)}`}
        lang={next}
        onClick={() => void i18n.changeLanguage(next)}
        c="var(--color-accent)"
        fz={13}
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

const OPEN_GROUPS_KEY = "mbp.nav.open";

function readOpenGroups(): Set<string> {
  try {
    const raw = localStorage.getItem(OPEN_GROUPS_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((v) => typeof v === "string") : []);
  } catch {
    return new Set(); // storage can be unavailable; every group then starts closed
  }
}

function storeOpenGroups(open: Set<string>): void {
  try {
    localStorage.setItem(OPEN_GROUPS_KEY, JSON.stringify([...open]));
  } catch {
    // Remembering which groups are open is a convenience only.
  }
}

/**
 * The grouped menu: in the sidebar, and in the phone's menu drawer. Groups fold; the one
 * holding the current page opens by itself, and the others stay as the admin left them.
 */
function NavMenu({ idPrefix }: { idPrefix: string }) {
  const { t, i18n } = useTranslation();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(readOpenGroups);
  const current = locate(pathname).group?.id;
  const Caret = i18n.dir(i18n.language) === "rtl" ? CaretLeft : CaretRight;

  useEffect(() => {
    if (!current) return;
    setOpen((previous) => {
      if (previous.has(current)) return previous;
      const next = new Set(previous).add(current);
      storeOpenGroups(next);
      return next;
    });
  }, [current]);

  const toggle = (id: string) =>
    setOpen((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      storeOpenGroups(next);
      return next;
    });

  return (
    <div className="cl-nav">
      {NAV_GROUPS.map((group) => {
        const items = (
          <ul id={`${idPrefix}-${group.id}-items`}>
            {group.items
              .filter((item) => !item.hidden)
              .map((item) => (
                <li key={item.to}>
                  <NavLink item={item} active={isActive(item, pathname)} />
                </li>
              ))}
          </ul>
        );
        if (!group.label) {
          return (
            <div key={group.id} className="cl-nav-group">
              {items}
            </div>
          );
        }
        const expanded = open.has(group.id);
        const headingId = `${idPrefix}-${group.id}`;
        return (
          <div
            key={group.id}
            className="cl-nav-group"
            role="group"
            aria-labelledby={headingId}
            data-open={expanded || undefined}
          >
            <UnstyledButton
              id={headingId}
              className="cl-nav-heading"
              aria-expanded={expanded}
              aria-controls={`${idPrefix}-${group.id}-items`}
              data-current={group.id === current || undefined}
              onClick={() => toggle(group.id)}
            >
              <span>{t(group.label)}</span>
              {expanded ? <CaretDown size={12} aria-hidden /> : <Caret size={12} aria-hidden />}
            </UnstyledButton>
            {expanded && items}
          </div>
        );
      })}
    </div>
  );
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const { t } = useTranslation();
  const ItemIcon = item.icon;
  return (
    <Link
      to={item.to}
      className="cl-nav-item"
      data-active={active || undefined}
      aria-current={active ? "page" : undefined}
    >
      <ItemIcon size={18} aria-hidden />
      <span>{t(item.label)}</span>
    </Link>
  );
}

/** "Section › Page › Sub-page" above the content; the last part is the current page. */
function Breadcrumbs() {
  const { t, i18n } = useTranslation();
  const { pathname } = useLocation();
  const { group, item, sub } = locate(pathname);
  const Caret = i18n.dir(i18n.language) === "rtl" ? CaretLeft : CaretRight;
  const separator = <Caret size={11} aria-hidden className="cl-crumb-sep" />;
  return (
    <nav aria-label={t("layout.breadcrumbs")} className="cl-crumbs">
      <ol>
        {group?.label && (
          <li className="cl-desktop-only">
            <span>{t(group.label)}</span>
            {separator}
          </li>
        )}
        {item && sub ? (
          <>
            <li>
              <Link to={item.to}>{t(item.label)}</Link>
              {separator}
            </li>
            <li aria-current="page" data-current>
              {t(sub)}
            </li>
          </>
        ) : (
          <li aria-current="page" data-current>
            {item ? t(item.label) : t("notFound.title")}
          </li>
        )}
      </ol>
    </nav>
  );
}

/** Keeps the browser tab's title on the current page: "Page · DevOps Manager". */
function useDocumentTitle() {
  const { t, i18n } = useTranslation();
  const { pathname } = useLocation();
  useEffect(() => {
    const { item, sub } = locate(pathname);
    const page = item ? t(item.label) : t("notFound.title");
    const parts = sub ? [t(sub), page] : [page];
    document.title = [...parts, t("common.appName")].join(" · ");
  }, [pathname, t, i18n.language]);
}

/**
 * After moving to another page, focus goes to its title (or the content), so keyboard and
 * screen-reader users start there instead of at the top of the menu.
 */
function useFocusOnNavigate(main: React.RefObject<HTMLElement>) {
  const { pathname } = useLocation();
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const frame = requestAnimationFrame(() => {
      const target = main.current?.querySelector<HTMLElement>("h1") ?? main.current;
      if (!target) return;
      if (target !== main.current) target.tabIndex = -1;
      target.focus({ preventScroll: true });
      window.scrollTo({ top: 0 });
    });
    return () => cancelAnimationFrame(frame);
  }, [pathname, main]);
}

function SearchButton({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  if (compact) {
    return (
      <UnstyledButton
        className="cl-icon-button"
        aria-label={t("layout.search")}
        onClick={() => spotlight.open()}
      >
        <MagnifyingGlass size={18} aria-hidden />
      </UnstyledButton>
    );
  }
  return (
    <UnstyledButton
      className="cl-search"
      onClick={() => spotlight.open()}
      aria-keyshortcuts="Control+K Meta+K"
    >
      <MagnifyingGlass size={15} aria-hidden />
      <span>{t("layout.search")}</span>
      <span className="cl-search-keys" aria-hidden dir="ltr">
        <Kbd size="xs">{MOD_KEY}</Kbd> <Kbd size="xs">K</Kbd>
      </span>
    </UnstyledButton>
  );
}

/** "Go to" palette (Ctrl+K or /): every page, and the servers to switch to. */
function GoTo() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { servers, server, select } = useCurrentServer();
  const actions = useMemo<SpotlightActionData[]>(() => {
    const pages = NAV_GROUPS.flatMap((group) =>
      group.items.map((item) => {
        const ItemIcon = item.icon;
        return {
          id: `page:${item.to}`,
          label: t(item.label),
          description: group.label ? t(group.label) : undefined,
          keywords: item.keywords ? t(item.keywords) : undefined,
          leftSection: <ItemIcon size={18} aria-hidden />,
          onClick: () => navigate(item.to),
        };
      }),
    );
    const switches = servers
      .filter((s) => s.paired && s.id !== server?.id)
      .map((s) => ({
        id: `server:${s.id}`,
        label: t("layout.switchTo", { name: s.name }),
        description: t("servers.switch"),
        leftSection: <HardDrives size={18} aria-hidden />,
        rightSection: <span className="cl-dot" data-tone={serverTone(s)} aria-hidden />,
        onClick: () => select(s.id),
      }));
    return [...pages, ...switches];
  }, [t, navigate, servers, server, select]);

  return (
    <Spotlight
      actions={actions}
      shortcut={["mod + K", "/"]}
      highlightQuery
      limit={20}
      nothingFound={t("layout.searchEmpty")}
      searchProps={{
        leftSection: <MagnifyingGlass size={18} aria-hidden />,
        placeholder: t("layout.searchPlaceholder"),
        "aria-label": t("layout.search"),
      }}
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
  const main = useRef<HTMLElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  useDocumentTitle();
  useFocusOnNavigate(main);

  useEffect(() => setMenuOpen(false), [pathname]);

  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.clear();
      queryClient.setQueryData(ME_KEY, null);
      navigate("/login", { replace: true });
    },
  });
  const username = me.data?.username ?? "";
  // The "Menu" tab is the active one on pages that have no tab of their own.
  const onTab = TAB_ITEMS.some((item) => isActive(item, pathname));

  return (
    <div className="cl-app" data-glow>
      <a href="#main" className="cl-skip">
        {t("layout.skipToContent")}
      </a>

      <aside className="cl-sidebar">
        <Brand />
        <SearchButton />
        <nav aria-label={t("layout.navigation")} className="cl-sidebar-nav">
          <NavMenu idPrefix="side" />
        </nav>
        <ServerSwitcher />
      </aside>

      <div className="cl-main">
        <header className="cl-header">
          <div className="cl-header-start">
            <span className="cl-mobile-only">
              <Brand compact />
            </span>
            <Breadcrumbs />
          </div>
          <div className="cl-header-actions">
            <span className="cl-mobile-only">
              <ServerSwitcher compact />
            </span>
            <span className="cl-mobile-only">
              <SearchButton compact />
            </span>
            <span className="cl-desktop-only">
              <LanguageSeg />
            </span>
            {username && (
              <Tooltip label={t("nav.account")}>
                <Link to="/account" className="cl-user cl-desktop-only">
                  <span className="cl-avatar" aria-hidden>
                    {username.slice(0, 1)}
                  </span>
                  <span dir="ltr">{username}</span>
                  {me.data?.two_factor_enabled && (
                    <ShieldCheck
                      size={14}
                      color="var(--color-success)"
                      aria-label={t("layout.twoFactorOn")}
                      role="img"
                    />
                  )}
                </Link>
              </Tooltip>
            )}
            <Button
              variant="subtle"
              size="compact-sm"
              className="cl-desktop-only"
              leftSection={<SignOut size={16} aria-hidden />}
              loading={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              {t("auth.signOut")}
            </Button>
          </div>
        </header>
        <main className="cl-content" id="main" ref={main} tabIndex={-1}>
          <div className="cl-content-inner">
            {currentServer.ready ? (
              <Outlet />
            ) : currentServer.error ? (
              <Alert color="red">{errorMessage(t, currentServer.error)}</Alert>
            ) : (
              <Loader aria-label={t("common.loading")} />
            )}
          </div>
        </main>
      </div>

      <nav className="cl-tabbar" aria-label={t("layout.quickNavigation")}>
        {TAB_ITEMS.map((item) => {
          const ItemIcon = item.icon;
          const active = isActive(item, pathname);
          return (
            <Link
              key={item.to}
              to={item.to}
              className="cl-tab"
              data-active={active || undefined}
              aria-current={active ? "page" : undefined}
            >
              <span className="cl-tab-icon">
                <ItemIcon size={19} aria-hidden />
              </span>
              {t(item.label)}
            </Link>
          );
        })}
        <UnstyledButton
          className="cl-tab"
          data-active={!onTab || menuOpen || undefined}
          aria-expanded={menuOpen}
          aria-controls="cl-menu-drawer"
          onClick={() => setMenuOpen(true)}
        >
          <span className="cl-tab-icon">
            <List size={19} aria-hidden />
          </span>
          {t("layout.menu")}
        </UnstyledButton>
      </nav>

      <Drawer
        id="cl-menu-drawer"
        opened={menuOpen}
        onClose={() => setMenuOpen(false)}
        position={rtl ? "right" : "left"}
        size={300}
        title={t("layout.menu")}
        closeButtonProps={{ "aria-label": t("common.close") }}
      >
        <div className="cl-drawer">
          <nav aria-label={t("layout.navigation")}>
            <NavMenu idPrefix="drawer" />
          </nav>
          <div className="cl-drawer-foot">
            <LanguageSeg />
            {username && (
              <span className="cl-drawer-user" dir="ltr">
                {username}
              </span>
            )}
            <Button
              variant="subtle"
              leftSection={<SignOut size={16} aria-hidden />}
              loading={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              {t("auth.signOut")}
            </Button>
          </div>
        </div>
      </Drawer>

      <GoTo />
    </div>
  );
}
