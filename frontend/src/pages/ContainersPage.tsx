import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  MultiSelect,
  NumberInput,
  Pagination,
  Paper,
  Progress,
  SegmentedControl,
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
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import type { TFunction } from "i18next";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError, errorMessage, isApiError } from "../api/client";
import {
  type ContainerAction,
  type ContainerSettings,
  type ContainerStats,
  type ContainerSummary,
  useContainerAction,
  useContainerActions,
  useContainerSettings,
  useContainerStats,
  useContainers,
  useSaveContainerSettings,
  useServerInfo,
  type ServerRef,
} from "../api/containers";
import { usableServers, useServers } from "../api/servers";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ContainerDrawer } from "../components/ContainerDrawer";
import { ContainerStateBadge } from "../components/ContainerStateBadge";
import {
  ArrowClockwise,
  ClockCountdown,
  Cube,
  GearSix,
  HardDrives,
  Lock,
  Play,
  Stop,
} from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { formatBytes, formatDuration } from "../format";
import { formatDateTime, formatNumber, formatPercent } from "../i18n";

type Filter = "all" | "running" | "problems" | "stopped";
type NumberField =
  | "cpu_percent"
  | "memory_percent"
  | "restart_count"
  | "restart_window_minutes"
  | "host_memory_percent"
  | "host_disk_percent";
// [setting, label key, max, min]
const THRESHOLDS: [NumberField, string, number, number][] = [
  ["cpu_percent", "cpu", 100, 0],
  ["memory_percent", "memory", 100, 0],
  ["restart_count", "restarts", 100, 0],
  ["restart_window_minutes", "restartWindow", 1440, 1],
  ["host_memory_percent", "hostMemory", 100, 0],
  ["host_disk_percent", "hostDisk", 100, 0],
];
const AGENT_CODES = new Set([
  "agent_unreachable",
  "agent_timeout",
  "agent_unauthorized",
  "docker_unavailable",
  "docker_permission_denied",
]);

function percent(value: number | null | undefined, lang: string): string {
  return value === null || value === undefined ? "—" : formatPercent(value, lang);
}

function AgentHelp({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const code = error instanceof ApiError ? error.code : "";
  return (
    <Paper withBorder p="lg">
      <Stack gap="sm">
        <Group gap="sm" wrap="nowrap">
          <span className="cl-icon-tile">
            <Cube size={20} />
          </span>
          <div>
            <Title order={4}>{t("containers.setup.title")}</Title>
            <Text size="sm" c="red.4">
              {errorMessage(t, error)}
            </Text>
          </div>
        </Group>
        <Text size="sm">{t("containers.setup.intro")}</Text>
        {code === "docker_permission_denied" ? (
          <>
            <Text size="sm">{t("containers.setup.gid")}</Text>
            <Code block dir="ltr">
              {`echo "MBP_DOCKER_GID=$(stat -c %g /var/run/docker.sock)" >> .env\ndocker compose up -d agent`}
            </Code>
          </>
        ) : (
          <>
            <Text size="sm">{t("containers.setup.steps")}</Text>
            <Code block dir="ltr">
              {`echo "COMPOSE_PROFILES=containers" >> .env\necho "MBP_DOCKER_GID=$(stat -c %g /var/run/docker.sock)" >> .env\ndocker compose up -d`}
            </Code>
          </>
        )}
        <Text size="xs" c="dimmed">
          {t("containers.setup.security")}
        </Text>
      </Stack>
    </Paper>
  );
}

function Meter(props: { label: string; value: string; note: string; percent: number | null }) {
  const p = props.percent;
  return (
    <div className="cl-stat">
      <div className="cl-stat-label">
        <span>{props.label}</span>
      </div>
      <div className="cl-stat-value">{props.value}</div>
      {p !== null && (
        <Progress
          value={Math.min(p, 100)}
          size="sm"
          my={4}
          color={p >= 90 ? "red" : p >= 75 ? "yellow" : "teal"}
        />
      )}
      <div className="cl-stat-note">{props.note}</div>
    </div>
  );
}

function ServerSummary({
  containers,
  server,
}: {
  containers: ContainerSummary[];
  server: ServerRef;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const info = useServerInfo(server);
  const host = info.data?.host;
  const docker = info.data?.docker;
  const running = containers.filter((c) => c.state === "running").length;
  const problems = containers.filter((c) => c.problem).length;
  const used = (total?: number | null, free?: number | null) =>
    total && free !== null && free !== undefined ? total - free : null;
  const memUsed = used(host?.memory_total, host?.memory_available);
  const diskUsed = used(host?.disk_total, host?.disk_free);
  return (
    <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing={12}>
      <Meter
        label={t("containers.summary.containers")}
        value={`${formatNumber(running, lang)} / ${formatNumber(containers.length, lang)}`}
        note={
          problems
            ? t("containers.summary.problems", { n: formatNumber(problems, lang) })
            : t("containers.summary.allGood")
        }
        percent={null}
      />
      <Meter
        label={t("containers.summary.cpu")}
        value={percent(host?.cpu_percent, lang)}
        note={t("containers.summary.cpuNote", {
          cpus: formatNumber(docker?.cpus ?? 0, lang),
          load: host?.load ? formatNumber(host.load[0], lang) : "—",
        })}
        percent={host?.cpu_percent ?? null}
      />
      <Meter
        label={t("containers.summary.memory")}
        value={memUsed !== null ? formatBytes(memUsed, t, lang) : "—"}
        note={t("containers.summary.of", {
          total: formatBytes(host?.memory_total, t, lang),
          percent: percent(memUsed !== null ? (memUsed * 100) / host!.memory_total! : null, lang),
        })}
        percent={memUsed !== null ? (memUsed * 100) / host!.memory_total! : null}
      />
      <Meter
        label={t("containers.summary.disk")}
        value={diskUsed !== null ? formatBytes(diskUsed, t, lang) : "—"}
        note={t("containers.summary.of", {
          total: formatBytes(host?.disk_total, t, lang),
          percent: percent(diskUsed !== null ? (diskUsed * 100) / host!.disk_total! : null, lang),
        })}
        percent={diskUsed !== null ? (diskUsed * 100) / host!.disk_total! : null}
      />
    </SimpleGrid>
  );
}

function uptime(c: ContainerSummary, t: TFunction, lang: string): string {
  if (c.state === "running" && c.started_at) {
    return formatDuration(Date.now() - new Date(c.started_at).getTime(), t, lang);
  }
  if (c.exit_code !== null && (c.state === "exited" || c.state === "dead")) {
    return t("containers.exitCode", { code: formatNumber(c.exit_code, lang) });
  }
  return "—";
}

function Controls(props: {
  c: ContainerSummary;
  readOnly: boolean;
  onAction: (c: ContainerSummary, action: ContainerAction) => void;
}) {
  const { t } = useTranslation();
  const { c } = props;
  if (props.readOnly || c.locked) {
    return (
      <Tooltip
        label={
          props.readOnly
            ? t("containers.readOnlyHint")
            : c.panel
              ? t("containers.panelHint")
              : t("containers.lockedHint")
        }
      >
        <span style={{ display: "inline-flex", color: "var(--color-neutral-500)" }}>
          <Lock size={16} aria-label={t("containers.locked")} />
        </span>
      </Tooltip>
    );
  }
  const stop = (e: React.MouseEvent, action: ContainerAction) => {
    e.stopPropagation();
    props.onAction(c, action);
  };
  return (
    <Group gap={4} wrap="nowrap">
      {c.state === "running" ? (
        <>
          <Tooltip label={t("containers.actions.restart")}>
            <ActionIcon
              variant="subtle"
              aria-label={`${t("containers.actions.restart")} ${c.name}`}
              onClick={(e) => stop(e, "restart")}
            >
              <ArrowClockwise size={16} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label={t("containers.actions.stop")}>
            <ActionIcon
              variant="subtle"
              color="red"
              aria-label={`${t("containers.actions.stop")} ${c.name}`}
              onClick={(e) => stop(e, "stop")}
            >
              <Stop size={16} />
            </ActionIcon>
          </Tooltip>
        </>
      ) : (
        <Tooltip label={t("containers.actions.start")}>
          <ActionIcon
            variant="subtle"
            color="green"
            aria-label={`${t("containers.actions.start")} ${c.name}`}
            onClick={(e) => stop(e, "start")}
          >
            <Play size={16} />
          </ActionIcon>
        </Tooltip>
      )}
    </Group>
  );
}

function Group_(props: {
  title: string;
  items: ContainerSummary[];
  stats: Record<string, ContainerStats | null>;
  readOnly: boolean;
  onOpen: (name: string) => void;
  onAction: (c: ContainerSummary, action: ContainerAction) => void;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  return (
    <Paper withBorder p={0} style={{ overflow: "hidden" }}>
      <Group
        justify="space-between"
        px="md"
        py="sm"
        style={{ borderBottom: "1px solid var(--color-neutral-800)" }}
      >
        <Group gap={8}>
          <Cube size={16} />
          <Text fw={600} dir="auto">
            {props.title}
          </Text>
        </Group>
        <Badge variant="light" color="gray">
          {formatNumber(props.items.length, lang)}
        </Badge>
      </Group>
      <Table.ScrollContainer minWidth={760}>
        <Table highlightOnHover verticalSpacing="sm" layout="fixed">
          <Table.Thead>
            <Table.Tr>
              <Table.Th w="30%">{t("containers.columns.name")}</Table.Th>
              <Table.Th w="16%">{t("containers.columns.state")}</Table.Th>
              <Table.Th w="13%">{t("containers.columns.uptime")}</Table.Th>
              <Table.Th w="9%">{t("containers.columns.cpu")}</Table.Th>
              <Table.Th w="15%">{t("containers.columns.memory")}</Table.Th>
              <Table.Th w="8%">{t("containers.columns.restarts")}</Table.Th>
              <Table.Th w="9%" />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {props.items.map((c) => {
              const s = props.stats[c.name];
              return (
                <Table.Tr
                  key={c.id}
                  onClick={() => props.onOpen(c.name)}
                  style={{ cursor: "pointer" }}
                  data-testid={`container-${c.name}`}
                >
                  <Table.Td>
                    <Text size="sm" fw={500} dir="ltr" ta="start" truncate>
                      {c.name}
                    </Text>
                    <Text size="xs" c="var(--color-neutral-500)" dir="ltr" ta="start" truncate>
                      {c.image}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <ContainerStateBadge c={c} />
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{uptime(c, t, lang)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {c.state === "running" ? percent(s?.cpu_percent, lang) : "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {c.state === "running" && s ? (
                      <Text size="sm">
                        {formatBytes(s.memory_usage, t, lang)}
                        <Text span size="xs" c="dimmed">
                          {` (${percent(s.memory_percent, lang)})`}
                        </Text>
                      </Text>
                    ) : (
                      <Text size="sm">—</Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c={c.restart_count ? "orange" : undefined}>
                      {formatNumber(c.restart_count, lang)}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Controls c={c} readOnly={props.readOnly} onAction={props.onAction} />
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Paper>
  );
}

function ContainersTab({ server }: { server: ServerRef }) {
  const { t } = useTranslation();
  const list = useContainers(server);
  const available = list.isSuccess;
  const stats = useContainerStats(server, available);
  const act = useContainerAction(server);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ c: ContainerSummary; action: ContainerAction } | null>(
    null,
  );

  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const items = (list.data?.containers ?? []).filter((c) => {
      if (filter === "running" && c.state !== "running") return false;
      if (filter === "problems" && !c.problem) return false;
      if (filter === "stopped" && c.state === "running") return false;
      return !needle || `${c.name} ${c.image} ${c.project ?? ""}`.toLowerCase().includes(needle);
    });
    const byProject = new Map<string, ContainerSummary[]>();
    for (const c of items) {
      const key = c.project ?? "";
      byProject.set(key, [...(byProject.get(key) ?? []), c]);
    }
    return [...byProject.entries()]
      .map(([project, cs]) => ({
        project,
        items: cs.sort(
          (a, b) =>
            Number(Boolean(b.problem)) - Number(Boolean(a.problem)) || a.name.localeCompare(b.name),
        ),
      }))
      .sort((a, b) =>
        a.project === "" ? 1 : b.project === "" ? -1 : a.project.localeCompare(b.project),
      );
  }, [list.data, filter, search]);

  const run = (c: ContainerSummary, action: ContainerAction) =>
    act.mutate(
      { name: c.name, action },
      {
        onSuccess: () => {
          notifications.show({
            color: "green",
            message: t(`containers.done.${action}`, { name: c.name }),
          });
          setConfirm(null);
        },
        onError: (error) => {
          notifications.show({ color: "red", message: errorMessage(t, error) });
          setConfirm(null);
        },
      },
    );

  if (list.isPending) return <Loader />;
  if (list.isError) {
    if (isApiError(list.error) && AGENT_CODES.has(list.error.code)) {
      return server === null ? (
        <AgentHelp error={list.error} />
      ) : (
        <RemoteAgentHelp error={list.error} />
      );
    }
    return <Alert color="red">{errorMessage(t, list.error)}</Alert>;
  }
  const containers = list.data.containers;
  const readOnly = list.data.read_only;

  return (
    <Stack gap="md">
      <ServerSummary containers={containers} server={server} />
      {readOnly && (
        <Alert color="blue" variant="light">
          {t("containers.readOnlyBanner")}
        </Alert>
      )}
      <Group justify="space-between" wrap="wrap">
        <SegmentedControl
          value={filter}
          onChange={(v) => setFilter(v as Filter)}
          data={(["all", "running", "problems", "stopped"] as Filter[]).map((value) => ({
            value,
            label: t(`containers.filter.${value}`),
          }))}
        />
        <TextInput
          placeholder={t("containers.search")}
          aria-label={t("containers.search")}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          style={{ flex: "0 1 280px" }}
        />
      </Group>
      {groups.length === 0 && (
        <Paper withBorder p="xl">
          <Text c="dimmed" ta="center">
            {t("containers.empty")}
          </Text>
        </Paper>
      )}
      {groups.map((g) => (
        <Group_
          key={g.project || "-"}
          title={g.project || t("containers.standalone")}
          items={g.items}
          stats={stats.data?.stats ?? {}}
          readOnly={readOnly}
          onOpen={setOpen}
          onAction={(c, action) =>
            action === "start" ? run(c, action) : setConfirm({ c, action })
          }
        />
      ))}
      <ContainerDrawer server={server} name={open} onClose={() => setOpen(null)} />
      <ConfirmDialog
        opened={confirm !== null}
        title={confirm ? t(`containers.confirm.${confirm.action}Title`) : ""}
        body={confirm ? t(`containers.confirm.${confirm.action}`, { name: confirm.c.name }) : ""}
        confirmLabel={confirm ? t(`containers.actions.${confirm.action}`) : ""}
        loading={act.isPending}
        onConfirm={() => confirm && run(confirm.c, confirm.action)}
        onCancel={() => setConfirm(null)}
      />
    </Stack>
  );
}

function ActivityTab({ server }: { server: ServerRef }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const [page, setPage] = useState(1);
  const actions = useContainerActions(server, page);
  if (actions.isPending) return <Loader />;
  if (actions.isError) return <Alert color="red">{errorMessage(t, actions.error)}</Alert>;
  const { items, total, page_size } = actions.data;
  return (
    <Paper withBorder p="lg">
      <Title order={4} mb={4}>
        {t("containers.activity.title")}
      </Title>
      <Text size="sm" c="dimmed" mb="md">
        {t("containers.activity.hint")}
      </Text>
      {items.length === 0 ? (
        <Text c="dimmed">{t("containers.activity.empty")}</Text>
      ) : (
        <Table.ScrollContainer minWidth={640}>
          <Table verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("containers.activity.time")}</Table.Th>
                <Table.Th>{t("containers.activity.container")}</Table.Th>
                <Table.Th>{t("containers.activity.action")}</Table.Th>
                <Table.Th>{t("containers.activity.by")}</Table.Th>
                <Table.Th>{t("containers.activity.result")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((item) => (
                <Table.Tr key={item.id}>
                  <Table.Td>
                    <Text size="sm">{formatDateTime(item.created_at, lang)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" dir="ltr" ta="start">
                      {item.container}
                    </Text>
                  </Table.Td>
                  <Table.Td>{t(`containers.actions.${item.action}`)}</Table.Td>
                  <Table.Td>
                    <Text size="sm">{item.actor}</Text>
                    <Text size="xs" c="dimmed">
                      {t(`containers.activity.sources.${item.source}`, {
                        defaultValue: item.source,
                      })}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {item.result === "ok" ? (
                      <Badge color="green" variant="light">
                        {t("containers.activity.ok")}
                      </Badge>
                    ) : (
                      <Tooltip label={item.detail ?? item.result}>
                        <Badge color="red" variant="light">
                          {t(`errors.${item.result}`, { defaultValue: item.result })}
                        </Badge>
                      </Tooltip>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {total > page_size && (
        <Group justify="center" mt="md">
          <Pagination total={Math.ceil(total / page_size)} value={page} onChange={setPage} />
        </Group>
      )}
    </Paper>
  );
}

function SettingsTab({ server }: { server: ServerRef }) {
  const { t } = useTranslation();
  const settings = useContainerSettings(server);
  const list = useContainers(server);
  const save = useSaveContainerSettings(server);
  const [values, setValues] = useState<ContainerSettings | null>(null);
  useEffect(() => {
    if (settings.data && values === null) setValues(settings.data);
  }, [settings.data, values]);

  if (settings.isError) return <Alert color="red">{errorMessage(t, settings.error)}</Alert>;
  if (settings.isPending || !values) return <Loader />;
  const set = <K extends keyof ContainerSettings>(key: K, value: ContainerSettings[K]) =>
    setValues((prev) => (prev ? { ...prev, [key]: value } : prev));
  const names = (list.data?.containers ?? []).map((c) => c.name);
  const options = [...new Set([...names, ...values.monitored])].sort();
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(values, {
          onSuccess: (data) => {
            setValues(data);
            notifications.show({ color: "green", message: t("containers.settings.saved") });
          },
        });
      }}
    >
      <Stack gap="md">
        <Paper withBorder p="lg">
          <Title order={4} mb="sm">
            {t("containers.settings.access")}
          </Title>
          <Stack gap="md">
            <Switch
              label={t("containers.settings.readOnly")}
              description={t("containers.settings.readOnlyHint")}
              checked={values.read_only}
              onChange={(e) => set("read_only", e.currentTarget.checked)}
            />
            <TagsInput
              label={t("containers.settings.hidden")}
              description={t("containers.settings.hiddenHint")}
              value={values.hidden}
              onChange={(v) => set("hidden", v)}
              dir="ltr"
              clearable
            />
            <TagsInput
              label={t("containers.settings.locked")}
              description={t("containers.settings.lockedHint")}
              value={values.locked}
              onChange={(v) => set("locked", v)}
              dir="ltr"
              clearable
            />
            <Switch
              label={t("containers.settings.botLogs")}
              description={t("containers.settings.botLogsHint")}
              checked={values.bot_logs}
              onChange={(e) => set("bot_logs", e.currentTarget.checked)}
            />
          </Stack>
        </Paper>
        <Paper withBorder p="lg">
          <Title order={4} mb={4}>
            {t("containers.settings.alerts")}
          </Title>
          <Text size="sm" c="dimmed" mb="md">
            {t("containers.settings.alertsHint")}
          </Text>
          <Stack gap="md">
            <Switch
              label={t("containers.settings.monitorAll")}
              checked={values.monitor_all}
              onChange={(e) => set("monitor_all", e.currentTarget.checked)}
            />
            {!values.monitor_all && (
              <MultiSelect
                label={t("containers.settings.monitored")}
                data={options}
                value={values.monitored}
                onChange={(v) => set("monitored", v)}
                searchable
                dir="ltr"
              />
            )}
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              {THRESHOLDS.map(([key, label, max, min]) => (
                <NumberInput
                  key={key}
                  label={t(`containers.settings.${label}`)}
                  min={min}
                  max={max}
                  value={values[key]}
                  onChange={(v) => set(key, typeof v === "number" ? v : min)}
                />
              ))}
            </SimpleGrid>
            <Text size="xs" c="dimmed">
              {t("containers.settings.zeroOff")}
            </Text>
          </Stack>
        </Paper>
        {save.isError && (
          <Alert color="red">
            {save.error instanceof ApiError && save.error.code === "validation_error"
              ? t("errors.validation_error")
              : errorMessage(t, save.error)}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button type="submit" loading={save.isPending}>
            {t("common.save")}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

/** Which server's containers are shown: the `server` URL parameter (none: the panel's own). */
function useServerParam(): [ServerRef, (server: ServerRef) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("server");
  const server = raw && /^\d+$/.test(raw) ? Number(raw) : null;
  const set = (next: ServerRef) => setParams(next === null ? {} : { server: String(next) });
  return [server, set];
}

function ServerPicker({
  server,
  onChange,
}: {
  server: ServerRef;
  onChange: (s: ServerRef) => void;
}) {
  const { t } = useTranslation();
  const servers = usableServers(useServers().data);
  if (servers.length < 2) return null;
  const local = servers.find((s) => s.kind === "local");
  const value = server === null ? String(local?.id ?? "") : String(server);
  return (
    <Select
      label={t("containers.server")}
      leftSection={<HardDrives size={16} />}
      allowDeselect={false}
      maw={320}
      data={servers.map((s) => ({
        value: String(s.id),
        label: s.kind === "local" ? `${s.name} (${t("servers.local")})` : s.name,
      }))}
      value={value}
      onChange={(v) => {
        if (!v) return;
        const picked = servers.find((s) => String(s.id) === v);
        onChange(picked?.kind === "local" ? null : Number(v));
      }}
    />
  );
}

function RemoteAgentHelp({ error }: { error: unknown }) {
  const { t } = useTranslation();
  return (
    <Paper withBorder p="lg">
      <Stack gap="sm">
        <Text c="red.4">{errorMessage(t, error)}</Text>
        <Text size="sm">{t("containers.remoteHelp")}</Text>
        <Group>
          <Button component={Link} to="/servers" variant="light">
            {t("nav.servers")}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

export function ContainersPage() {
  const { t } = useTranslation();
  const [server, setServer] = useServerParam();
  return (
    <Stack gap={18}>
      <PageHeader
        help="containers-usage"
        title={t("containers.title")}
        subtitle={t("containers.subtitle")}
      />
      <ServerPicker server={server} onChange={setServer} />
      <Tabs defaultValue="containers" keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="containers" leftSection={<HardDrives size={16} />}>
            {t("containers.tabs.containers")}
          </Tabs.Tab>
          <Tabs.Tab value="activity" leftSection={<ClockCountdown size={16} />}>
            {t("containers.tabs.activity")}
          </Tabs.Tab>
          <Tabs.Tab value="settings" leftSection={<GearSix size={16} />}>
            {t("containers.tabs.settings")}
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="containers">
          <ContainersTab key={server ?? 0} server={server} />
        </Tabs.Panel>
        <Tabs.Panel value="activity">
          <ActivityTab key={server ?? 0} server={server} />
        </Tabs.Panel>
        <Tabs.Panel value="settings">
          <SettingsTab key={server ?? 0} server={server} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
