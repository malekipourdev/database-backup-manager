import { Button, Stack, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { CloudSlash } from "../components/Icons";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <Stack gap="sm" mt={48} align="flex-start">
      <span className="cl-hero-icon">
        <CloudSlash size={28} />
      </span>
      <Text ff="monospace" c="var(--color-neutral-500)">
        404
      </Text>
      <Title order={2}>{t("notFound.title")}</Title>
      <Text>{t("notFound.body")}</Text>
      <Button component={Link} to="/instances">
        {t("notFound.home")}
      </Button>
    </Stack>
  );
}
