import { Alert, Code, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";

import type { ConnectionTestResult } from "../api/instances";
import { formatDateTime } from "../i18n";

export function ConnectionResult({ result }: { result: ConnectionTestResult }) {
  const { t, i18n } = useTranslation();
  const testedAt = t("connection.testedAt", {
    time: formatDateTime(result.tested_at, i18n.language),
  });

  if (result.ok) {
    return (
      <Alert color="green" title={t("connection.successTitle")} role="status">
        <Text size="sm">
          {t("connection.successBody", {
            type: result.server_type ? t(`connection.serverType.${result.server_type}`) : "",
            version: result.server_version ?? "",
          })}
        </Text>
        <Text size="xs" c="dimmed" mt={4}>
          {testedAt}
        </Text>
      </Alert>
    );
  }

  const code = result.error_code ?? "server_error";
  return (
    <Alert
      color="red"
      title={`${t("connection.failureTitle")}: ${t(`errors.${code}`)}`}
      role="alert"
    >
      <Text size="sm">{t(`connection.explain.${code}`)}</Text>
      {result.error_detail && (
        <Code block mt="xs" dir="ltr">
          {result.error_detail}
        </Code>
      )}
      <Text size="xs" c="dimmed" mt={4}>
        {testedAt}
      </Text>
    </Alert>
  );
}
