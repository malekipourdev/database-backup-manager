import { Button, Stack, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <Stack align="center" mt="xl" gap="sm">
      <Title order={2}>{t("notFound.title")}</Title>
      <Text c="dimmed">{t("notFound.body")}</Text>
      <Button component={Link} to="/instances" variant="light">
        {t("notFound.home")}
      </Button>
    </Stack>
  );
}
