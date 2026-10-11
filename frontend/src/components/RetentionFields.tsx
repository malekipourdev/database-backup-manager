import { NumberInput, SimpleGrid, Stack, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";

import type { RetentionPolicy } from "../api/storage";
import { formatNumber } from "../i18n";

type Field = keyof RetentionPolicy;

const GROUPS: { title: string; keep: Field; age: Field }[] = [
  { title: "retention.local", keep: "local_keep_last", age: "local_max_age_days" },
  { title: "retention.remote", keep: "remote_keep_last", age: "remote_max_age_days" },
];

interface RetentionFieldsProps {
  value: RetentionPolicy;
  onChange: (value: RetentionPolicy) => void;
  disabled?: boolean;
}

/** Keep-last / max-age inputs for local and remote copies; empty means "no limit". */
export function RetentionFields({ value, onChange, disabled }: RetentionFieldsProps) {
  const { t } = useTranslation();
  const set = (field: Field, raw: string | number) =>
    onChange({ ...value, [field]: raw === "" || raw === null ? null : Number(raw) });

  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="lg">
      {GROUPS.map((group) => (
        <Stack key={group.title} gap="xs">
          <Text fw={600} size="sm">
            {t(group.title)}
          </Text>
          <NumberInput
            label={t("retention.keepLast")}
            description={t("retention.keepLastHelp")}
            placeholder={t("retention.noLimit")}
            min={1}
            max={100000}
            allowDecimal={false}
            allowNegative={false}
            disabled={disabled}
            value={value[group.keep] ?? ""}
            onChange={(raw) => set(group.keep, raw)}
          />
          <NumberInput
            label={t("retention.maxAge")}
            description={
              group.age === "remote_max_age_days"
                ? t("retention.remoteMaxAgeHelp")
                : t("retention.maxAgeHelp")
            }
            placeholder={t("retention.noLimit")}
            min={group.age === "remote_max_age_days" ? 7 : 1}
            max={36500}
            allowDecimal={false}
            allowNegative={false}
            disabled={disabled}
            value={value[group.age] ?? ""}
            onChange={(raw) => set(group.age, raw)}
          />
        </Stack>
      ))}
    </SimpleGrid>
  );
}

/** One-line summary like "keep 7 · 30 days" for a policy side. */
export function policySummary(
  t: (key: string, options?: Record<string, unknown>) => string,
  lang: string,
  keep: number | null,
  age: number | null,
): string {
  const parts: string[] = [];
  if (keep !== null)
    parts.push(t("retention.summaryKeep", { count: keep, n: formatNumber(keep, lang) }));
  if (age !== null)
    parts.push(t("retention.summaryAge", { count: age, n: formatNumber(age, lang) }));
  return parts.length ? parts.join(" · ") : t("retention.keepAll");
}
