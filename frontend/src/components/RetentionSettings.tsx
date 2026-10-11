import { Alert, Button, Group, List, Loader, Modal, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { errorMessage } from "../api/client";
import {
  EMPTY_POLICY,
  type RetentionPolicy,
  type RetentionReport,
  useApplyRetention,
  useRetention,
  useSaveRetention,
} from "../api/storage";
import { formatDateTime, formatNumber } from "../i18n";
import { RetentionFields } from "./RetentionFields";

function ReportList({ report }: { report: RetentionReport }) {
  const { t, i18n } = useTranslation();
  if (report.deleted.length === 0 && report.errors.length === 0) {
    return <Text size="sm">{t("retention.nothingToDelete")}</Text>;
  }
  return (
    <Stack gap="xs">
      {report.deleted.length > 0 && (
        <List size="sm" spacing={2} data-testid="retention-report">
          {report.deleted.map((item) => (
            <List.Item key={`${item.target}-${item.run_id}`}>
              {t(`retention.target.${item.target}`)}: {item.instance_name} /{" "}
              <span dir="ltr">{item.file_name ?? item.database_name}</span>
              {item.finished_at && ` · ${formatDateTime(item.finished_at, i18n.language)}`}
            </List.Item>
          ))}
        </List>
      )}
      {report.errors.length > 0 && (
        <Alert color="red" title={t("retention.errorsTitle")}>
          <List size="sm">
            {report.errors.map((item) => (
              <List.Item key={`e-${item.target}-${item.run_id}`}>
                {item.instance_name} / <span dir="ltr">{item.file_name}</span>:{" "}
                {t(`errors.${item.error_code}`, { defaultValue: item.error_code ?? "" })}
              </List.Item>
            ))}
          </List>
        </Alert>
      )}
    </Stack>
  );
}

/** Global retention policy with a preview-then-apply action. */
export function RetentionSettings() {
  const { t, i18n } = useTranslation();
  const retention = useRetention();
  const save = useSaveRetention();
  const apply = useApplyRetention();
  const [values, setValues] = useState<RetentionPolicy>(EMPTY_POLICY);
  const [preview, setPreview] = useState<RetentionReport | null>(null);

  useEffect(() => {
    if (retention.data) setValues(retention.data);
  }, [retention.data]);

  if (retention.isPending) return <Loader size="sm" />;
  if (retention.isError) return <Alert color="red">{errorMessage(t, retention.error)}</Alert>;

  const runApply = (dryRun: boolean) =>
    apply.mutate(dryRun, {
      onSuccess: (report) => {
        if (dryRun) {
          setPreview(report);
          return;
        }
        setPreview(null);
        notifications.show({
          color: report.errors.length ? "orange" : "green",
          message: t("retention.applied", {
            deleted: formatNumber(report.deleted.length, i18n.language),
            errors: formatNumber(report.errors.length, i18n.language),
          }),
        });
      },
      onError: (error) => notifications.show({ color: "red", message: errorMessage(t, error) }),
    });

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        {t("retention.hint")}
      </Text>
      <RetentionFields value={values} onChange={setValues} />
      {save.isError && <Alert color="red">{errorMessage(t, save.error)}</Alert>}
      <Group justify="space-between">
        <Button variant="default" loading={apply.isPending} onClick={() => runApply(true)}>
          {t("retention.preview")}
        </Button>
        <Button
          loading={save.isPending}
          onClick={() =>
            save.mutate(values, {
              onSuccess: () => notifications.show({ color: "green", message: t("settings.saved") }),
            })
          }
        >
          {t("common.save")}
        </Button>
      </Group>

      <Modal
        opened={preview !== null}
        onClose={() => setPreview(null)}
        title={t("retention.previewTitle")}
        size="lg"
      >
        {preview && (
          <Stack gap="md">
            <Text size="sm" c="dimmed">
              {t("retention.previewHint")}
            </Text>
            <ReportList report={preview} />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setPreview(null)}>
                {t("common.cancel")}
              </Button>
              <Button
                color="red"
                disabled={preview.deleted.length === 0}
                loading={apply.isPending}
                onClick={() => runApply(false)}
              >
                {t("retention.applyNow")}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Stack>
  );
}
