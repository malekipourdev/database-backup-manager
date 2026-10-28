import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  NumberInput,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  TagsInput,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import {
  API_BASE,
  type ApiSettings,
  type OpenApiOperation,
  apiAccessKeys,
  fetchRequests,
  useApiKeys,
  useApiSettings,
  useOpenApi,
  useSaveApiSettings,
  useWebhooks,
} from "../api/apiAccess";
import { ApiError, errorMessage } from "../api/client";
import { KeysTab, curlExample } from "../components/ApiKeys";
import { CodeBlock, CopyLine, HttpStatusBadge, MethodBadge, Stat } from "../components/ApiShared";
import { SIGNATURE_EXAMPLE, WebhooksTab } from "../components/ApiWebhooks";
import {
  ArrowClockwise,
  BookOpen,
  GearSix,
  Key,
  List,
  MagnifyingGlass,
  PlugsConnected,
  Warning,
} from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { formatDateTime, formatNumber } from "../i18n";

const TABS = ["keys", "webhooks", "log", "reference", "settings"] as const;
type Tab = (typeof TABS)[number];
const TOPICS = ["auth", "scopes", "errors"] as const;

function jsExample(base: string): string {
  return `const API = "${base}";
const KEY = process.env.MBP_KEY;

async function api(path, init = {}) {
  const res = await fetch(API + path, {
    ...init,
    headers: { Authorization: \`Bearer \${KEY}\`, "Content-Type": "application/json", ...init.headers },
  });
  if (!res.ok) throw await res.json(); // {code, detail, fields}
  return res.status === 204 ? null : res.json();
}

const projects = await api("/projects");
await api(\`/projects/\${projects[0].id}/deploy\`, { method: "POST", body: JSON.stringify({}) });`;
}

function pythonExample(base: string): string {
  return `import os, httpx

api = httpx.Client(
    base_url="${base}",
    headers={"Authorization": f"Bearer {os.environ['MBP_KEY']}"},
)

started = api.post("/instances/1/backups", json={"scope": "all"}).json()
run = api.get(f"/backups/runs/{started['created'][0]['id']}").json()
print(run["status"])`;
}

/** Summary and the address of the API, above the tabs. */
function Overview({ settings }: { settings: ApiSettings | undefined }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const keys = useApiKeys();
  const hooks = useWebhooks();
  const base = `${window.location.origin}${API_BASE}`;
  const list = keys.data ?? [];
  const active = list.filter((k) => k.enabled && !k.expired).length;
  const requests = list.reduce((sum, k) => sum + k.requests_24h, 0);
  const errors = list.reduce((sum, k) => sum + k.errors_24h, 0);
  const failing = (hooks.data ?? []).filter((h) => h.enabled && h.failures > 0).length;
  return (
    <Stack gap="md">
      {settings && !settings.enabled && (
        <Alert color="orange" icon={<Warning size={18} />} title={t("api.disabledTitle")}>
          {t("api.disabledBody")}
        </Alert>
      )}
      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" align="flex-end" wrap="wrap" gap="md">
          <div style={{ flex: "1 1 360px", minWidth: 0 }}>
            <Text size="sm" fw={500} mb={6}>
              {t("api.baseUrl")}
            </Text>
            <CopyLine value={base} label={t("api.baseUrl")} />
          </div>
          <Group gap="xs">
            <Button
              component="a"
              href={`${API_BASE}/docs`}
              target="_blank"
              rel="noreferrer"
              variant="light"
              leftSection={<BookOpen size={16} />}
            >
              {t("api.swagger")}
            </Button>
            <Button
              component="a"
              href={`${API_BASE}/redoc`}
              target="_blank"
              rel="noreferrer"
              variant="default"
            >
              {t("api.redoc")}
            </Button>
            <Button
              component="a"
              href={`${API_BASE}/openapi.json`}
              target="_blank"
              rel="noreferrer"
              variant="default"
            >
              {t("api.openapi")}
            </Button>
          </Group>
        </Group>
      </Paper>
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing={12}>
        <Stat
          icon={<Key size={20} />}
          color="yellow"
          label={t("api.stats.keys")}
          value={formatNumber(active, lang)}
        />
        <Stat
          icon={<List size={20} />}
          color="blue"
          label={t("api.stats.requests")}
          value={formatNumber(requests, lang)}
        />
        <Stat
          icon={<Warning size={20} />}
          color={errors ? "orange" : "gray"}
          label={t("api.stats.errors")}
          value={formatNumber(errors, lang)}
        />
        <Stat
          icon={<PlugsConnected size={20} />}
          color={failing ? "red" : "grape"}
          label={failing ? t("api.stats.failingHooks") : t("api.stats.hooks")}
          value={formatNumber(failing || (hooks.data ?? []).length, lang)}
        />
      </SimpleGrid>
    </Stack>
  );
}

function LogTab({ keyId, onKey }: { keyId: number | null; onKey: (id: number | null) => void }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const keys = useApiKeys();
  const [errors, setErrors] = useState(false);
  const log = useInfiniteQuery({
    queryKey: apiAccessKeys.requests(keyId, errors),
    queryFn: ({ pageParam }) => fetchRequests(keyId, errors, pageParam),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_before,
  });
  const items = log.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
        <Group gap="md" align="flex-end">
          <Select
            label={t("api.log.key")}
            placeholder={t("api.log.allKeys")}
            data={(keys.data ?? []).map((k) => ({ value: String(k.id), label: k.name }))}
            value={keyId === null ? null : String(keyId)}
            onChange={(v) => onKey(v ? Number(v) : null)}
            clearable
            w={220}
          />
          <Switch
            label={t("api.log.errorsOnly")}
            checked={errors}
            onChange={(e) => setErrors(e.currentTarget.checked)}
            mb={8}
          />
        </Group>
        <Button
          variant="default"
          leftSection={<ArrowClockwise size={16} />}
          onClick={() => log.refetch()}
          loading={log.isRefetching}
        >
          {t("api.refresh")}
        </Button>
      </Group>
      {log.isError && <Alert color="red">{errorMessage(t, log.error)}</Alert>}
      {log.isSuccess && items.length === 0 ? (
        <Paper withBorder p="xl" radius="md">
          <Text c="dimmed" ta="center" size="sm">
            {t("api.log.empty")}
          </Text>
        </Paper>
      ) : (
        <Paper withBorder radius="md" style={{ overflow: "hidden" }}>
          <Table.ScrollContainer minWidth={820}>
            <Table verticalSpacing="xs" highlightOnHover data-testid="api-log">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("api.log.time")}</Table.Th>
                  <Table.Th>{t("api.log.key")}</Table.Th>
                  <Table.Th>{t("api.log.request")}</Table.Th>
                  <Table.Th>{t("api.log.result")}</Table.Th>
                  <Table.Th>{t("api.log.ip")}</Table.Th>
                  <Table.Th>{t("api.log.duration")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {items.map((r) => (
                  <Table.Tr key={r.id}>
                    <Table.Td>
                      <Text size="sm">{formatDateTime(r.created_at, lang)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{r.key_name}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={8} wrap="nowrap" dir="ltr">
                        <MethodBadge method={r.method} />
                        <Text size="sm" ff="var(--font-mono)" style={{ overflowWrap: "anywhere" }}>
                          {r.path}
                        </Text>
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={6} wrap="nowrap">
                        <HttpStatusBadge status={r.status} />
                        {r.error && (
                          <Text size="xs" c="dimmed" ff="var(--font-mono)">
                            {r.error}
                          </Text>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" ff="var(--font-mono)" dir="ltr" ta="start">
                        {r.ip || t("common.notAvailable")}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{t("api.ms", { n: formatNumber(r.duration_ms, lang) })}</Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {log.hasNextPage && (
        <Group justify="center">
          <Button
            variant="default"
            onClick={() => log.fetchNextPage()}
            loading={log.isFetchingNextPage}
          >
            {t("api.log.more")}
          </Button>
        </Group>
      )}
    </Stack>
  );
}

interface Endpoint {
  method: string;
  path: string;
  op: OpenApiOperation;
}

function ReferenceTab() {
  const { t, i18n } = useTranslation();
  const spec = useOpenApi();
  const [query, setQuery] = useState("");
  const base = `${window.location.origin}${API_BASE}`;
  const groups = useMemo(() => {
    const byTag = new Map<string, Endpoint[]>();
    for (const [path, ops] of Object.entries(spec.data?.paths ?? {})) {
      for (const [method, op] of Object.entries(ops)) {
        const tag = op.tags?.[0] ?? "other";
        const short = path.slice(API_BASE.length);
        const haystack =
          `${method} ${short} ${op.summary ?? ""} ${op["x-required-scope"] ?? ""}`.toLowerCase();
        if (query && !haystack.includes(query.toLowerCase())) continue;
        byTag.set(tag, [...(byTag.get(tag) ?? []), { method, path: short, op }]);
      }
    }
    const order = (spec.data?.tags ?? []).map((tag) => tag.name);
    return [...byTag.entries()].sort(([a], [b]) => order.indexOf(a) - order.indexOf(b));
  }, [spec.data, query]);
  const total = groups.reduce((n, [, eps]) => n + eps.length, 0);

  return (
    <Stack gap="lg">
      <div>
        <Title order={4} mb={4}>
          {t("api.reference.quickStart")}
        </Title>
        <Text size="sm" c="dimmed" mb="sm">
          {t("api.reference.quickStartHint")}
        </Text>
        <Tabs defaultValue="curl" variant="pills" radius="md">
          <Tabs.List mb="xs">
            <Tabs.Tab value="curl">{t("api.reference.langs.curl")}</Tabs.Tab>
            <Tabs.Tab value="js">{t("api.reference.langs.js")}</Tabs.Tab>
            <Tabs.Tab value="python">{t("api.reference.langs.python")}</Tabs.Tab>
            <Tabs.Tab value="webhook">{t("api.reference.langs.webhook")}</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="curl">
            <CodeBlock
              code={`${curlExample("$MBP_KEY", "/projects")}\n\n${curlExample("$MBP_KEY", "/backups/runs?page_size=20")}`}
            />
          </Tabs.Panel>
          <Tabs.Panel value="js">
            <CodeBlock code={jsExample(base)} />
          </Tabs.Panel>
          <Tabs.Panel value="python">
            <CodeBlock code={pythonExample(base)} />
          </Tabs.Panel>
          <Tabs.Panel value="webhook">
            <CodeBlock code={SIGNATURE_EXAMPLE} />
          </Tabs.Panel>
        </Tabs>
      </div>

      <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
        {TOPICS.map((topic) => (
          <Paper key={topic} withBorder p="md" radius="md">
            <Text fw={600} mb={4}>
              {t(`api.reference.topics.${topic}.title`)}
            </Text>
            <Text size="sm" c="dimmed">
              {t(`api.reference.topics.${topic}.body`)}
            </Text>
          </Paper>
        ))}
      </SimpleGrid>

      <div>
        <Group justify="space-between" mb="sm" align="flex-end">
          <div>
            <Title order={4}>{t("api.reference.endpoints")}</Title>
            <Text size="sm" c="dimmed">
              {t("api.reference.endpointsHint", { n: formatNumber(total, i18n.language) })}
            </Text>
          </div>
          <TextInput
            leftSection={<MagnifyingGlass size={16} />}
            placeholder={t("api.reference.search")}
            aria-label={t("api.reference.search")}
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            w={280}
          />
        </Group>
        {spec.isError && <Alert color="red">{t("api.reference.loadError")}</Alert>}
        <Accordion variant="separated" multiple radius="md" data-testid="api-reference">
          {groups.map(([tag, endpoints]) => (
            <Accordion.Item key={tag} value={tag}>
              <Accordion.Control>
                <Group gap="sm" wrap="nowrap">
                  <Text fw={600}>{t(`api.areas.${tag}.label`, { defaultValue: tag })}</Text>
                  <Badge variant="light" color="gray">
                    {formatNumber(endpoints.length, i18n.language)}
                  </Badge>
                  <Text size="xs" c="dimmed" truncate visibleFrom="sm">
                    {t(`api.areas.${tag}.hint`, { defaultValue: "" })}
                  </Text>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap={0}>
                  {endpoints.map((ep, index) => (
                    <Group
                      key={`${ep.method}${ep.path}`}
                      justify="space-between"
                      wrap="nowrap"
                      py={8}
                      gap="sm"
                      dir="ltr"
                      style={{
                        borderTop: index ? "1px solid var(--color-neutral-800)" : undefined,
                      }}
                    >
                      <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
                        <MethodBadge method={ep.method} />
                        <div style={{ minWidth: 0 }}>
                          <Text
                            size="sm"
                            ff="var(--font-mono)"
                            style={{ overflowWrap: "anywhere" }}
                          >
                            {ep.path}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {ep.op.summary}
                          </Text>
                        </div>
                      </Group>
                      {ep.op["x-required-scope"] && (
                        <Badge
                          variant="outline"
                          radius="sm"
                          ff="var(--font-mono)"
                          color={ep.op["x-required-scope"].endsWith(":read") ? "blue" : "orange"}
                          style={{ flexShrink: 0, textTransform: "none" }}
                        >
                          {ep.op["x-required-scope"]}
                        </Badge>
                      )}
                    </Group>
                  ))}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
        <Text size="sm" c="dimmed" mt="sm">
          {t("api.reference.full")}{" "}
          <Anchor href={`${API_BASE}/docs`} target="_blank" rel="noreferrer">
            {t("api.swagger")}
          </Anchor>
        </Text>
      </div>
    </Stack>
  );
}

function SettingsTab() {
  const { t } = useTranslation();
  const settings = useApiSettings();
  const save = useSaveApiSettings();
  const [form, setForm] = useState<ApiSettings | null>(null);
  useEffect(() => {
    if (settings.data) setForm(settings.data);
  }, [settings.data]);
  if (!form) return null;
  const originError =
    save.error instanceof ApiError && save.error.fields?.cors_origins
      ? t("api.validation.invalid_origin")
      : null;
  return (
    <Paper withBorder p="lg" radius="md" maw={760}>
      <Stack gap="lg">
        <Switch
          size="md"
          label={t("api.settings.enabled")}
          description={t("api.settings.enabledHint")}
          checked={form.enabled}
          onChange={(e) => setForm({ ...form, enabled: e.currentTarget.checked })}
        />
        <TagsInput
          label={t("api.settings.origins")}
          description={t("api.settings.originsHint")}
          placeholder={t("api.settings.originsPlaceholder")}
          value={form.cors_origins}
          onChange={(v) => setForm({ ...form, cors_origins: v })}
          error={originError}
          styles={{ input: { direction: "ltr" } }}
          clearable
        />
        <NumberInput
          label={t("api.settings.retention")}
          description={t("api.settings.retentionHint")}
          value={form.log_retention_days}
          onChange={(v) => setForm({ ...form, log_retention_days: typeof v === "number" ? v : 30 })}
          min={1}
          max={365}
          w={260}
        />
        <Alert color="gray" variant="light">
          {t("api.settings.proxyHint")}
        </Alert>
        {save.isError && !originError && <Alert color="red">{errorMessage(t, save.error)}</Alert>}
        <Group justify="flex-end">
          <Button
            loading={save.isPending}
            onClick={() =>
              save.mutate(form, {
                onSuccess: () =>
                  notifications.show({ color: "green", message: t("api.settings.saved") }),
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

export function ApiAccessPage() {
  const { t } = useTranslation();
  const settings = useApiSettings();
  const [params, setParams] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(params.get("tab") ?? "")
    ? (params.get("tab") as Tab)
    : "keys";
  const [logKey, setLogKey] = useState<number | null>(null);
  const go = (next: Tab) => setParams(next === "keys" ? {} : { tab: next }, { replace: true });
  return (
    <Stack gap={18}>
      <PageHeader help="api" title={t("api.title")} subtitle={t("api.subtitle")} />
      <Overview settings={settings.data} />
      <Tabs value={tab} onChange={(v) => go((v as Tab) ?? "keys")} keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="keys" leftSection={<Key size={16} />}>
            {t("api.tabs.keys")}
          </Tabs.Tab>
          <Tabs.Tab value="webhooks" leftSection={<PlugsConnected size={16} />}>
            {t("api.tabs.webhooks")}
          </Tabs.Tab>
          <Tabs.Tab value="log" leftSection={<List size={16} />}>
            {t("api.tabs.log")}
          </Tabs.Tab>
          <Tabs.Tab value="reference" leftSection={<BookOpen size={16} />}>
            {t("api.tabs.reference")}
          </Tabs.Tab>
          <Tabs.Tab value="settings" leftSection={<GearSix size={16} />}>
            {t("api.tabs.settings")}
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="keys">
          <KeysTab
            onShowLog={(id) => {
              setLogKey(id);
              go("log");
            }}
          />
        </Tabs.Panel>
        <Tabs.Panel value="webhooks">
          <WebhooksTab />
        </Tabs.Panel>
        <Tabs.Panel value="log">
          <LogTab keyId={logKey} onKey={setLogKey} />
        </Tabs.Panel>
        <Tabs.Panel value="reference">
          <ReferenceTab />
        </Tabs.Panel>
        <Tabs.Panel value="settings">
          <SettingsTab />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
