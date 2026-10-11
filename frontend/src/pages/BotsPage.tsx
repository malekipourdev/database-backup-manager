import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Code,
  Collapse,
  Group,
  List,
  Loader,
  Modal,
  NumberInput,
  Paper,
  PasswordInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type BotAdmin,
  type BotSettings,
  type BotSettingsInput,
  type BotTestResult,
  type LinkCode,
  type NotifyLevel,
  PLATFORMS,
  type Platform,
  useAddBotAdmin,
  useBotAdmins,
  useBots,
  useCreateLinkCode,
  useDeleteBotAdmin,
  useSaveBot,
  useTestBot,
  useUpdateBotAdmin,
} from "../api/bots";
import { ApiError, errorMessage } from "../api/client";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { formatDateTime } from "../i18n";

const LEVELS: NotifyLevel[] = ["info", "warning", "error", "off"];

function toInput(bot: BotSettings): BotSettingsInput {
  return {
    enabled: bot.enabled,
    token: "",
    api_base_url: bot.api_base_url,
    proxy_url: bot.proxy_url,
    allow_file_download: bot.allow_file_download,
    max_file_mb: bot.max_file_mb,
  };
}

function BotStatus({ bot }: { bot: BotSettings }) {
  const { t, i18n } = useTranslation();
  if (bot.running && !bot.last_error) {
    return (
      <Badge color="green" variant="light" tt="none">
        {bot.bot_username
          ? t("bots.connectedAs", { name: `@${bot.bot_username}` })
          : t("bots.connected")}
      </Badge>
    );
  }
  if (bot.running && bot.last_error) {
    return (
      <Tooltip label={bot.last_error} multiline w={320}>
        <Badge color="red" variant="light">
          {t("bots.error")}
          {bot.last_ok_at && ` · ${formatDateTime(bot.last_ok_at, i18n.language)}`}
        </Badge>
      </Tooltip>
    );
  }
  return (
    <Badge color="gray" variant="light">
      {bot.enabled ? t("bots.starting") : t("bots.off")}
    </Badge>
  );
}

function BotCard({ bot }: { bot: BotSettings }) {
  const { t } = useTranslation();
  const save = useSaveBot(bot.platform);
  const test = useTestBot(bot.platform);
  const [values, setValues] = useState<BotSettingsInput>(toInput(bot));
  const [result, setResult] = useState<BotTestResult | null>(null);
  const [advanced, setAdvanced] = useState(Boolean(bot.proxy_url || bot.api_base_url));

  // Server-side fields (status) refresh on their own; only reset the form after a save.
  useEffect(() => {
    if (save.isSuccess) setValues(toInput(bot));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [save.isSuccess]);

  const set = <K extends keyof BotSettingsInput>(key: K, value: BotSettingsInput[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));
  const fieldError = (field: string) => {
    const error = save.error ?? test.error;
    if (!(error instanceof ApiError) || !error.fields?.[field]) return null;
    return t(`bots.validation.${error.fields[field]}`, { defaultValue: t("validation.invalid") });
  };

  return (
    <Paper withBorder p="lg" radius="md">
      <Group justify="space-between" mb="sm">
        <Title order={4}>{t(`bots.platform.${bot.platform}`)}</Title>
        <BotStatus bot={bot} />
      </Group>
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          {t(`bots.howTo.${bot.platform}`)}
        </Text>
        <Switch
          label={t("bots.enabled")}
          checked={values.enabled}
          onChange={(e) => set("enabled", e.currentTarget.checked)}
        />
        <PasswordInput
          label={t("bots.token")}
          description={bot.has_token ? t("bots.tokenStored") : t("bots.tokenHelp")}
          dir="ltr"
          autoComplete="new-password"
          value={values.token}
          onChange={(e) => set("token", e.currentTarget.value)}
          error={fieldError("token")}
        />
        <Switch
          label={t("bots.allowFiles")}
          description={t("bots.allowFilesHelp")}
          checked={values.allow_file_download}
          onChange={(e) => set("allow_file_download", e.currentTarget.checked)}
        />
        {values.allow_file_download && (
          <NumberInput
            label={t("bots.maxFile")}
            min={1}
            max={2000}
            allowDecimal={false}
            value={values.max_file_mb}
            onChange={(v) => set("max_file_mb", Number(v) || 1)}
          />
        )}
        <Anchor component="button" size="sm" onClick={() => setAdvanced((v) => !v)}>
          {t("bots.advanced")}
        </Anchor>
        <Collapse in={advanced}>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label={t("bots.proxy")}
              description={t("bots.proxyHelp")}
              placeholder={t("bots.proxyPlaceholder")}
              dir="ltr"
              value={values.proxy_url}
              onChange={(e) => set("proxy_url", e.currentTarget.value)}
              error={fieldError("proxy_url")}
            />
            <TextInput
              label={t("bots.apiBase")}
              description={t("bots.apiBaseHelp")}
              dir="ltr"
              value={values.api_base_url}
              onChange={(e) => set("api_base_url", e.currentTarget.value)}
              error={fieldError("api_base_url")}
            />
          </SimpleGrid>
        </Collapse>
        {result && (
          <Alert color={result.ok ? "green" : "red"} data-testid={`bot-test-${bot.platform}`}>
            {result.ok
              ? t("bots.testOk", { name: `@${result.username ?? ""}` })
              : `${t(`bots.testErrors.${result.error_code}`, {
                  defaultValue: t("bots.testFailed"),
                })}${result.error_detail ? ` — ${result.error_detail}` : ""}`}
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
              test.mutate(values, { onSuccess: setResult, onError: () => setResult(null) })
            }
          >
            {t("bots.test")}
          </Button>
          <Button
            loading={save.isPending}
            onClick={() =>
              save.mutate(values, {
                onSuccess: () =>
                  notifications.show({ color: "green", message: t("settings.saved") }),
              })
            }
          >
            {t("common.save")}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function AddAdmin() {
  const { t } = useTranslation();
  const add = useAddBotAdmin();
  const [platform, setPlatform] = useState<Platform>("bale");
  const [userId, setUserId] = useState<string | number>("");
  const [name, setName] = useState("");
  const idError =
    add.error instanceof ApiError && add.error.fields?.user_id
      ? t(`bots.validation.${add.error.fields.user_id}`, { defaultValue: t("validation.invalid") })
      : null;
  return (
    <Group align="flex-end" wrap="wrap">
      <Select
        label={t("bots.admins.platform")}
        data={PLATFORMS.map((p) => ({ value: p, label: t(`bots.platform.${p}`) }))}
        value={platform}
        onChange={(v) => v && setPlatform(v as Platform)}
        allowDeselect={false}
        w={140}
      />
      <NumberInput
        label={t("bots.admins.userId")}
        description={t("bots.admins.userIdHelp")}
        dir="ltr"
        allowDecimal={false}
        allowNegative={false}
        hideControls
        value={userId}
        onChange={setUserId}
        error={idError}
        w={200}
      />
      <TextInput
        label={t("bots.admins.name")}
        value={name}
        onChange={(e) => setName(e.currentTarget.value)}
        w={200}
      />
      <Button
        loading={add.isPending}
        disabled={!userId || !name.trim()}
        onClick={() =>
          add.mutate(
            { platform, user_id: Number(userId), display_name: name.trim() },
            {
              onSuccess: () => {
                setUserId("");
                setName("");
                notifications.show({ color: "green", message: t("bots.admins.added") });
              },
            },
          )
        }
      >
        {t("bots.admins.add")}
      </Button>
    </Group>
  );
}

function LinkCodeDialog({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const [platform, setPlatform] = useState<Platform>("bale");
  const [name, setName] = useState("");
  const [code, setCode] = useState<LinkCode | null>(null);
  const create = useCreateLinkCode(platform);
  return (
    <Modal opened onClose={onClose} title={t("bots.link.title")} size="lg">
      {code ? (
        <Stack gap="sm">
          <Text size="sm">{t("bots.link.instructions")}</Text>
          <Code block dir="ltr" fz="xl" ta="center" data-testid="link-code">
            {code.code}
          </Code>
          <List size="sm">
            <List.Item>
              {code.bot_username
                ? t("bots.link.step1Named", { name: `@${code.bot_username}` })
                : t("bots.link.step1")}
            </List.Item>
            <List.Item>{t("bots.link.step2")}</List.Item>
          </List>
          {code.deep_link && (
            <Anchor href={code.deep_link} target="_blank" rel="noreferrer" dir="ltr">
              {code.deep_link}
            </Anchor>
          )}
          <Text size="xs" c="dimmed">
            {t("bots.link.expires", { time: formatDateTime(code.expires_at, i18n.language) })}
          </Text>
          <Group justify="flex-end">
            <Button onClick={onClose}>{t("bots.link.done")}</Button>
          </Group>
        </Stack>
      ) : (
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            {t("bots.link.hint")}
          </Text>
          <Select
            label={t("bots.admins.platform")}
            data={PLATFORMS.map((p) => ({ value: p, label: t(`bots.platform.${p}`) }))}
            value={platform}
            onChange={(v) => v && setPlatform(v as Platform)}
            allowDeselect={false}
          />
          <TextInput
            label={t("bots.admins.name")}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
          />
          {create.isError && <Alert color="red">{errorMessage(t, create.error)}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button
              loading={create.isPending}
              disabled={!name.trim()}
              onClick={() => create.mutate(name.trim(), { onSuccess: setCode })}
            >
              {t("bots.link.create")}
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}

function AdminsTable() {
  const { t, i18n } = useTranslation();
  const admins = useBotAdmins();
  const update = useUpdateBotAdmin();
  const remove = useDeleteBotAdmin();
  const [deleting, setDeleting] = useState<BotAdmin | null>(null);
  const [linking, setLinking] = useState(false);
  const patch = (admin: BotAdmin, body: Partial<BotAdmin>) =>
    update.mutate(
      { id: admin.id, body },
      { onError: (error) => notifications.show({ color: "red", message: errorMessage(t, error) }) },
    );

  return (
    <Paper withBorder p="lg" radius="md">
      <Group justify="space-between" mb="sm">
        <Title order={4}>{t("bots.admins.title")}</Title>
        <Button size="xs" variant="light" onClick={() => setLinking(true)}>
          {t("bots.link.button")}
        </Button>
      </Group>
      <Text size="sm" c="dimmed" mb="md">
        {t("bots.admins.hint")}
      </Text>
      {admins.isPending && <Loader size="sm" />}
      {admins.data && admins.data.length === 0 && (
        <Text size="sm" c="dimmed" mb="md">
          {t("bots.admins.empty")}
        </Text>
      )}
      {admins.data && admins.data.length > 0 && (
        <Table.ScrollContainer minWidth={760}>
          <Table verticalSpacing="xs" mb="md">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("bots.admins.name")}</Table.Th>
                <Table.Th>{t("bots.admins.platform")}</Table.Th>
                <Table.Th>{t("bots.admins.userId")}</Table.Th>
                <Table.Th>{t("bots.admins.level")}</Table.Th>
                <Table.Th>{t("bots.admins.language")}</Table.Th>
                <Table.Th>{t("bots.admins.lastSeen")}</Table.Th>
                <Table.Th>{t("bots.admins.enabled")}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {admins.data.map((admin) => (
                <Table.Tr key={admin.id}>
                  <Table.Td>{admin.display_name}</Table.Td>
                  <Table.Td>{t(`bots.platform.${admin.platform}`)}</Table.Td>
                  <Table.Td dir="ltr">{admin.user_id}</Table.Td>
                  <Table.Td>
                    <Select
                      size="xs"
                      w={170}
                      aria-label={t("bots.admins.level")}
                      data={LEVELS.map((l) => ({ value: l, label: t(`bots.levels.${l}`) }))}
                      value={admin.notify_level}
                      allowDeselect={false}
                      onChange={(v) => v && patch(admin, { notify_level: v as NotifyLevel })}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Select
                      size="xs"
                      w={100}
                      aria-label={t("bots.admins.language")}
                      data={[
                        { value: "fa", label: t("language.fa") },
                        { value: "en", label: t("language.en") },
                      ]}
                      value={admin.language}
                      allowDeselect={false}
                      onChange={(v) => v && patch(admin, { language: v as "fa" | "en" })}
                    />
                  </Table.Td>
                  <Table.Td>
                    {admin.last_seen_at
                      ? formatDateTime(admin.last_seen_at, i18n.language)
                      : t("bots.admins.never")}
                  </Table.Td>
                  <Table.Td>
                    <Switch
                      aria-label={t("bots.admins.enabled")}
                      checked={admin.enabled}
                      onChange={(e) => patch(admin, { enabled: e.currentTarget.checked })}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Tooltip label={t("common.delete")}>
                      <ActionIcon
                        color="red"
                        variant="subtle"
                        aria-label={t("common.delete")}
                        onClick={() => setDeleting(admin)}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                          <path
                            d="M6 6l12 12M18 6L6 18"
                            stroke="currentColor"
                            strokeWidth="2.5"
                            strokeLinecap="round"
                          />
                        </svg>
                      </ActionIcon>
                    </Tooltip>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      <AddAdmin />
      {linking && <LinkCodeDialog onClose={() => setLinking(false)} />}
      <ConfirmDialog
        opened={deleting !== null}
        title={t("bots.admins.deleteTitle")}
        body={deleting ? t("bots.admins.deleteConfirm", { name: deleting.display_name }) : ""}
        confirmLabel={t("common.delete")}
        loading={remove.isPending}
        onConfirm={() =>
          deleting && remove.mutate(deleting.id, { onSettled: () => setDeleting(null) })
        }
        onCancel={() => setDeleting(null)}
      />
    </Paper>
  );
}

export function BotsPage() {
  const { t } = useTranslation();
  const bots = useBots();
  return (
    <Stack gap="md">
      <Title order={2}>{t("bots.title")}</Title>
      <Text c="dimmed" size="sm">
        {t("bots.hint")}
      </Text>
      {bots.isPending && <Loader />}
      {bots.isError && <Alert color="red">{errorMessage(t, bots.error)}</Alert>}
      {bots.data && (
        <SimpleGrid cols={{ base: 1, md: 2 }}>
          {bots.data.map((bot) => (
            <BotCard key={bot.platform} bot={bot} />
          ))}
        </SimpleGrid>
      )}
      <AdminsTable />
    </Stack>
  );
}
