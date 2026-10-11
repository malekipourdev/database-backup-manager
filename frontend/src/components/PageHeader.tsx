import { Anchor, Group, Stack, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ArrowLeft, ArrowRight } from "./Icons";

interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  /** Shown next to the title (e.g. a status tag). */
  badge?: ReactNode;
  actions?: ReactNode;
  back?: { to: string; label: string };
}

/** Page title row of the Cloud theme: back link, title, subtitle, actions. */
export function PageHeader({ title, subtitle, badge, actions, back }: PageHeaderProps) {
  const { i18n } = useTranslation();
  const Arrow = i18n.dir(i18n.language) === "rtl" ? ArrowRight : ArrowLeft;
  return (
    <div className="cl-page-head">
      <Stack gap={4} style={{ minWidth: 0 }}>
        {back && (
          <Anchor
            component={Link}
            to={back.to}
            size="sm"
            c="var(--color-neutral-400)"
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            <Arrow size={13} />
            {back.label}
          </Anchor>
        )}
        <Group gap="sm" wrap="nowrap">
          <Title order={2} style={{ overflowWrap: "anywhere" }}>
            {title}
          </Title>
          {badge}
        </Group>
        {subtitle && <span className="cl-page-sub">{subtitle}</span>}
      </Stack>
      {actions && <Group gap="xs">{actions}</Group>}
    </div>
  );
}
