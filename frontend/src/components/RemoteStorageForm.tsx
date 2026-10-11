import {
  Alert,
  Button,
  Checkbox,
  Group,
  Loader,
  PasswordInput,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, errorMessage } from "../api/client";
import {
  type RemoteStorageInput,
  type RemoteTestResult,
  useRemoteStorage,
  useSaveRemoteStorage,
  useTestRemoteStorage,
} from "../api/storage";

const EMPTY: RemoteStorageInput = {
  enabled: false,
  endpoint_url: "",
  region: "",
  bucket: "",
  prefix: "",
  access_key_id: "",
  secret_access_key: "",
  force_path_style: true,
};

/** S3-compatible remote storage settings. The secret is write-only. */
export function RemoteStorageForm() {
  const { t } = useTranslation();
  const remote = useRemoteStorage();
  const save = useSaveRemoteStorage();
  const test = useTestRemoteStorage();
  const [values, setValues] = useState<RemoteStorageInput>(EMPTY);
  const [result, setResult] = useState<RemoteTestResult | null>(null);

  useEffect(() => {
    if (!remote.data) return;
    const data = remote.data;
    setValues({
      enabled: data.enabled,
      endpoint_url: data.endpoint_url,
      region: data.region,
      bucket: data.bucket,
      prefix: data.prefix,
      access_key_id: data.access_key_id,
      secret_access_key: "",
      force_path_style: data.force_path_style,
    });
  }, [remote.data]);

  if (remote.isPending) return <Loader size="sm" />;
  if (remote.isError) return <Alert color="red">{errorMessage(t, remote.error)}</Alert>;
  const hasSecret = remote.data.has_secret;

  const set = <K extends keyof RemoteStorageInput>(key: K, value: RemoteStorageInput[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  const fieldError = (field: keyof RemoteStorageInput) => {
    const error = save.error ?? test.error;
    if (!(error instanceof ApiError) || !error.fields?.[field]) return null;
    return t(`remote.validation.${error.fields[field]}`, { defaultValue: t("validation.invalid") });
  };

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        {t("remote.hint")}
      </Text>
      <Switch
        label={t("remote.enabled")}
        description={t("remote.enabledHelp")}
        checked={values.enabled}
        onChange={(e) => set("enabled", e.currentTarget.checked)}
      />
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <TextInput
          label={t("remote.endpoint")}
          description={t("remote.endpointHelp")}
          placeholder={t("remote.endpointPlaceholder")}
          dir="ltr"
          value={values.endpoint_url}
          onChange={(e) => set("endpoint_url", e.currentTarget.value)}
          error={fieldError("endpoint_url")}
        />
        <TextInput
          label={t("remote.region")}
          placeholder={t("remote.regionPlaceholder")}
          dir="ltr"
          value={values.region}
          onChange={(e) => set("region", e.currentTarget.value)}
        />
        <TextInput
          label={t("remote.bucket")}
          dir="ltr"
          value={values.bucket}
          onChange={(e) => set("bucket", e.currentTarget.value)}
          error={fieldError("bucket")}
        />
        <TextInput
          label={t("remote.prefix")}
          description={t("remote.prefixHelp")}
          dir="ltr"
          value={values.prefix}
          onChange={(e) => set("prefix", e.currentTarget.value)}
          error={fieldError("prefix")}
        />
        <TextInput
          label={t("remote.accessKey")}
          dir="ltr"
          autoComplete="off"
          value={values.access_key_id}
          onChange={(e) => set("access_key_id", e.currentTarget.value)}
          error={fieldError("access_key_id")}
        />
        <PasswordInput
          label={t("remote.secretKey")}
          description={hasSecret ? t("remote.secretStored") : undefined}
          dir="ltr"
          autoComplete="new-password"
          value={values.secret_access_key}
          onChange={(e) => set("secret_access_key", e.currentTarget.value)}
          error={fieldError("secret_access_key")}
        />
      </SimpleGrid>
      <Checkbox
        label={t("remote.pathStyle")}
        description={t("remote.pathStyleHelp")}
        checked={values.force_path_style}
        onChange={(e) => set("force_path_style", e.currentTarget.checked)}
      />

      {result && (
        <Alert
          color={result.ok ? "green" : "red"}
          title={result.ok ? t("remote.testOk") : t("remote.testFailed")}
          data-testid="remote-test-result"
        >
          {!result.ok && (
            <Stack gap={4}>
              <Text size="sm">
                {t(`errors.${result.error_code}`, { defaultValue: t("errors.remote_error") })}
              </Text>
              {result.error_detail && (
                <Text size="xs" dir="ltr">
                  {result.error_detail}
                </Text>
              )}
            </Stack>
          )}
        </Alert>
      )}
      {Boolean(save.error) && !(save.error instanceof ApiError && save.error.fields) && (
        <Alert color="red">{errorMessage(t, save.error)}</Alert>
      )}

      <Group justify="space-between">
        <Button
          variant="default"
          loading={test.isPending}
          onClick={() =>
            test.mutate(values, {
              onSuccess: setResult,
              onError: () => setResult(null),
            })
          }
        >
          {t("remote.test")}
        </Button>
        <Button
          loading={save.isPending}
          onClick={() =>
            save.mutate(values, {
              onSuccess: () => {
                notifications.show({ color: "green", message: t("settings.saved") });
                set("secret_access_key", "");
              },
            })
          }
        >
          {t("common.save")}
        </Button>
      </Group>
    </Stack>
  );
}
