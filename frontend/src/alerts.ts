import type { TFunction } from "i18next";

import type { NotificationLogItem } from "./api/notifications";
import { formatBytes, formatDuration } from "./format";
import { formatDateTime, formatNumber, formatPercent } from "./i18n";

const RECOVERED_KINDS = new Set([
  "container_down",
  "container_restarting",
  "container_unhealthy",
  "container_resources",
  "host_memory",
  "host_disk",
  "agent",
]);

/** The alert's message in the selected language, from its event type and parameters. */
export function renderAlert(item: NotificationLogItem, t: TFunction, lang: string): string {
  const text = renderBody(item, t, lang);
  // Alerts about another server than the panel's own name it first.
  const server = (item.params as Record<string, unknown>).server;
  return typeof server === "string" && server ? `${server}: ${text}` : text;
}

function renderBody(item: NotificationLogItem, t: TFunction, lang: string): string {
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
    case "container_down":
      return p.oom
        ? t("alerts.events.container_down_oom", { name: str("name") })
        : t("alerts.events.container_down", {
            name: str("name"),
            code: formatNumber(num("exit_code") ?? 0, lang),
          });
    case "container_restarting":
      return t("alerts.events.container_restarting", {
        name: str("name"),
        n: formatNumber(num("restarts") ?? 0, lang),
        minutes: formatNumber(num("minutes") ?? 0, lang),
      });
    case "container_unhealthy":
      return t("alerts.events.container_unhealthy", { name: str("name") });
    case "container_resources":
      return t("alerts.events.container_resources", {
        name: str("name"),
        cpu: num("cpu") === null ? "—" : formatPercent(Math.round(num("cpu")!), lang),
        memory:
          num("memory_percent") === null
            ? "—"
            : `${formatBytes(num("memory_usage"), t, lang)} (${formatPercent(
                Math.round(num("memory_percent")!),
                lang,
              )})`,
      });
    case "host_resources":
      return t(`alerts.events.host_${p.kind === "disk" ? "disk" : "memory"}`, {
        percent: formatPercent(Math.round(num("percent") ?? 0), lang),
        used: formatBytes(num("used"), t, lang),
        total: formatBytes(num("total"), t, lang),
      });
    case "deploy_succeeded":
      return t("alerts.events.deploy_succeeded", {
        project: str("project"),
        commit: str("commit"),
        message: str("message"),
        actor: str("actor"),
      });
    case "deploy_failed":
      return t("alerts.events.deploy_failed", {
        project: str("project"),
        error:
          t(`projects.errors.${str("error")}`, { defaultValue: str("error") }) +
          (p.detail ? ` (${str("detail")})` : ""),
      });
    case "agent_unreachable":
      return t("alerts.events.agent_unreachable", {
        code: t(`errors.${str("code")}`, { defaultValue: str("code") }),
      });
    case "site_down":
      return t("alerts.events.site_down", {
        url: str("url"),
        reason:
          typeof p.code === "number"
            ? `HTTP ${p.code}`
            : t(`webservers.checks.errors.${str("error")}`, { defaultValue: str("error") }),
      });
    case "cert_expiring": {
      const values = {
        names: (Array.isArray(p.names) ? p.names : []).join(", ") || str("path"),
        days: formatNumber(num("days") ?? 0, lang),
        date: p.not_after ? formatDateTime(str("not_after"), lang) : "—",
      };
      return (num("days") ?? 0) < 0
        ? t("alerts.events.cert_expired", values)
        : t("alerts.events.cert_expiring", values);
    }
    case "recovered":
      if (p.kind === "site_down") {
        return t("alerts.events.recovered_site_down", {
          url: str("url"),
          minutes: formatNumber(num("minutes") ?? 0, lang),
        });
      }
      if (p.kind === "cert") {
        return t("alerts.events.recovered_cert", {
          names: (Array.isArray(p.names) ? p.names : []).join(", ") || str("path"),
          date: p.not_after ? formatDateTime(str("not_after"), lang) : "—",
        });
      }
      if (typeof p.kind === "string" && RECOVERED_KINDS.has(p.kind)) {
        return t(`alerts.events.recovered_${p.kind}`, {
          name: str("name"),
          percent: formatPercent(Math.round(num("percent") ?? 0), lang),
        });
      }
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
