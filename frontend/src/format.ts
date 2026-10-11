import type { TFunction } from "i18next";

import { localeOf } from "./i18n";

const UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

/** Human-readable size in the selected language (binary units). */
export function formatBytes(bytes: number | null | undefined, t: TFunction, lang: string): string {
  if (bytes === null || bytes === undefined) return t("common.notAvailable");
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const n = new Intl.NumberFormat(localeOf(lang), {
    maximumFractionDigits: unit === 0 ? 0 : 1,
  }).format(value);
  return t(`units.${UNITS[unit]}`, { n });
}

/** Duration like "1h 2m 3s" with localized units and digits. */
export function formatDuration(ms: number | null | undefined, t: TFunction, lang: string): string {
  if (ms === null || ms === undefined) return t("common.notAvailable");
  if (ms < 1000) return t("duration.sub");
  const nf = new Intl.NumberFormat(localeOf(lang));
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const parts: string[] = [];
  if (hours) parts.push(t("duration.h", { n: nf.format(hours) }));
  if (hours || minutes) parts.push(t("duration.m", { n: nf.format(minutes) }));
  parts.push(t("duration.s", { n: nf.format(seconds) }));
  return parts.join(" ");
}
