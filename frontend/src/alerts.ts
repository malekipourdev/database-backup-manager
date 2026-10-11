import type { TFunction } from "i18next";

import type { NotificationLogItem } from "./api/notifications";
import { formatBytes, formatDuration } from "./format";
import { formatDateTime, formatNumber } from "./i18n";

/** The alert's message in the selected language, from its event type and parameters. */
export function renderAlert(item: NotificationLogItem, t: TFunction, lang: string): string {
  const p = item.params as Record<string, unknown>;
  const str = (key: string) => String(p[key] ?? "");
  const num = (key: string) => (typeof p[key] === "number" ? (p[key] as number) : null);
  switch (item.event) {
    case "backup_succeeded":
      return t("alerts.events.backup_succeeded", {
        instance: str("instance"),
        db: str("db"),
        size: formatBytes(num("size"), t, lang),
        duration: formatDuration(num("duration_ms"), t, lang),
      });
    case "stale_backup":
      return t("alerts.events.stale_backup", {
        instance: str("instance"),
        db: str("db"),
        hours: formatNumber(num("hours") ?? 0, lang),
        last: p.last_success ? formatDateTime(str("last_success"), lang) : t("alerts.never"),
      });
    case "disk_low":
      return t("alerts.events.disk_low", {
        percent: formatNumber(Math.round((num("free_percent") ?? 0) * 10) / 10, lang),
        free: formatBytes(num("free"), t, lang),
        total: formatBytes(num("total"), t, lang),
      });
    case "recovered":
      return p.kind === "disk_low"
        ? t("alerts.events.recovered_disk", { free: formatBytes(num("free"), t, lang) })
        : t("alerts.events.recovered_stale", { instance: str("instance"), db: str("db") });
    case "schedule_problem":
      return t("alerts.events.schedule_problem", {
        name: str("name"),
        instance: str("instance"),
        result: t(`schedules.result.${str("result")}`, { defaultValue: str("result") }),
      });
    case "daily_summary":
      return t("alerts.events.daily_summary", {
        ok: formatNumber(num("ok") ?? 0, lang),
        failed: formatNumber(num("failed") ?? 0, lang),
      });
    case "test":
      return t("alerts.events.test");
    default:
      return t(`alerts.events.${item.event}`, {
        instance: str("instance"),
        db: str("db"),
        reason: str("reason"),
        defaultValue: item.event,
      });
  }
}
