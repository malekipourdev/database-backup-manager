import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Menu,
  Modal,
  NumberInput,
  Paper,
  PasswordInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  TagsInput,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  API_BASE,
  type ApiArea,
  type ApiKey,
  type ApiKeySecret,
  type Level,
  levelOf,
  useApiCatalog,
  useApiKeys,
  useKeyMutations,
  withLevel,
} from "../api/apiAccess";
import { ApiError, errorMessage } from "../api/client";
import { formatDateTime, formatNumber } from "../i18n";
import { CodeBlock, CopyIcon, SecretModal } from "./ApiShared";
import { ConfirmDialog } from "./ConfirmDialog";
import { ArrowClockwise, Key, List, Lock, PencilSimple, Play, Plus, Stop, Trash } from "./Icons";

export const DOWNLOAD = "backups:download";
type Preset = "full" | "read" | "custom";
type Expiry = "keep" | "never" | "30" | "90" | "365" | "date";

function presetOf(scopes: string[], areas: ApiArea[]): Preset {
  if (scopes.includes("*")) return "full";
  const read = areas.map((a) => `${a.area}:read`);
  if (scopes.length === read.length && read.every((s) => scopes.includes(s))) return "read";
  return "custom";
}

function scopesFor(preset: Preset, areas: ApiArea[], custom: string[]): string[] {
  if (preset === "full") return ["*"];
  if (preset === "read") return areas.map((a) => `${a.area}:read`);
  return custom;
}

/** Each area with none / read / read and write, and the backup download on its own. */
export function ScopeMatrix(props: {
  areas: ApiArea[];
  value: string[];
  onChange: (scopes: string[]) => void;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  return (
    <Paper withBorder radius="md" style={{ overflow: "hidden" }}>
      {props.areas.map((area, index) => {
        const level = levelOf(props.value, area.area);
        return (
          <Group
            key={area.area}
            justify="space-between"
            wrap="wrap"
            gap="xs"
            px="md"
            py={10}
            style={{
              borderTop: index ? "1px solid var(--color-neutral-800)" : undefined,
              background:
                level === "none"
                  ? undefined
                  : `color-mix(in srgb, var(--mantine-color-${level === "write" ? "orange" : "blue"}-9) 14%, transparent)`,
            }}
            data-testid={`scope-${area.area}`}
          >
            <div style={{ minWidth: 0, flex: "1 1 220px" }}>
              <Text size="sm" fw={600}>
                {t(`api.areas.${area.area}.label`)}
              </Text>
              <Text size="xs" c="dimmed">
                {t(`api.areas.${area.area}.hint`)}
                {" · "}
                {t("api.scopes.counts", {
                  read: formatNumber(area.read, lang),
                  write: formatNumber(area.write, lang),
                })}
              </Text>
              {area.area === "backups" && (
                <Checkbox
                  mt={6}
                  size="xs"
                  label={t("api.scopes.download")}
                  checked={props.value.includes(DOWNLOAD)}
                  onChange={(e) =>
                    props.onChange(
                      e.currentTarget.checked
                        ? [...props.value, DOWNLOAD]
                        : props.value.filter((s) => s !== DOWNLOAD),
                    )
                  }
                />
              )}
            </div>
            <SegmentedControl
              size="xs"
              value={level}
              onChange={(v) => props.onChange(withLevel(props.value, area.area, v as Level))}
              aria-label={t(`api.areas.${area.area}.label`)}
              data={[
                { value: "none", label: t("api.scopes.none") },
                { value: "read", label: t("api.scopes.read") },
                { value: "write", label: t("api.scopes.write") },
              ]}
            />
          </Group>
        );
      })}
    </Paper>
  );
}

/** What a key may do, in a few words. */
export function ScopeSummary({ scopes, areas }: { scopes: string[]; areas: ApiArea[] }) {
  const { t, i18n } = useTranslation();
  const preset = presetOf(scopes, areas);
  if (preset === "full") {
    return (
      <Badge color="orange" variant="light">
        {t("api.presets.full")}
      </Badge>
    );
  }
  if (preset === "read") {
    return (
      <Badge color="blue" variant="light">
        {t("api.presets.read")}
      </Badge>
    );
  }
  const shown = areas.filter((a) => levelOf(scopes, a.area) !== "none");
  return (
    <Group gap={4}>
      {shown.slice(0, 4).map((a) => (
        <Badge
          key={a.area}
          color={levelOf(scopes, a.area) === "write" ? "orange" : "blue"}
          variant="light"
          size="sm"
        >
          {t(`api.areas.${a.area}.label`)}
        </Badge>
      ))}
      {shown.length > 4 && (
        <Badge color="gray" variant="light" size="sm">
          {t("api.scopes.more", { n: formatNumber(shown.length - 4, i18n.language) })}
        </Badge>
      )}
      {scopes.includes(DOWNLOAD) && (
        <Badge color="red" variant="light" size="sm">
          {t("api.scopes.downloadShort")}
        </Badge>
      )}
    </Group>
  );
}

function expiryDate(expiry: Expiry, date: string): string | null | undefined {
  if (expiry === "keep") return undefined;
  if (expiry === "never") return null;
  if (expiry === "date") return date ? new Date(`${date}T23:59:59`).toISOString() : null;
  return new Date(Date.now() + Number(expiry) * 86_400_000).toISOString();
}

function fieldError(t: (k: string) => string, error: unknown, field: string): string | null {
  if (!(error instanceof ApiError) || !error.fields?.[field]) return null;
  return t(`api.validation.${error.fields[field]}`);
}

/** New key, or a key's settings (no password: the secret does not change). */
function KeyModal(props: {
  opened: boolean;
  editing: ApiKey | null;
  areas: ApiArea[];
  onClose: () => void;
  onCreated: (secret: ApiKeySecret) => void;
}) {
  const { t, i18n } = useTranslation();
  const { create, update } = useKeyMutations();
  const editing = props.editing;
  const [name, setName] = useState(editing?.name ?? "");
  const [preset, setPreset] = useState<Preset>(
    editing ? presetOf(editing.scopes, props.areas) : "read",
  );
  const [custom, setCustom] = useState<string[]>(
    editing && !editing.scopes.includes("*") ? editing.scopes : [],
  );
  const [ips, setIps] = useState<string[]>(editing?.allowed_ips ?? []);
  const [rate, setRate] = useState<number>(editing?.rate_limit ?? 600);
  const [expiry, setExpiry] = useState<Expiry>(editing ? "keep" : "never");
  const [date, setDate] = useState("");
  const [password, setPassword] = useState("");
  const mutation = editing ? update : create;
  const scopes = scopesFor(preset, props.areas, custom);
  const download = scopes.includes(DOWNLOAD);

  const submit = () => {
    const expires = expiryDate(expiry, date);
    const fields = {
      name: name.trim(),
      scopes,
      allowed_ips: ips,
      rate_limit: rate,
      ...(expires === undefined ? {} : { expires_at: expires }),
    };
    if (editing) {
      update.mutate(
        { id: editing.id, ...fields },
        {
          onSuccess: () => {
            notifications.show({ color: "green", message: t("api.keys.saved") });
            props.onClose();
          },
        },
      );
    } else {
      create.mutate(
        { ...fields, expires_at: expires ?? null, password },
        { onSuccess: (data) => props.onCreated(data) },
      );
    }
  };

  const error = mutation.error;
  const valid =
    name.trim() && scopes.length > 0 && (editing || password) && !(expiry === "date" && !date);
  return (
    <Modal
      opened={props.opened}
      onClose={props.onClose}
      size="xl"
      title={editing ? t("api.keys.editTitle", { name: editing.name }) : t("api.keys.newTitle")}
    >
      <Stack gap="md">
        <TextInput
          label={t("api.keys.name")}
          description={t("api.keys.nameHint")}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          maxLength={80}
          data-autofocus
          required
        />
        <div>
          <Text size="sm" fw={500} mb={6}>
            {t("api.keys.access")}
          </Text>
          <SegmentedControl
            fullWidth
            value={preset}
            onChange={(v) => {
              if (v === "custom" && preset !== "custom") setCustom(scopes.filter((s) => s !== "*"));
              setPreset(v as Preset);
            }}
            data={[
              { value: "read", label: t("api.presets.read") },
              { value: "custom", label: t("api.presets.custom") },
              { value: "full", label: t("api.presets.full") },
            ]}
          />
          <Text size="xs" c="dimmed" mt={6}>
            {t(`api.presets.${preset}Hint`)}
          </Text>
        </div>
        {preset === "custom" && (
          <ScopeMatrix areas={props.areas} value={custom} onChange={setCustom} />
        )}
        {preset === "full" && (
          <Alert color="orange" variant="light" icon={<Lock size={18} />}>
            {t("api.presets.fullWarning")}
          </Alert>
        )}
        {download && (
          <Alert color="red" variant="light">
            {t("api.scopes.downloadWarning")}
          </Alert>
        )}
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TagsInput
            label={t("api.keys.ips")}
            description={t("api.keys.ipsHint")}
            placeholder={t("api.keys.ipsPlaceholder")}
            value={ips}
            onChange={setIps}
            error={fieldError(t, error, "allowed_ips")}
            styles={{ input: { direction: "ltr" } }}
            clearable
          />
          <NumberInput
            label={t("api.keys.rate")}
            description={t("api.keys.rateHint")}
            value={rate}
            onChange={(v) => setRate(typeof v === "number" ? v : 0)}
            min={0}
            max={100000}
            step={60}
            thousandSeparator
          />
        </SimpleGrid>
        <Group grow align="flex-start">
          <Select
            label={t("api.keys.expiry")}
            value={expiry}
            onChange={(v) => setExpiry((v as Expiry) ?? "never")}
            allowDeselect={false}
            data={[
              ...(editing
                ? [
                    {
                      value: "keep",
                      label: editing.expires_at
                        ? t("api.keys.expiryKeepDate", {
                            date: formatDateTime(editing.expires_at, i18n.language),
                          })
                        : t("api.keys.expiryKeepNever"),
                    },
                  ]
                : []),
              { value: "never", label: t("api.keys.expiryNever") },
              { value: "30", label: t("api.keys.expiryDays", { n: 30 }) },
              { value: "90", label: t("api.keys.expiryDays", { n: 90 }) },
              { value: "365", label: t("api.keys.expiryYear") },
              { value: "date", label: t("api.keys.expiryDate") },
            ]}
          />
          {expiry === "date" && (
            <TextInput
              type="date"
              label={t("api.keys.expiryOn")}
              value={date}
              onChange={(e) => setDate(e.currentTarget.value)}
              dir="ltr"
            />
          )}
        </Group>
        {!editing && (
          <PasswordInput
            label={t("api.keys.password")}
            description={t("api.keys.passwordHint")}
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            error={fieldError(t, error, "password")}
            autoComplete="current-password"
            required
          />
        )}
        {error && !(error instanceof ApiError && error.fields) && (
          <Alert color="red">{errorMessage(t, error)}</Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={submit} loading={mutation.isPending} disabled={!valid}>
            {editing ? t("common.save") : t("api.keys.create")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function RotateModal(props: {
  apiKey: ApiKey | null;
  onClose: () => void;
  onRotated: (s: ApiKeySecret) => void;
}) {
  const { t } = useTranslation();
  const { rotate } = useKeyMutations();
  const [password, setPassword] = useState("");
  const key = props.apiKey;
  return (
    <Modal
      opened={key !== null}
      onClose={props.onClose}
      title={t("api.keys.rotateTitle", { name: key?.name ?? "" })}
      centered
    >
      <Stack>
        <Text size="sm">{t("api.keys.rotateBody")}</Text>
        <PasswordInput
          label={t("api.keys.password")}
          value={password}
          onChange={(e) => setPassword(e.currentTarget.value)}
          error={fieldError(t, rotate.error, "password")}
          autoComplete="current-password"
          data-autofocus
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            color="orange"
            disabled={!password}
            loading={rotate.isPending}
            onClick={() =>
              key &&
              rotate.mutate(
                { id: key.id, password },
                {
                  onSuccess: (data) => {
                    setPassword("");
                    props.onRotated(data);
                  },
                },
              )
            }
          >
            {t("api.keys.rotate")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function KeyStatus({ apiKey }: { apiKey: ApiKey }) {
  const { t } = useTranslation();
  if (!apiKey.enabled) {
    return (
      <Badge color="gray" variant="light">
        {t("api.keys.status.disabled")}
      </Badge>
    );
  }
  if (apiKey.expired) {
    return (
      <Badge color="red" variant="light">
        {t("api.keys.status.expired")}
      </Badge>
    );
  }
  return (
    <Badge color="green" variant="light">
      {t("api.keys.status.active")}
    </Badge>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ minWidth: 0 }}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm" component="div" style={{ overflowWrap: "anywhere" }}>
        {children}
      </Text>
    </div>
  );
}

function KeyCard(props: {
  apiKey: ApiKey;
  areas: ApiArea[];
  onEdit: () => void;
  onRotate: () => void;
  onDelete: () => void;
  onLog: () => void;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const { update } = useKeyMutations();
  const key = props.apiKey;
  const n = (v: number) => formatNumber(v, lang);
  return (
    <Paper
      withBorder
      p="md"
      radius="md"
      data-testid={`api-key-${key.id}`}
      style={{ opacity: key.enabled ? 1 : 0.7 }}
    >
      <Group justify="space-between" wrap="nowrap" align="flex-start" mb="sm">
        <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
          <span
            className="cl-icon-tile"
            style={{
              color: "var(--mantine-color-yellow-4)",
              background: "color-mix(in srgb, var(--mantine-color-yellow-9) 30%, transparent)",
            }}
          >
            <Key size={20} />
          </span>
          <div style={{ minWidth: 0 }}>
            <Group gap={8}>
              <Text fw={600} truncate>
                {key.name}
              </Text>
              <KeyStatus apiKey={key} />
            </Group>
            <Group gap={4} wrap="nowrap">
              <Text size="sm" c="dimmed" ff="var(--font-mono)" dir="ltr">
                {`${key.prefix}…`}
              </Text>
              <CopyIcon value={key.prefix} />
            </Group>
          </div>
        </Group>
        <Group gap={4} wrap="nowrap">
          <Tooltip label={t("common.edit")} withArrow>
            <ActionIcon
              variant="subtle"
              color="gray"
              onClick={props.onEdit}
              aria-label={t("common.edit")}
            >
              <PencilSimple size={18} />
            </ActionIcon>
          </Tooltip>
          <Menu position="bottom-end" withinPortal>
            <Menu.Target>
              <ActionIcon variant="subtle" color="gray" aria-label={t("api.keys.more")}>
                <List size={18} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item leftSection={<List size={16} />} onClick={props.onLog}>
                {t("api.keys.viewLog")}
              </Menu.Item>
              <Menu.Item leftSection={<ArrowClockwise size={16} />} onClick={props.onRotate}>
                {t("api.keys.rotate")}
              </Menu.Item>
              <Menu.Item
                leftSection={key.enabled ? <Stop size={16} /> : <Play size={16} />}
                onClick={() => update.mutate({ id: key.id, enabled: !key.enabled })}
              >
                {key.enabled ? t("api.keys.disable") : t("api.keys.enable")}
              </Menu.Item>
              <Menu.Divider />
              <Menu.Item color="red" leftSection={<Trash size={16} />} onClick={props.onDelete}>
                {t("common.delete")}
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      </Group>
      <Stack gap="sm">
        <ScopeSummary scopes={key.scopes} areas={props.areas} />
        <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }} spacing="sm">
          <Fact label={t("api.keys.lastUsed")}>
            {key.last_used_at ? formatDateTime(key.last_used_at, lang) : t("api.keys.never")}
          </Fact>
          <Fact label={t("api.keys.lastIp")}>
            <span dir="ltr">{key.last_used_ip ?? t("common.notAvailable")}</span>
          </Fact>
          <Fact label={t("api.keys.requests24h")}>
            {n(key.requests_24h)}
            {key.errors_24h > 0 && (
              <Text span size="sm" c="orange.4">
                {` · ${t("api.keys.errorsN", { n: n(key.errors_24h) })}`}
              </Text>
            )}
          </Fact>
          <Fact label={t("api.keys.rate")}>
            {key.rate_limit
              ? t("api.keys.perMinute", { n: n(key.rate_limit) })
              : t("api.keys.unlimited")}
          </Fact>
          <Fact label={t("api.keys.ips")}>
            <span dir="ltr">
              {key.allowed_ips.length ? key.allowed_ips.join(", ") : t("api.keys.anywhere")}
            </span>
          </Fact>
          <Fact label={t("api.keys.expiry")}>
            {key.expires_at ? formatDateTime(key.expires_at, lang) : t("api.keys.expiryNever")}
          </Fact>
        </SimpleGrid>
      </Stack>
    </Paper>
  );
}

/** The quick test shown with a new key. */
export function curlExample(secret: string, path = "/me"): string {
  return `curl -H "Authorization: Bearer ${secret}" \\\n  ${window.location.origin}${API_BASE}${path}`;
}

export function KeysTab({ onShowLog }: { onShowLog: (keyId: number) => void }) {
  const { t } = useTranslation();
  const keys = useApiKeys();
  const catalog = useApiCatalog();
  const { remove } = useKeyMutations();
  const [modal, setModal] = useState<{ editing: ApiKey | null } | null>(null);
  const [secret, setSecret] = useState<ApiKeySecret | null>(null);
  const [rotating, setRotating] = useState<ApiKey | null>(null);
  const [deleting, setDeleting] = useState<ApiKey | null>(null);
  const areas = catalog.data?.areas ?? [];

  if (keys.isError) return <Alert color="red">{errorMessage(t, keys.error)}</Alert>;
  const list = keys.data ?? [];
  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text size="sm" c="dimmed" maw={640}>
          {t("api.keys.hint")}
        </Text>
        <Button
          leftSection={<Plus size={16} />}
          onClick={() => setModal({ editing: null })}
          disabled={!catalog.data}
        >
          {t("api.keys.new")}
        </Button>
      </Group>
      {keys.isSuccess && list.length === 0 && (
        <Paper withBorder p="xl" radius="md" data-testid="no-keys">
          <Stack align="center" gap="xs">
            <span className="cl-icon-tile" style={{ color: "var(--mantine-color-yellow-4)" }}>
              <Key size={22} />
            </span>
            <Text fw={500}>{t("api.keys.empty")}</Text>
            <Text size="sm" c="dimmed" ta="center" maw={460}>
              {t("api.keys.emptyHint")}
            </Text>
          </Stack>
        </Paper>
      )}
      {list.map((key) => (
        <KeyCard
          key={key.id}
          apiKey={key}
          areas={areas}
          onEdit={() => setModal({ editing: key })}
          onRotate={() => setRotating(key)}
          onDelete={() => setDeleting(key)}
          onLog={() => onShowLog(key.id)}
        />
      ))}
      {modal && (
        <KeyModal
          opened
          editing={modal.editing}
          areas={areas}
          onClose={() => setModal(null)}
          onCreated={(data) => {
            setModal(null);
            setSecret(data);
          }}
        />
      )}
      <RotateModal
        apiKey={rotating}
        onClose={() => setRotating(null)}
        onRotated={(data) => {
          setRotating(null);
          setSecret(data);
        }}
      />
      <SecretModal
        opened={secret !== null}
        title={t("api.keys.secretTitle", { name: secret?.key.name ?? "" })}
        hint={t("api.keys.secretHint")}
        secret={secret?.secret ?? ""}
        onClose={() => setSecret(null)}
      >
        {secret && <CodeBlock title={t("api.keys.tryIt")} code={curlExample(secret.secret)} />}
      </SecretModal>
      <ConfirmDialog
        opened={deleting !== null}
        title={t("api.keys.deleteTitle", { name: deleting?.name ?? "" })}
        body={t("api.keys.deleteBody")}
        confirmLabel={t("common.delete")}
        loading={remove.isPending}
        onCancel={() => setDeleting(null)}
        onConfirm={() =>
          deleting && remove.mutate(deleting.id, { onSettled: () => setDeleting(null) })
        }
      />
    </Stack>
  );
}
