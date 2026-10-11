import {
  Alert,
  Button,
  Checkbox,
  Code,
  Group,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type BackupOverrides,
  type BackupSettings,
  type Compression,
  previewPattern,
} from "../api/backups";
import { ApiError, errorMessage } from "../api/client";

const PLACEHOLDERS = [
  "{instance}",
  "{database}",
  "{date}",
  "{time}",
  "{datetime}",
  "{server_type}",
];
const COMPRESSIONS: Compression[] = ["gzip", "bzip2", "none"];
type Field = keyof BackupSettings;
const FIELDS: Field[] = ["storage_dir", "name_pattern", "compression"];

interface BackupSettingsFormProps {
  /** "instance" adds per-field override toggles; unchecked fields inherit `inherited`. */
  mode: "global" | "instance";
  initial: BackupSettings;
  inherited?: BackupSettings;
  initialOverridden?: Record<Field, boolean>;
  saving: boolean;
  error: unknown;
  onSave: (value: BackupSettings | BackupOverrides) => void;
}

export function BackupSettingsForm(props: BackupSettingsFormProps) {
  const { t } = useTranslation();
  const { mode, inherited } = props;
  const [values, setValues] = useState<BackupSettings>(props.initial);
  const [overridden, setOverridden] = useState<Record<Field, boolean>>(
    props.initialOverridden ?? { storage_dir: true, name_pattern: true, compression: true },
  );
  const [preview, setPreview] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const effective: BackupSettings =
    mode === "instance" && inherited
      ? {
          storage_dir: overridden.storage_dir ? values.storage_dir : inherited.storage_dir,
          name_pattern: overridden.name_pattern ? values.name_pattern : inherited.name_pattern,
          compression: overridden.compression ? values.compression : inherited.compression,
        }
      : values;
  const [debounced] = useDebouncedValue(effective, 300);

  useEffect(() => {
    let cancelled = false;
    previewPattern(debounced)
      .then((result) => {
        if (cancelled) return;
        setPreview(result.path);
        setPreviewError(null);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setPreview(null);
        setPreviewError(fieldMessage(error) ?? errorMessage(t, error));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced.storage_dir, debounced.name_pattern, debounced.compression]);

  function fieldMessage(error: unknown, field?: Field): string | null {
    if (!(error instanceof ApiError) || !error.fields) return null;
    const entries = Object.entries(error.fields).filter(([key]) => !field || key === field);
    if (entries.length === 0) return null;
    return entries
      .map(([, code]) =>
        t(`settings.validation.${code}`, { defaultValue: t("validation.invalid") }),
      )
      .join(" ");
  }

  const set = (field: Field, value: string) => setValues((prev) => ({ ...prev, [field]: value }));

  const submit = () => {
    if (mode === "global") {
      props.onSave(values);
      return;
    }
    const body: BackupOverrides = { storage_dir: null, name_pattern: null, compression: null };
    for (const field of FIELDS) {
      if (overridden[field]) (body as Record<Field, string | null>)[field] = values[field];
    }
    props.onSave(body);
  };

  const overrideToggle = (field: Field, inheritedValue: string) =>
    mode === "instance" && (
      <Checkbox
        size="xs"
        label={t("settings.override")}
        description={
          overridden[field]
            ? undefined
            : t("settings.inherit", { value: inheritedValue || t("settings.root") })
        }
        checked={overridden[field]}
        onChange={(e) => {
          const checked = e.currentTarget.checked;
          setOverridden((prev) => ({ ...prev, [field]: checked }));
        }}
      />
    );

  const disabled = (field: Field) => mode === "instance" && !overridden[field];

  return (
    <Stack gap="md">
      {mode === "instance" && (
        <Text size="sm" c="dimmed">
          {t("settings.instanceHint")}
        </Text>
      )}

      <Stack gap={4}>
        {overrideToggle("storage_dir", inherited?.storage_dir ?? "")}
        <TextInput
          label={t("settings.storageDir")}
          description={t("settings.storageDirHelp")}
          dir="ltr"
          value={disabled("storage_dir") ? (inherited?.storage_dir ?? "") : values.storage_dir}
          disabled={disabled("storage_dir")}
          onChange={(e) => set("storage_dir", e.currentTarget.value)}
          error={fieldMessage(props.error, "storage_dir")}
        />
      </Stack>

      <Stack gap={4}>
        {overrideToggle("name_pattern", inherited?.name_pattern ?? "")}
        <TextInput
          label={t("settings.namePattern")}
          description={t("settings.namePatternHelp")}
          dir="ltr"
          value={disabled("name_pattern") ? (inherited?.name_pattern ?? "") : values.name_pattern}
          disabled={disabled("name_pattern")}
          onChange={(e) => set("name_pattern", e.currentTarget.value)}
          error={fieldMessage(props.error, "name_pattern")}
        />
        {!disabled("name_pattern") && (
          <Group gap={4} dir="ltr">
            {PLACEHOLDERS.map((placeholder) => (
              <Button
                key={placeholder}
                size="compact-xs"
                variant="default"
                onClick={() => set("name_pattern", values.name_pattern + placeholder)}
              >
                {placeholder}
              </Button>
            ))}
          </Group>
        )}
      </Stack>

      <Stack gap={4}>
        {overrideToggle(
          "compression",
          inherited ? t(`backups.compression.${inherited.compression}`) : "",
        )}
        <Text size="sm" fw={500}>
          {t("settings.compression")}
        </Text>
        <SegmentedControl
          value={disabled("compression") ? (inherited?.compression ?? "gzip") : values.compression}
          disabled={disabled("compression")}
          onChange={(value) => set("compression", value)}
          data={COMPRESSIONS.map((c) => ({ value: c, label: t(`backups.compression.${c}`) }))}
        />
      </Stack>

      <Stack gap={2}>
        <Text size="sm" fw={500}>
          {t("settings.preview")}
        </Text>
        {preview && (
          <Code dir="ltr" data-testid="pattern-preview">
            {preview}
          </Code>
        )}
        {previewError && (
          <Text size="sm" c="red">
            {previewError}
          </Text>
        )}
      </Stack>

      {Boolean(props.error) && !fieldMessage(props.error) && (
        <Alert color="red">{errorMessage(t, props.error)}</Alert>
      )}

      <Group justify="flex-end">
        <Button loading={props.saving} onClick={submit}>
          {t("common.save")}
        </Button>
      </Group>
    </Stack>
  );
}
