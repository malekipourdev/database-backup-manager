import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Drawer,
  Group,
  Menu,
  Modal,
  MultiSelect,
  Paper,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type Webhook,
  type WebhookDelivery,
  type WebhookSecret,
  useApiCatalog,
  useWebhookDeliveries,
  useWebhookMutations,
  useWebhooks,
} from "../api/apiAccess";
import { ApiError, errorMessage } from "../api/client";
import { formatDateTime, formatNumber } from "../i18n";
import {
  CodeBlock,
  HttpStatusBadge,
  SecretModal,
  ServerLimitPicker,
  ServerLimitSummary,
} from "./ApiShared";
import { ConfirmDialog } from "./ConfirmDialog";
import {
  ArrowClockwise,
  CheckCircle,
  List,
  PencilSimple,
  PlugsConnected,
  Plus,
  Trash,
  Warning,
} from "./Icons";

export const SIGNATURE_EXAMPLE = `import hashlib, hmac, time

def verify(secret: str, body: bytes, timestamp: str, signature: str) -> bool:
    if abs(time.time() - int(timestamp)) > 300:
        return False
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return hmac.compare_digest("sha256=" + mac.hexdigest(), signature)

# signature = request.headers["X-MBP-Signature"]
# timestamp = request.headers["X-MBP-Timestamp"]`;

function eventLabel(t: (k: string, o?: Record<string, unknown>) => string, event: string): string {
  if (event === "*") return t("api.webhooks.allEvents");
  if (event === "ping") return t("api.webhooks.ping");
  return t(`alerts.names.${event}`, { defaultValue: event });
}

function WebhookModal(props: {
  editing: Webhook | null;
  events: string[];
  onClose: () => void;
  onCreated: (data: WebhookSecret) => void;
}) {
  const { t } = useTranslation();
  const { create, update } = useWebhookMutations();
  const editing = props.editing;
  const [name, setName] = useState(editing?.name ?? "");
  const [url, setUrl] = useState(editing?.url ?? "");
  const [all, setAll] = useState(editing ? editing.events.includes("*") : true);
  const [events, setEvents] = useState<string[]>(
    editing && !editing.events.includes("*") ? editing.events : [],
  );
  const [enabled, setEnabled] = useState(editing?.enabled ?? true);
  const [servers, setServers] = useState<number[] | null>(editing ? editing.server_ids : null);
  const mutation = editing ? update : create;
  const choices = props.events.filter((e) => e !== "*");
  const body = {
    name: name.trim(),
    url: url.trim(),
    events: all ? ["*"] : events,
    server_ids: servers,
    enabled,
  };
  const urlError =
    mutation.error instanceof ApiError && mutation.error.fields?.url
      ? t("api.validation.invalid_url")
      : null;

  const submit = () => {
    if (editing) {
      update.mutate(
        { id: editing.id, ...body },
        {
          onSuccess: () => {
            notifications.show({ color: "green", message: t("api.webhooks.saved") });
            props.onClose();
          },
        },
      );
    } else {
      create.mutate(body, { onSuccess: props.onCreated });
    }
  };

  return (
    <Modal
      opened
      onClose={props.onClose}
      size="lg"
      title={
        editing ? t("api.webhooks.editTitle", { name: editing.name }) : t("api.webhooks.newTitle")
      }
    >
      <Stack gap="md">
        <TextInput
          label={t("api.webhooks.name")}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          maxLength={80}
          data-autofocus
          required
        />
        <TextInput
          label={t("api.webhooks.url")}
          description={t("api.webhooks.urlHint")}
          placeholder={t("api.webhooks.urlPlaceholder")}
          value={url}
          onChange={(e) => setUrl(e.currentTarget.value)}
          error={urlError}
          dir="ltr"
          required
        />
        <div>
          <Text size="sm" fw={500} mb={6}>
            {t("api.webhooks.events")}
          </Text>
          <SegmentedControl
            fullWidth
            value={all ? "all" : "some"}
            onChange={(v) => setAll(v === "all")}
            data={[
              { value: "all", label: t("api.webhooks.allEvents") },
              { value: "some", label: t("api.webhooks.someEvents") },
            ]}
          />
          {!all && (
            <MultiSelect
              mt="sm"
              data={choices.map((e) => ({ value: e, label: eventLabel(t, e) }))}
              value={events}
              onChange={setEvents}
              placeholder={t("api.webhooks.pickEvents")}
              searchable
              aria-label={t("api.webhooks.events")}
            />
          )}
        </div>
        <ServerLimitPicker
          label={t("api.webhooks.servers")}
          allHint={t("api.webhooks.serversAllHint")}
          someHint={t("api.webhooks.serversSomeHint")}
          value={servers}
          onChange={setServers}
        />
        <Switch
          label={t("api.webhooks.enabled")}
          checked={enabled}
          onChange={(e) => setEnabled(e.currentTarget.checked)}
        />
        {mutation.error && !urlError && (
          <Alert color="red">{errorMessage(t, mutation.error)}</Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            loading={mutation.isPending}
            disabled={
              !body.name ||
              !body.url ||
              body.events.length === 0 ||
              (servers !== null && servers.length === 0)
            }
          >
            {editing ? t("common.save") : t("api.webhooks.create")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function DeliveryStatus({ delivery }: { delivery: WebhookDelivery }) {
  const { t } = useTranslation();
  const color =
    delivery.status === "sent" ? "green" : delivery.status === "failed" ? "red" : "gray";
  return (
    <Badge color={color} variant="light">
      {t(`api.webhooks.status.${delivery.status}`)}
    </Badge>
  );
}

function DeliveriesDrawer({ webhook, onClose }: { webhook: Webhook | null; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const deliveries = useWebhookDeliveries(webhook?.id ?? null);
  const { redeliver } = useWebhookMutations();
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Drawer
      opened={webhook !== null}
      onClose={onClose}
      position="right"
      size="xl"
      title={t("api.webhooks.deliveriesTitle", { name: webhook?.name ?? "" })}
    >
      <Stack gap="sm">
        <Group justify="space-between">
          <Text size="sm" c="dimmed">
            {t("api.webhooks.deliveriesHint")}
          </Text>
          <Button
            size="xs"
            variant="default"
            leftSection={<ArrowClockwise size={14} />}
            onClick={() => deliveries.refetch()}
            loading={deliveries.isFetching}
          >
            {t("api.refresh")}
          </Button>
        </Group>
        {redeliver.isError && <Alert color="red">{errorMessage(t, redeliver.error)}</Alert>}
        {deliveries.data?.length === 0 && (
          <Text size="sm" c="dimmed" ta="center" py="xl">
            {t("api.webhooks.noDeliveries")}
          </Text>
        )}
        {deliveries.data?.map((d) => (
          <Paper key={d.id} withBorder p="sm" radius="md">
            <Group justify="space-between" wrap="nowrap">
              <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
                <DeliveryStatus delivery={d} />
                <div style={{ minWidth: 0 }}>
                  <Text size="sm" fw={500} truncate>
                    {eventLabel(t, d.event)}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {formatDateTime(d.created_at, lang)}
                    {d.duration_ms !== null &&
                      ` · ${t("api.ms", { n: formatNumber(d.duration_ms, lang) })}`}
                    {d.attempts > 1 &&
                      ` · ${t("api.webhooks.attempts", { n: formatNumber(d.attempts, lang) })}`}
                  </Text>
                </div>
              </Group>
              <Group gap={4} wrap="nowrap">
                {d.response_status !== null && <HttpStatusBadge status={d.response_status} />}
                <Button
                  size="xs"
                  variant="subtle"
                  onClick={() => setOpen(open === d.id ? null : d.id)}
                >
                  {open === d.id ? t("api.webhooks.hide") : t("api.webhooks.details")}
                </Button>
                <Tooltip label={t("api.webhooks.redeliver")} withArrow>
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    loading={redeliver.isPending && redeliver.variables === d.id}
                    onClick={() =>
                      redeliver.mutate(d.id, { onSuccess: () => deliveries.refetch() })
                    }
                    aria-label={t("api.webhooks.redeliver")}
                  >
                    <ArrowClockwise size={16} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            </Group>
            {open === d.id && (
              <Stack gap="xs" mt="sm">
                {d.detail && (
                  <Alert color={d.status === "failed" ? "red" : "gray"} variant="light" p="xs">
                    <Text
                      size="xs"
                      ff="var(--font-mono)"
                      dir="ltr"
                      style={{ overflowWrap: "anywhere" }}
                    >
                      {d.detail}
                    </Text>
                  </Alert>
                )}
                <Text size="xs" c="dimmed" ff="var(--font-mono)" dir="ltr">
                  {`X-MBP-Delivery: ${d.uuid}`}
                </Text>
                <CodeBlock
                  title={t("api.webhooks.payload")}
                  code={JSON.stringify(d.payload, null, 2)}
                  maxHeight={260}
                />
              </Stack>
            )}
          </Paper>
        ))}
      </Stack>
    </Drawer>
  );
}

function HookHealth({ hook }: { hook: Webhook }) {
  const { t, i18n } = useTranslation();
  if (!hook.last_delivery_at) {
    return (
      <Text size="sm" c="dimmed">
        {t("api.webhooks.notYet")}
      </Text>
    );
  }
  const failing = hook.failures > 0;
  return (
    <Group gap={6} wrap="nowrap">
      {failing ? (
        <Warning size={16} color="var(--mantine-color-red-5)" />
      ) : (
        <CheckCircle size={16} color="var(--mantine-color-green-5)" />
      )}
      <Text size="sm" c={failing ? "red.4" : undefined}>
        {failing
          ? t("api.webhooks.failing", { n: formatNumber(hook.failures, i18n.language) })
          : hook.last_status}
        {" · "}
        {formatDateTime(hook.last_delivery_at, i18n.language)}
      </Text>
    </Group>
  );
}

export function WebhooksTab() {
  const { t } = useTranslation();
  const hooks = useWebhooks();
  const catalog = useApiCatalog();
  const { update, rotate, remove, test } = useWebhookMutations();
  const [modal, setModal] = useState<{ editing: Webhook | null } | null>(null);
  const [secret, setSecret] = useState<WebhookSecret | null>(null);
  const [deleting, setDeleting] = useState<Webhook | null>(null);
  const [viewing, setViewing] = useState<Webhook | null>(null);
  const events = catalog.data?.events ?? [];

  const runTest = (hook: Webhook) =>
    test.mutate(hook.id, {
      onSuccess: (d) =>
        notifications.show({
          color: d.status === "sent" ? "green" : "red",
          title: hook.name,
          message:
            d.status === "sent"
              ? t("api.webhooks.testOk", { status: d.response_status ?? "" })
              : t("api.webhooks.testFailed", { detail: d.detail ?? "" }),
        }),
      onError: (error) => notifications.show({ color: "red", message: errorMessage(t, error) }),
    });

  if (hooks.isError) return <Alert color="red">{errorMessage(t, hooks.error)}</Alert>;
  const list = hooks.data ?? [];
  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text size="sm" c="dimmed" maw={640}>
          {t("api.webhooks.hint")}
        </Text>
        <Button
          leftSection={<Plus size={16} />}
          onClick={() => setModal({ editing: null })}
          disabled={!catalog.data}
        >
          {t("api.webhooks.new")}
        </Button>
      </Group>
      {hooks.isSuccess && list.length === 0 && (
        <Paper withBorder p="xl" radius="md" data-testid="no-webhooks">
          <Stack align="center" gap="xs">
            <span className="cl-icon-tile" style={{ color: "var(--mantine-color-grape-4)" }}>
              <PlugsConnected size={22} />
            </span>
            <Text fw={500}>{t("api.webhooks.empty")}</Text>
            <Text size="sm" c="dimmed" ta="center" maw={460}>
              {t("api.webhooks.emptyHint")}
            </Text>
          </Stack>
        </Paper>
      )}
      {list.length > 0 && (
        <Paper withBorder radius="md" style={{ overflow: "hidden" }}>
          <Table.ScrollContainer minWidth={760}>
            <Table verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("api.webhooks.name")}</Table.Th>
                  <Table.Th>{t("api.webhooks.events")}</Table.Th>
                  <Table.Th>{t("api.webhooks.servers")}</Table.Th>
                  <Table.Th>{t("api.webhooks.lastDelivery")}</Table.Th>
                  <Table.Th w={150} />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.map((hook) => (
                  <Table.Tr key={hook.id} style={{ opacity: hook.enabled ? 1 : 0.6 }}>
                    <Table.Td>
                      <Group gap={8}>
                        <Text fw={600} size="sm">
                          {hook.name}
                        </Text>
                        {!hook.enabled && (
                          <Badge color="gray" variant="light" size="sm">
                            {t("api.keys.status.disabled")}
                          </Badge>
                        )}
                      </Group>
                      <Text
                        size="xs"
                        c="dimmed"
                        ff="var(--font-mono)"
                        dir="ltr"
                        ta="start"
                        style={{ overflowWrap: "anywhere" }}
                      >
                        {hook.url}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      {hook.events.includes("*") ? (
                        <Badge variant="light" color="grape">
                          {t("api.webhooks.allEvents")}
                        </Badge>
                      ) : (
                        <Group gap={4}>
                          {hook.events.slice(0, 3).map((e) => (
                            <Badge key={e} variant="light" color="gray" size="sm">
                              {eventLabel(t, e)}
                            </Badge>
                          ))}
                          {hook.events.length > 3 && (
                            <Badge variant="light" color="gray" size="sm">
                              {t("api.scopes.more", { n: hook.events.length - 3 })}
                            </Badge>
                          )}
                        </Group>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <ServerLimitSummary ids={hook.server_ids} />
                    </Table.Td>
                    <Table.Td>
                      <HookHealth hook={hook} />
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        <Button
                          size="xs"
                          variant="light"
                          loading={test.isPending && test.variables === hook.id}
                          onClick={() => runTest(hook)}
                        >
                          {t("api.webhooks.test")}
                        </Button>
                        <Menu position="bottom-end" withinPortal>
                          <Menu.Target>
                            <ActionIcon
                              variant="subtle"
                              color="gray"
                              aria-label={t("api.keys.more")}
                            >
                              <List size={18} />
                            </ActionIcon>
                          </Menu.Target>
                          <Menu.Dropdown>
                            <Menu.Item
                              leftSection={<List size={16} />}
                              onClick={() => setViewing(hook)}
                            >
                              {t("api.webhooks.deliveries")}
                            </Menu.Item>
                            <Menu.Item
                              leftSection={<PencilSimple size={16} />}
                              onClick={() => setModal({ editing: hook })}
                            >
                              {t("common.edit")}
                            </Menu.Item>
                            <Menu.Item
                              leftSection={<ArrowClockwise size={16} />}
                              onClick={() => rotate.mutate(hook.id, { onSuccess: setSecret })}
                            >
                              {t("api.webhooks.rotate")}
                            </Menu.Item>
                            <Menu.Item
                              onClick={() => update.mutate({ id: hook.id, enabled: !hook.enabled })}
                            >
                              {hook.enabled ? t("api.keys.disable") : t("api.keys.enable")}
                            </Menu.Item>
                            <Menu.Divider />
                            <Menu.Item
                              color="red"
                              leftSection={<Trash size={16} />}
                              onClick={() => setDeleting(hook)}
                            >
                              {t("common.delete")}
                            </Menu.Item>
                          </Menu.Dropdown>
                        </Menu>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {modal && (
        <WebhookModal
          editing={modal.editing}
          events={events}
          onClose={() => setModal(null)}
          onCreated={(data) => {
            setModal(null);
            setSecret(data);
          }}
        />
      )}
      <SecretModal
        opened={secret !== null}
        title={t("api.webhooks.secretTitle", { name: secret?.webhook.name ?? "" })}
        hint={t("api.webhooks.secretHint")}
        secret={secret?.secret ?? ""}
        onClose={() => setSecret(null)}
      >
        <CodeBlock title={t("api.webhooks.verify")} code={SIGNATURE_EXAMPLE} />
      </SecretModal>
      <DeliveriesDrawer webhook={viewing} onClose={() => setViewing(null)} />
      <ConfirmDialog
        opened={deleting !== null}
        title={t("api.webhooks.deleteTitle", { name: deleting?.name ?? "" })}
        body={t("api.webhooks.deleteBody")}
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
