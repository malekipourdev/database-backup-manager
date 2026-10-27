import type { Icon } from "@phosphor-icons/react";

import {
  Archive,
  Bell,
  ClockCountdown,
  Cube,
  Database,
  GearSix,
  Globe,
  HardDrives,
  Question,
  Robot,
  RocketLaunch,
  ShieldCheck,
  SquaresFour,
} from "./components/Icons";

export interface NavItem {
  to: string;
  /** i18n key of the menu label (also the page's title in the header and the tab). */
  label: string;
  icon: Icon;
  /** Shows only the current server's items. */
  scoped?: boolean;
  /** Extra words the "Go to" search matches (i18n key). */
  keywords?: string;
  /** Not listed in the menu (reached another way); still titled and found by "Go to". */
  hidden?: boolean;
}

export interface NavGroup {
  id: string;
  /** i18n key of the group heading; none for the overview at the top. */
  label?: string;
  items: NavItem[];
}

/** The panel's menu, grouped from the widest scope down: servers, applications, databases. */
export const NAV_GROUPS: NavGroup[] = [
  {
    id: "home",
    items: [{ to: "/overview", label: "nav.overview", icon: SquaresFour, scoped: true }],
  },
  {
    id: "infra",
    label: "nav.groups.infra",
    items: [
      // Opened from the current-server card ("Manage all servers").
      { to: "/servers", label: "nav.servers", icon: HardDrives, hidden: true },
      {
        to: "/webservers",
        label: "nav.webservers",
        icon: Globe,
        scoped: true,
        keywords: "nav.keywords.webservers",
      },
    ],
  },
  {
    id: "apps",
    label: "nav.groups.apps",
    items: [
      { to: "/projects", label: "nav.projects", icon: RocketLaunch, scoped: true },
      { to: "/containers", label: "nav.containers", icon: Cube, scoped: true },
    ],
  },
  {
    id: "data",
    label: "nav.groups.data",
    items: [
      { to: "/instances", label: "nav.instances", icon: Database, scoped: true },
      { to: "/backups", label: "nav.backups", icon: Archive, scoped: true },
      { to: "/schedules", label: "nav.schedules", icon: ClockCountdown, scoped: true },
      {
        to: "/settings/backups",
        label: "nav.settings",
        icon: GearSix,
        keywords: "nav.keywords.settings",
      },
    ],
  },
  {
    id: "alerts",
    label: "nav.groups.alerts",
    items: [
      { to: "/notifications", label: "nav.notifications", icon: Bell },
      { to: "/bots", label: "nav.bots", icon: Robot, keywords: "nav.keywords.bots" },
    ],
  },
  {
    id: "system",
    label: "nav.groups.system",
    items: [
      { to: "/account", label: "nav.account", icon: ShieldCheck, keywords: "nav.keywords.account" },
      { to: "/help", label: "nav.help", icon: Question },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items);

/** The phone's bottom bar: the most used pages; everything else is under "Menu". */
export const TAB_ITEMS: NavItem[] = ["/overview", "/containers", "/projects", "/instances"].map(
  (to) => NAV_ITEMS.find((item) => item.to === to)!,
);

export function isActive(item: NavItem, pathname: string): boolean {
  return pathname === item.to || pathname.startsWith(`${item.to}/`);
}

export interface NavLocation {
  group: NavGroup | null;
  item: NavItem | null;
  /** i18n key of a page below the item (new, edit, details), if any. */
  sub: string | null;
}

/** Where a path is in the menu: its group, item and sub-page, for the breadcrumbs and title. */
export function locate(pathname: string): NavLocation {
  for (const group of NAV_GROUPS) {
    const item = group.items.find((candidate) => isActive(candidate, pathname));
    if (!item) continue;
    const rest = pathname.slice(item.to.length).replace(/^\/|\/$/g, "");
    let sub: string | null = null;
    if (rest === "new") sub = "nav.sub.new";
    else if (rest.endsWith("/edit")) sub = "nav.sub.edit";
    else if (rest && item.to === "/help") sub = "nav.sub.article";
    else if (rest) sub = "nav.sub.details";
    return { group, item, sub };
  }
  return { group: null, item: null, sub: null };
}
