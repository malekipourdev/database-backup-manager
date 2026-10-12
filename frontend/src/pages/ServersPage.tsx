import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Code,
  CopyButton,
  Group,
  List,
  Loader,
  Modal,
  NumberInput,
  Paper,
  Stack,
  Text,
  TextInput,
  Textarea,
  Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ApiError, errorMessage } from "../api/client";
import {
  type Server,
  type ServerInput,
  type ServerSetup,
  useConnectServer,
  useCreateServer,
  useDeleteServer,
  useRotateServerToken,
  useServers,
  useUpdateServer,
} from "../api/servers";
import { ConfirmDialog } from "../components/ConfirmDialog";
import {
  Copy,
  HardDrives,
  Key,
  PencilSimple,
  PlugsConnected,
  Plus,
  Trash,
} from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { formatDateTime, formatNumber } from "../i18n";

const HOST_RE = /^[A-Za-z0-9._:-]+$/;
const DEFAULT_PORT = 8443;

function StatusBadge({ server }: { server: Server }) {
  const { t } = useTranslation();
  if (!server.paired) {
    return (
      <Badge color="gray" variant="light">
        {t("servers.notConnected")}
      </Badge>
    );
  }
  if (server.last_error) {
    return (
      <Badge color="red" variant="light">
        {t("servers.unreachable")}
      </Badge>
    );
  }
  if (!server.last_seen_at) {
    return (
      <Badge color="gray" variant="light">
        {t("servers.unknown")}
      </Badge>
    );
  }
  return (
    <Badge color="teal" variant="light">
      {t("servers.connected")}
    </Badge>
  );
}

function fingerprint(value: string | null): string {
  if (!value) return "—";
  return (value.slice(0, 16).match(/.{2}/g) ?? []).join(":");
}

function ServerCard(props: {
  server: Server;
  onConnect: () => void;
  connecting: boolean;
  onEdit: () => void;
  onToken: () => void;
  onDelete: () => void;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const s = props.server;
  const local = s.kind === "local";
  return (
    <Paper withBorder p="md" data-testid={`server-${s.name}`}>
      <Stack gap="sm">
        <Group gap="sm" wrap="nowrap" align="flex-start">
          <span className="cl-icon-tile">
            <HardDrives size={20} />
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Group gap={6}>
              <Text fw={600}>{s.name}</Text>
              {local && (
                <Badge variant="outline" color="blue">
                  {t("servers.local")}
                </Badge>
              )}
              <StatusBadge server={s} />
            </Group>
            <Text size="xs" c="dimmed" dir="ltr" ta="start">
              {local ? t("servers.localAddress") : `${s.host}:${s.port}`}
            </Text>
          </div>
          <Group gap={4} wrap="nowrap">
            <Tooltip label={t("common.edit")}>
              <ActionIcon variant="subtle" onClick={props.onEdit} aria-label={t("common.edit")}>
                <PencilSimple size={16} />
              </ActionIcon>
            </Tooltip>
            {!local && (
              <>
                <Tooltip label={t("servers.newToken")}>
                  <ActionIcon
                    variant="subtle"
                    onClick={props.onToken}
                    aria-label={t("servers.newToken")}
                  >
                    <Key size={16} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label={t("common.delete")}>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    onClick={props.onDelete}
                    aria-label={t("common.delete")}
                  >
                    <Trash size={16} />
                  </ActionIcon>
                </Tooltip>
              </>
            )}
          </Group>
        </Group>
        {s.last_error && (
          <Text size="sm" c="red.4">
            {t(`errors.${s.last_error}`, { defaultValue: s.last_error })}
          </Text>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="cl-kv">
            <span>{t("servers.hostname")}</span>
            <code dir="ltr">{s.agent_hostname ?? "—"}</code>
          </div>
          <div className="cl-kv">
            <span>{t("servers.docker")}</span>
            <code dir="ltr">{s.docker_version ?? "—"}</code>
          </div>
          {!local && (
            <div className="cl-kv">
              <span>{t("servers.fingerprint")}</span>
              <code dir="ltr">{fingerprint(s.cert_fingerprint)}</code>
            </div>
          )}
          <div className="cl-kv">
            <span>{t("servers.lastSeen")}</span>
            <span>{s.last_seen_at ? formatDateTime(s.last_seen_at, lang) : "—"}</span>
          </div>
          <div className="cl-kv">
            <span>{t("servers.usage")}</span>
            <span>
              {t("servers.usageValue", {
                projects: formatNumber(s.projects, lang),
                databases: formatNumber(s.instances, lang),
              })}
            </span>
          </div>
        </div>
        {s.notes && (
          <Text size="sm" c="dimmed">
            {s.notes}
          </Text>
        )}
        <Group justify="space-between">
          <Button
            size="xs"
            variant="light"
            leftSection={<PlugsConnected size={14} />}
            loading={props.connecting}
            onClick={props.onConnect}
          >
            {s.paired ? t("servers.check") : t("servers.connect")}
          </Button>
          {s.paired && (
            <Button
              size="xs"
              variant="subtle"
              component={Link}
              to={local ? "/containers" : `/containers?server=${s.id}`}
            >
              {t("servers.openContainers")}
            </Button>
          )}
        </Group>
      </Stack>
    </Paper>
  );
}

/** The commands to run on the server, shown once with its token. */
function SetupView({
  setup,
  onConnect,
  connecting,
  error,
}: {
  setup: ServerSetup;
  onConnect: () => void;
  connecting: boolean;
  error: unknown;
}) {
  const { t } = useTranslation();
  const firewall = `sudo ufw allow from <PANEL-IP> to any port ${setup.server.port} proto tcp`;
  return (
    <Stack gap="sm">
      <Alert color="yellow">{t("servers.setup.once")}</Alert>
      <Text size="sm">{t("servers.setup.intro")}</Text>
      <List size="sm" type="ordered" spacing={4}>
        <List.Item>{t("servers.setup.step1")}</List.Item>
        <List.Item>{t("servers.setup.step2")}</List.Item>
        <List.Item>{t("servers.setup.step3", { port: setup.server.port })}</List.Item>
      </List>
      <Stack gap={6}>
        <Group justify="flex-end">
          <CopyButton value={setup.install_command}>
            {({ copied, copy }) => (
              <Button
                size="compact-xs"
                variant="light"
                leftSection={<Copy size={12} />}
                onClick={copy}
              >
                {copied ? t("servers.setup.copied") : t("servers.setup.copy")}
              </Button>
            )}
          </CopyButton>
        </Group>
        <Code block dir="ltr" style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
          {setup.install_command}
        </Code>
      </Stack>
      <Text size="sm">{t("servers.setup.firewall")}</Text>
      <Code block dir="ltr">
        {firewall}
      </Code>
      <Text size="xs" c="dimmed">
        {t("servers.setup.repoNote")}
      </Text>
      {error !== null && error !== undefined && <Alert color="red">{errorMessage(t, error)}</Alert>}
      <Group justify="flex-end">
        <Button leftSection={<PlugsConnected size={16} />} loading={connecting} onClick={onConnect}>
          {t("servers.connect")}
        </Button>
      </Group>
    </Stack>
  );
}

function ServerForm({
  initial,
  local,
  saving,
  error,
  onSubmit,
  onCancel,
}: {
  initial: ServerInput;
  local: boolean;
  saving: boolean;
  error: unknown;
  onSubmit: (values: ServerInput) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const form = useForm<ServerInput>({
    initialValues: initial,
    validate: {
      name: (v) => (v.trim() ? null : t("validation.required")),
      host: (v) =>
        local
          ? null
          : !v.trim()
            ? t("validation.required")
            : HOST_RE.test(v.trim())
              ? null
              : t("validation.hostInvalid"),
      port: (v) =>
        local || (Number.isInteger(v) && v >= 1 && v <= 65535) ? null : t("validation.portRange"),
    },
  });
  const nameTaken = error instanceof ApiError && error.code === "name_taken";
  return (
    <form
      onSubmit={form.onSubmit((values) =>
        onSubmit({ ...values, name: values.name.trim(), host: values.host.trim() }),
      )}
      noValidate
    >
      <Stack gap="sm">
        {error !== null && error !== undefined && !nameTaken && (
          <Alert color="red">{errorMessage(t, error)}</Alert>
        )}
        <TextInput
          label={t("servers.fields.name")}
          required
          maxLength={60}
          {...form.getInputProps("name")}
          error={nameTaken ? t("errors.name_taken") : form.errors.name}
        />
        {!local && (
          <Group grow align="flex-start">
            <TextInput
              label={t("servers.fields.host")}
              description={t("servers.fields.hostHint")}
              required
              dir="ltr"
              {...form.getInputProps("host")}
            />
            <NumberInput
              label={t("servers.fields.port")}
              required
              dir="ltr"
              min={1}
              max={65535}
              allowDecimal={false}
              allowNegative={false}
              hideControls
              maw={140}
              {...form.getInputProps("port")}
            />
          </Group>
        )}
        <Textarea
          label={t("servers.fields.notes")}
          autosize
          minRows={2}
          maxRows={6}
          maxLength={2000}
          {...form.getInputProps("notes")}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={saving}>
            {t("common.save")}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function ServersPage() {
  const { t } = useTranslation();
  const servers = useServers();
  const create = useCreateServer();
  const update = useUpdateServer();
  const remove = useDeleteServer();
  const connect = useConnectServer();
  const rotate = useRotateServerToken();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Server | null>(null);
  const [setup, setSetup] = useState<ServerSetup | null>(null);
  const [rekey, setRekey] = useState<Server | null>(null);
  const [deleting, setDeleting] = useState<Server | null>(null);
  const [connectingId, setConnectingId] = useState<number | null>(null);

  const runConnect = (server: { id: number; name: string }, after?: () => void) => {
    setConnectingId(server.id);
    connect.mutate(server.id, {
      onSuccess: () => {
        notifications.show({ color: "green", message: t("servers.connectedNote", server) });
        after?.();
      },
      onError: (error) => {
        if (!after) notifications.show({ color: "red", message: errorMessage(t, error) });
      },
      onSettled: () => setConnectingId(null),
    });
  };

  const closeSetup = () => {
    setSetup(null);
    connect.reset();
  };

  return (
    <Stack gap={18}>
      <PageHeader
        title={t("servers.title")}
        subtitle={t("servers.subtitle")}
        actions={
          <Button
            leftSection={<Plus size={16} />}
            onClick={() => {
              create.reset();
              setAdding(true);
            }}
          >
            {t("servers.add")}
          </Button>
        }
      />
      {servers.isPending && <Loader />}
      {servers.isError && <Alert color="red">{errorMessage(t, servers.error)}</Alert>}
      {servers.data && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
            gap: 12,
          }}
        >
          {servers.data.map((server) => (
            <ServerCard
              key={server.id}
              server={server}
              connecting={connectingId === server.id}
              onConnect={() => runConnect(server)}
              onEdit={() => {
                update.reset();
                setEditing(server);
              }}
              onToken={() => setRekey(server)}
              onDelete={() => {
                remove.reset();
                setDeleting(server);
              }}
            />
          ))}
        </div>
      )}
      {servers.data && servers.data.length === 1 && (
        <Paper withBorder p="lg">
          <Text size="sm" c="dimmed">
            {t("servers.onlyLocal")}
          </Text>
        </Paper>
      )}

      <Modal opened={adding} onClose={() => setAdding(false)} title={t("servers.add")} centered>
        <ServerForm
          initial={{ name: "", host: "", port: DEFAULT_PORT, notes: "" }}
          local={false}
          saving={create.isPending}
          error={create.error}
          onCancel={() => setAdding(false)}
          onSubmit={(values) =>
            create.mutate(values, {
              onSuccess: (data) => {
                setAdding(false);
                setSetup(data);
              },
            })
          }
        />
      </Modal>

      <Modal
        opened={editing !== null}
        onClose={() => setEditing(null)}
        title={t("servers.editTitle", { name: editing?.name ?? "" })}
        centered
      >
        {editing && (
          <ServerForm
            initial={{
              name: editing.name,
              host: editing.host ?? "",
              port: editing.port ?? DEFAULT_PORT,
              notes: editing.notes,
            }}
            local={editing.kind === "local"}
            saving={update.isPending}
            error={update.error}
            onCancel={() => setEditing(null)}
            onSubmit={(values) =>
              update.mutate(
                editing.kind === "local"
                  ? { id: editing.id, name: values.name, notes: values.notes }
                  : { id: editing.id, ...values },
                { onSuccess: () => setEditing(null) },
              )
            }
          />
        )}
      </Modal>

      <Modal
        opened={setup !== null}
        onClose={closeSetup}
        title={t("servers.setup.title", { name: setup?.server.name ?? "" })}
        size="lg"
        centered
      >
        {setup && (
          <SetupView
            setup={setup}
            connecting={connect.isPending}
            error={connect.error}
            onConnect={() => runConnect(setup.server, closeSetup)}
          />
        )}
      </Modal>

      <ConfirmDialog
        opened={rekey !== null}
        title={t("servers.newToken")}
        body={t("servers.newTokenConfirm", { name: rekey?.name ?? "" })}
        confirmLabel={t("servers.newToken")}
        loading={rotate.isPending}
        onCancel={() => setRekey(null)}
        onConfirm={() =>
          rekey &&
          rotate.mutate(rekey.id, {
            onSuccess: (data) => {
              setRekey(null);
              setSetup(data);
            },
          })
        }
      />

      <ConfirmDialog
        opened={deleting !== null}
        title={t("servers.deleteTitle")}
        body={t("servers.deleteConfirm", { name: deleting?.name ?? "" })}
        confirmLabel={t("common.delete")}
        loading={remove.isPending}
        onCancel={() => setDeleting(null)}
        onConfirm={() =>
          deleting &&
          remove.mutate(deleting.id, {
            onSuccess: () => {
              notifications.show({ color: "green", message: t("servers.deleted") });
              setDeleting(null);
            },
          })
        }
      >
        {remove.isError && (
          <Alert color="red" mb="md">
            {remove.error instanceof ApiError && remove.error.code === "server_in_use"
              ? t("servers.inUse")
              : errorMessage(t, remove.error)}
          </Alert>
        )}
      </ConfirmDialog>
    </Stack>
  );
}
