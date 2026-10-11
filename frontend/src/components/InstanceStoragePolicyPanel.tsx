import {
  Alert,
  Button,
  Checkbox,
  Group,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { errorMessage } from "../api/client";
import {
  type InstanceStoragePolicy,
  type RemoteUpload,
  useInstanceStoragePolicy,
  useSaveInstanceStoragePolicy,
} from "../api/storage";
import { RetentionFields, policySummary } from "./RetentionFields";

function Editor({
  instanceId,
  policy,
  onDone,
}: {
  instanceId: number;
  policy: InstanceStoragePolicy;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const save = useSaveInstanceStoragePolicy(instanceId);
  const [upload, setUpload] = useState<RemoteUpload>(policy.remote_upload);
  const [override, setOverride] = useState(policy.retention_override);
  const [retention, setRetention] = useState(
    policy.retention_override ? policy.retention : policy.effective_retention,
  );

  return (
    <Stack gap="md">
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          {t("policy.remoteUpload")}
        </Text>
        <SegmentedControl
          value={upload}
          onChange={(value) => setUpload(value as RemoteUpload)}
          data={(["inherit", "enabled", "disabled"] as const).map((value) => ({
            value,
            label: t(`policy.upload.${value}`),
          }))}
        />
      </Stack>
      <Checkbox
        label={t("policy.overrideRetention")}
        description={override ? undefined : t("policy.inheritRetention")}
        checked={override}
        onChange={(e) => setOverride(e.currentTarget.checked)}
      />
      <RetentionFields value={retention} onChange={setRetention} disabled={!override} />
      {save.isError && <Alert color="red">{errorMessage(t, save.error)}</Alert>}
      <Group justify="flex-end">
        <Button variant="default" onClick={onDone}>
          {t("common.cancel")}
        </Button>
        <Button
          loading={save.isPending}
          onClick={() =>
            save.mutate(
              { remote_upload: upload, retention_override: override, retention },
              {
                onSuccess: () => {
                  notifications.show({ color: "green", message: t("settings.saved") });
                  onDone();
                },
              },
            )
          }
        >
          {t("common.save")}
        </Button>
      </Group>
    </Stack>
  );
}

/** Remote upload and retention for one instance (inherit or override). */
export function InstanceStoragePolicyPanel({ instanceId }: { instanceId: number }) {
  const { t, i18n } = useTranslation();
  const policy = useInstanceStoragePolicy(instanceId);
  const [editing, setEditing] = useState(false);
  if (!policy.data) return null;
  const data = policy.data;
  const eff = data.effective_retention;

  return (
    <Paper withBorder p="lg">
      <Group justify="space-between" mb="sm">
        <Title order={4}>{t("policy.title")}</Title>
        {!editing && (
          <Button size="xs" variant="default" onClick={() => setEditing(true)}>
            {t("settings.edit")}
          </Button>
        )}
      </Group>
      {editing ? (
        <Editor instanceId={instanceId} policy={data} onDone={() => setEditing(false)} />
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              {t("policy.remoteUpload")}
            </Text>
            <Text size="sm">
              {data.effective_upload ? t("policy.uploadOn") : t("policy.uploadOff")}
              {data.remote_upload === "inherit" && ` (${t("policy.upload.inherit")})`}
            </Text>
          </Stack>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              {t("retention.local")}
            </Text>
            <Text size="sm">
              {policySummary(t, i18n.language, eff.local_keep_last, eff.local_max_age_days)}
            </Text>
          </Stack>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              {t("retention.remote")}
            </Text>
            <Text size="sm">
              {policySummary(t, i18n.language, eff.remote_keep_last, eff.remote_max_age_days)}
            </Text>
          </Stack>
        </SimpleGrid>
      )}
    </Paper>
  );
}
