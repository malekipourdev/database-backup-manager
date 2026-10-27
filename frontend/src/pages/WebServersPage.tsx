import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  NumberInput,
  Pagination,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { errorMessage, isApiError } from "../api/client";
import { useContainers } from "../api/containers";
import {
  type Domain,
  type WebActionItem,
  type WebCertificate,
  type WebCheck,
  type WebResult,
  type WebServer,
  type WebServerKind,
  type WebServiceStatus,
  type WebSettings,
  type WebSite,
  daysLeft,
  domainsOf,
  servedBy,
  useCertbot,
  useCertificates,
  useCheckMutations,
  useConfigTest,
  useControl,
  useSaveWebSettings,
  useStartJob,
  useWebActions,
  useWebChecks,
  useWebServers,
  useWebSettings,
  useWebStatus,
} from "../api/webservers";
import { ConfirmDialog } from "../components/ConfirmDialog";
import {
  ArrowClockwise,
  ClockCountdown,
  GearSix,
  Globe,
  Lock,
  MagnifyingGlass,
  Play,
  Plus,
  ShieldCheck,
  Trash,
  Warning,
} from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { ServerBadge } from "../components/ServerBadge";
import { CertbotModal, JobPanel, NewSiteModal, WebResultAlert } from "../components/WebDialogs";
import { WebSiteDrawer } from "../components/WebSiteDrawer";
import { formatDateTime, formatNumber } from "../i18n";
import { useCurrentServer } from "../server/CurrentServer";

type Filter = "enabled" | "all";
type ServerRef = number | null;
const KIND_LABEL = { nginx: "nginx", apache: "Apache" } as const;
const PLAIN_HOST = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/i;
const STATE_COLORS: Record<string, string> = {
  active: "green",
  reloading: "blue",
  activating: "blue",
  inactive: "gray",
  failed: "red",
};

function SetupHelp({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Paper withBorder p="lg">
      <Stack gap="sm">
        <Group gap="sm" wrap="nowrap">
          <span className="cl-icon-tile">
            <Globe size={20} />
          </span>
          <Title order={4}>{title}</Title>
        </Group>
        {children}
      </Stack>
    </Paper>
  );
}

function AgentProblem({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const current = useCurrentServer().server;
  const local = !current || current.kind === "local";
  const outdated = isApiError(error, "agent_outdated");
  return (
    <SetupHelp title={t("webservers.setup.agentTitle")}>
      <Text size="sm" c="red.4">
        {errorMessage(t, error)}
      </Text>
      {outdated ? (
        <Text size="sm">{t("webservers.setup.outdated")}</Text>
      ) : (
        <Text size="sm">
          {local ? t("webservers.setup.agentLocal") : t("containers.remoteHelp")}
        </Text>
      )}
      <Group>
        <Button component={Link} to={local ? "/containers" : "/servers"} variant="light">
          {local ? t("nav.containers") : t("nav.servers")}
        </Button>
      </Group>
    </SetupHelp>
  );
}

function NotMounted() {
  const { t } = useTranslation();
  const current = useCurrentServer().server;
  const local = !current || current.kind === "local";
  return (
    <SetupHelp title={t("webservers.setup.mountTitle")}>
      <Text size="sm">{t("webservers.setup.mount")}</Text>
      <Code block dir="ltr">
        {local
          ? `git pull\ndocker compose up -d --build agent`
          : `git pull\ndocker compose -f docker-compose.agent.yml --env-file .env.agent up -d --build`}
      </Code>
      <Text size="xs" c="dimmed">
        {t("webservers.setup.readOnly")}
      </Text>
    </SetupHelp>
  );
}

// --- status of the web servers ---

function ServiceCard(props: {
  ws: WebServer;
  status: WebServiceStatus | undefined;
  statusError: unknown;
  server: ServerRef;
  readOnly: boolean;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const { ws, status } = props;
  const enabled = ws.sites.filter((s) => s.enabled && !s.maintenance_page).length;
  const test = useConfigTest(props.server);
  const control = useControl(props.server);
  const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState<WebResult | { ok: boolean; output: string } | null>(null);
  const lastReload = status?.panel_reload ?? status?.last_reload ?? null;
  return (
    <Paper withBorder p="md" data-testid={`webserver-${ws.kind}`}>
      <Stack gap={8}>
        <Group justify="space-between" wrap="nowrap">
          <Group gap={8} wrap="nowrap">
            <Globe size={18} />
            <Text fw={600}>{KIND_LABEL[ws.kind]}</Text>
            {status?.version && (
              <Text size="sm" c="dimmed" dir="ltr">
                {status.version}
              </Text>
            )}
          </Group>
          {status ? (
            <Badge color={STATE_COLORS[status.state] ?? "gray"} variant="light">
              {t(`webservers.state.${status.state}`, { defaultValue: status.state })}
            </Badge>
          ) : ws.error ? (
            <Badge color="red" variant="light">
              {t("webservers.unreadable")}
            </Badge>
          ) : null}
        </Group>
        <div className="cl-kv">
          <span>{t("webservers.sites")}</span>
          <span>{formatNumber(enabled, lang)}</span>
        </div>
        <div className="cl-kv">
          <span>{t("webservers.config")}</span>
          <code dir="ltr">{ws.config}</code>
        </div>
        {status?.since && (
          <div className="cl-kv">
            <span>{t("webservers.since")}</span>
            <span dir="ltr">{status.since}</span>
          </div>
        )}
        <div className="cl-kv">
          <span>{t("webservers.lastReload")}</span>
          <span dir="ltr">
            {lastReload
              ? formatDateTime(lastReload.replace(/([+-]\d{2})(\d{2})$/, "$1:$2"), lang)
              : "—"}
          </span>
        </div>
        {props.statusError !== null && props.statusError !== undefined && (
          <Text size="xs" c="orange">
            {errorMessage(t, props.statusError)}
          </Text>
        )}
        {ws.error && (
          <Alert color="red" p="xs">
            <Text size="xs" dir="ltr" ta="start">
              {ws.error}
            </Text>
          </Alert>
        )}
        {ws.warnings.length > 0 && (
          <Alert color="yellow" p="xs" icon={<Warning size={16} />}>
            <Stack gap={2}>
              {ws.warnings.map((w) => (
                <Text key={w} size="xs" dir="ltr" ta="start">
                  {w}
                </Text>
              ))}
            </Stack>
          </Alert>
        )}
        <Group gap="xs" mt={4}>
          <Button
            size="xs"
            variant="default"
            loading={test.isPending}
            onClick={() => test.mutate(ws.kind, { onSuccess: setResult })}
          >
            {t("webservers.actions.test")}
          </Button>
          <Tooltip label={t("webservers.readOnlyHint")} disabled={!props.readOnly}>
            <Button
              size="xs"
              variant="light"
              disabled={props.readOnly}
              loading={control.isPending && control.variables?.action === "reload"}
              leftSection={<ArrowClockwise size={14} />}
              onClick={() =>
                control.mutate({ kind: ws.kind, action: "reload" }, { onSuccess: setResult })
              }
            >
              {t("webservers.actions.reload")}
            </Button>
          </Tooltip>
          <Button
            size="xs"
            variant="light"
            color="orange"
            disabled={props.readOnly}
            loading={control.isPending && control.variables?.action === "restart"}
            onClick={() => setConfirm(true)}
          >
            {t("webservers.actions.restart")}
          </Button>
        </Group>
        {control.isError && <Alert color="red">{errorMessage(t, control.error)}</Alert>}
        {result &&
          ("code" in result ? (
            <WebResultAlert result={result} />
          ) : (
            <Alert color={result.ok ? "green" : "red"} p="xs">
              <Stack gap={4}>
                <Text size="sm">
                  {result.ok ? t("webservers.testOk") : t("webservers.result.config_test_failed")}
                </Text>
                {result.output && (
                  <Code block dir="ltr">
                    {result.output}
                  </Code>
                )}
              </Stack>
            </Alert>
          ))}
      </Stack>
      <ConfirmDialog
        opened={confirm}
        title={t("webservers.actions.restart")}
        body={t("webservers.restartConfirm", { name: KIND_LABEL[ws.kind] })}
        confirmLabel={t("webservers.actions.restart")}
        loading={control.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() =>
          control.mutate(
            { kind: ws.kind, action: "restart" },
            { onSuccess: setResult, onSettled: () => setConfirm(false) },
          )
        }
      />
    </Paper>
  );
}

function CertbotCard(props: { server: ServerRef; kind: WebServerKind; readOnly: boolean }) {
  const { t } = useTranslation();
  const certbot = useCertbot(props.server);
  const start = useStartJob(props.server);
  const [job, setJob] = useState<string | null>(null);
  const data = certbot.data;
  return (
    <Paper withBorder p="md" data-testid="certbot-card">
      <Stack gap={8}>
        <Group justify="space-between">
          <Group gap={8}>
            <ShieldCheck size={18} />
            <Text fw={600}>{t("webservers.certbot.card")}</Text>
          </Group>
          {data && (
            <Badge color={data.installed ? "green" : "gray"} variant="light">
              {data.installed
                ? `certbot ${data.version ?? ""}`.trim()
                : t("webservers.certbot.missing")}
            </Badge>
          )}
        </Group>
        {certbot.isPending && <Loader size="sm" />}
        {certbot.isError && (
          <Text size="xs" c="orange">
            {errorMessage(t, certbot.error)}
          </Text>
        )}
        {data && (
          <div className="cl-kv">
            <span>{t("webservers.certbot.autoRenew")}</span>
            <span dir="ltr">{data.auto_renew ?? t("webservers.certbot.noAutoRenew")}</span>
          </div>
        )}
        {data && !data.installed && (
          <Text size="xs" c="dimmed">
            {data.package_manager
              ? t("webservers.certbot.installHint")
              : t("webservers.certbot.installManual")}
          </Text>
        )}
        <Group gap="xs">
          {data?.installed && (
            <Button
              size="xs"
              variant="light"
              disabled={props.readOnly}
              loading={start.isPending}
              onClick={() =>
                start.mutate(
                  { path: "/webservers/-/certbot/renew" },
                  { onSuccess: (j) => setJob(j.id) },
                )
              }
            >
              {t("webservers.certbot.renewAll")}
            </Button>
          )}
          {data && !data.installed && data.package_manager && (
            <Button
              size="xs"
              variant="light"
              disabled={props.readOnly}
              loading={start.isPending}
              onClick={() =>
                start.mutate(
                  { path: `/webservers/${props.kind}/certbot/install` },
                  { onSuccess: (j) => setJob(j.id) },
                )
              }
            >
              {t("webservers.certbot.install")}
            </Button>
          )}
        </Group>
        {start.isError && <Alert color="red">{errorMessage(t, start.error)}</Alert>}
        {job && <JobPanel server={props.server} id={job} />}
      </Stack>
    </Paper>
  );
}

// --- the domains ---

function Serves({ site }: { site: WebSite }) {
  const { t } = useTranslation();
  if (site.backends.length > 0) {
    return (
      <Stack gap={2}>
        {site.backends.map((b) => (
          <Text key={`${b.kind}-${b.target}`} size="sm" dir="ltr" ta="start">
            <Badge size="xs" variant="light" color="blue" me={6}>
              {t(`webservers.backends.${b.kind}`, { defaultValue: b.kind })}
            </Badge>
            {b.target}
            {b.servers.length > 0 && (
              <Text span size="xs" c="dimmed">
                {" "}
                ({b.servers.join(", ")})
              </Text>
            )}
          </Text>
        ))}
      </Stack>
    );
  }
  if (site.redirect) {
    return (
      <Text size="sm" dir="ltr" ta="start">
        <Badge size="xs" variant="light" color="grape" me={6}>
          {t("webservers.redirect")}
        </Badge>
        {site.redirect}
      </Text>
    );
  }
  if (site.root) {
    return (
      <Text size="sm" dir="ltr" ta="start">
        <Badge size="xs" variant="light" color="gray" me={6}>
          {t("webservers.files")}
        </Badge>
        {site.root}
      </Text>
    );
  }
  return <Text c="dimmed">—</Text>;
}

function CertBadge(props: { d: Domain; certificates: Record<string, WebCertificate> }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const { d } = props;
  if (!d.ssl) {
    return (
      <Badge color="orange" variant="light">
        {t("webservers.httpOnly")}
      </Badge>
    );
  }
  const path = d.sites.find((s) => s.certificate)?.certificate ?? null;
  const cert = path ? props.certificates[path] : undefined;
  const days = daysLeft(cert);
  const redirects = d.sites.some((s) => !s.ssl && s.redirect?.startsWith("https://"));
  const color = days === null ? "teal" : days < 0 ? "red" : days < 14 ? "orange" : "teal";
  const label =
    days === null
      ? redirects
        ? t("webservers.httpsForced")
        : t("webservers.https")
      : days < 0
        ? t("webservers.expired")
        : t("webservers.daysLeft", { n: formatNumber(days, lang) });
  return (
    <Tooltip
      label={
        cert?.not_after
          ? `${path} — ${cert.issuer ?? ""} — ${formatDateTime(cert.not_after, lang)}`
          : (path ?? t("webservers.https"))
      }
    >
      <Badge color={color} variant="light" leftSection={<Lock size={11} />}>
        {label}
      </Badge>
    </Tooltip>
  );
}

function DomainRow(props: {
  d: Domain;
  certificates: Record<string, WebCertificate>;
  check: WebCheck | undefined;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const { d } = props;
  const site = servedBy(d);
  const files = [...new Set(d.sites.map((s) => `${s.file}:${s.line}`))];
  return (
    <Table.Tr
      data-testid={`domain-${d.name || "catch-all"}`}
      style={{ opacity: d.enabled ? 1 : 0.6, cursor: "pointer" }}
      onClick={props.onOpen}
    >
      <Table.Td>
        <Stack gap={4}>
          {d.name === "" ? (
            <Text size="sm" fs="italic" c="dimmed">
              {t("webservers.catchAll")}
            </Text>
          ) : PLAIN_HOST.test(d.name) && d.enabled ? (
            <Anchor
              href={`${d.ssl ? "https" : "http"}://${d.name}`}
              target="_blank"
              rel="noopener noreferrer"
              size="sm"
              dir="ltr"
              style={{ overflowWrap: "anywhere" }}
              onClick={(e) => e.stopPropagation()}
            >
              {d.name}
            </Anchor>
          ) : (
            <Text size="sm" dir="ltr" ta="start" style={{ overflowWrap: "anywhere" }}>
              {d.name}
            </Text>
          )}
          <Group gap={4}>
            {d.maintenance && (
              <Badge size="xs" color="orange" variant="light">
                {t("webservers.maintenance")}
              </Badge>
            )}
            {!d.enabled && (
              <Badge size="xs" color="gray" variant="outline">
                {t("webservers.disabled")}
              </Badge>
            )}
            {d.sites.some((s) => s.default_server) && (
              <Badge size="xs" color="gray" variant="light">
                {t("webservers.default")}
              </Badge>
            )}
            {props.check?.status && (
              <Badge size="xs" color={props.check.status === "up" ? "green" : "red"} variant="dot">
                {t(`webservers.checks.status.${props.check.status}`)}
              </Badge>
            )}
          </Group>
        </Stack>
      </Table.Td>
      <Table.Td>
        <Text size="sm">{KIND_LABEL[d.server]}</Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" dir="ltr" ta="start">
          {d.ports.join(", ") || "—"}
        </Text>
      </Table.Td>
      <Table.Td>
        <CertBadge d={d} certificates={props.certificates} />
      </Table.Td>
      <Table.Td>
        <Serves site={site} />
      </Table.Td>
      <Table.Td>
        <Stack gap={2}>
          {files.map((f) => (
            <Text
              key={f}
              size="xs"
              c="dimmed"
              dir="ltr"
              ta="start"
              style={{ overflowWrap: "anywhere" }}
            >
              {f}
            </Text>
          ))}
        </Stack>
      </Table.Td>
    </Table.Tr>
  );
}

function domainKey(d: Domain): string {
  return `${d.server}\u0000${d.name}`;
}

function checkFor(d: Domain, checks: WebCheck[]): WebCheck | undefined {
  return checks.find((c) => {
    try {
      return new URL(c.url).hostname === d.name;
    } catch {
      return false;
    }
  });
}

function SitesTab(props: { server: ServerRef; servers: WebServer[]; readOnly: boolean }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const [filter, setFilter] = useState<Filter>("enabled");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [certFor, setCertFor] = useState<Domain | null>(null);
  const certificates = useCertificates(props.server);
  const certbot = useCertbot(props.server);
  const checks = useWebChecks(props.server);
  const checkActions = useCheckMutations(props.server);
  const all = useMemo(() => domainsOf(props.servers), [props.servers]);
  const disabled = all.filter((d) => !d.enabled).length;
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return all.filter((d) => {
      if (filter === "enabled" && !d.enabled) return false;
      if (!needle) return true;
      const site = servedBy(d);
      const text = [d.name, site.root, site.redirect, ...site.backends.map((b) => b.target)];
      return text.join(" ").toLowerCase().includes(needle);
    });
  }, [all, filter, search]);
  // The open domain, found again after every reload (it may have been turned off).
  const opened = open
    ? (all.find((d) => domainKey(d) === open && d.enabled) ??
      all.find((d) => domainKey(d) === open) ??
      null)
    : null;
  const certs = certificates.data?.certificates ?? {};
  const checkList = checks.data?.checks ?? [];

  return (
    <>
      <Paper withBorder p={0} style={{ overflow: "hidden" }}>
        <Group
          justify="space-between"
          px="md"
          py="sm"
          gap="sm"
          style={{ borderBottom: "1px solid var(--color-neutral-800)" }}
        >
          <Group gap={8}>
            <Text fw={600}>{t("webservers.domains")}</Text>
            <Badge variant="light" color="gray">
              {formatNumber(shown.length, lang)}
            </Badge>
          </Group>
          <Group gap="sm">
            <TextInput
              size="xs"
              placeholder={t("webservers.search")}
              aria-label={t("webservers.search")}
              leftSection={<MagnifyingGlass size={14} />}
              value={search}
              onChange={(e) => setSearch(e.currentTarget.value)}
            />
            {disabled > 0 && (
              <SegmentedControl
                size="xs"
                value={filter}
                onChange={(v) => setFilter(v as Filter)}
                data={[
                  { value: "enabled", label: t("webservers.filter.enabled") },
                  {
                    value: "all",
                    label: t("webservers.filter.all", { n: formatNumber(disabled, lang) }),
                  },
                ]}
              />
            )}
          </Group>
        </Group>
        {shown.length === 0 ? (
          <Text c="dimmed" ta="center" p="lg">
            {all.length === 0 ? t("webservers.noSites") : t("webservers.noMatch")}
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={900}>
            <Table verticalSpacing="sm" layout="fixed" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th w="22%">{t("webservers.columns.domain")}</Table.Th>
                  <Table.Th w="9%">{t("webservers.columns.server")}</Table.Th>
                  <Table.Th w="8%">{t("webservers.columns.ports")}</Table.Th>
                  <Table.Th w="14%">{t("webservers.columns.https")}</Table.Th>
                  <Table.Th w="27%">{t("webservers.columns.serves")}</Table.Th>
                  <Table.Th w="20%">{t("webservers.columns.file")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {shown.map((d) => (
                  <DomainRow
                    key={`${d.server}-${d.enabled}-${d.name}`}
                    d={d}
                    certificates={certs}
                    check={checkFor(d, checkList)}
                    onOpen={() => setOpen(domainKey(d))}
                  />
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Paper>
      <WebSiteDrawer
        server={props.server}
        domain={opened}
        readOnly={props.readOnly}
        certificates={certs}
        monitored={Boolean(opened && checkFor(opened, checkList))}
        onClose={() => setOpen(null)}
        onCertificate={setCertFor}
        onMonitor={(url) =>
          checkActions.add.mutate(url, {
            onSuccess: () =>
              notifications.show({ color: "green", message: t("webservers.checks.added") }),
            onError: (error) =>
              notifications.show({ color: "red", message: errorMessage(t, error) }),
          })
        }
      />
      {certFor && (
        <CertbotModal
          opened
          onClose={() => setCertFor(null)}
          server={props.server}
          kind={certFor.server}
          domains={[
            ...new Set(certFor.sites.flatMap((s) => s.names).filter((n) => PLAIN_HOST.test(n))),
          ]}
          installed={certbot.data?.installed ?? true}
        />
      )}
    </>
  );
}

// --- health checks ---

function Spark({ check }: { check: WebCheck }) {
  const { t, i18n } = useTranslation();
  return (
    <Group gap={2} wrap="nowrap" aria-hidden>
      {check.recent.slice(-24).map((r) => (
        <Tooltip
          key={r.checked_at}
          label={`${formatDateTime(r.checked_at, i18n.language)} — ${
            r.code ?? t(`webservers.checks.errors.${r.error}`, { defaultValue: r.error ?? "" })
          }${r.ms !== null ? ` — ${r.ms} ms` : ""}`}
        >
          <span
            style={{
              width: 5,
              height: 18,
              borderRadius: 2,
              background: r.ok ? "var(--mantine-color-green-6)" : "var(--mantine-color-red-6)",
              display: "inline-block",
            }}
          />
        </Tooltip>
      ))}
    </Group>
  );
}

function ChecksTab({ server }: { server: ServerRef }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const checks = useWebChecks(server);
  const { add, toggle, remove, run } = useCheckMutations(server);
  const [url, setUrl] = useState("https://");
  const [confirm, setConfirm] = useState<WebCheck | null>(null);
  return (
    <Stack gap="md">
      <Paper withBorder p="md">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate(url.trim(), { onSuccess: () => setUrl("https://") });
          }}
        >
          <Group align="flex-end" gap="sm">
            <TextInput
              label={t("webservers.checks.url")}
              description={t("webservers.checks.urlHint")}
              value={url}
              onChange={(e) => setUrl(e.currentTarget.value)}
              dir="ltr"
              style={{ flex: 1, minWidth: 240 }}
            />
            <Button type="submit" loading={add.isPending} leftSection={<Plus size={14} />}>
              {t("webservers.checks.add")}
            </Button>
          </Group>
        </form>
        {add.isError && (
          <Alert color="red" mt="sm">
            {errorMessage(t, add.error)}
          </Alert>
        )}
      </Paper>
      {checks.isPending && <Loader />}
      {checks.isError && <Alert color="red">{errorMessage(t, checks.error)}</Alert>}
      {checks.data && checks.data.checks.length === 0 && (
        <Text c="dimmed" ta="center">
          {t("webservers.checks.empty")}
        </Text>
      )}
      {checks.data && checks.data.checks.length > 0 && (
        <Paper withBorder p={0} style={{ overflow: "hidden" }}>
          <Table.ScrollContainer minWidth={820}>
            <Table verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("webservers.checks.url")}</Table.Th>
                  <Table.Th>{t("webservers.checks.state")}</Table.Th>
                  <Table.Th>{t("webservers.checks.response")}</Table.Th>
                  <Table.Th>{t("webservers.checks.uptime")}</Table.Th>
                  <Table.Th>{t("webservers.checks.recent")}</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {checks.data.checks.map((c) => (
                  <Table.Tr
                    key={c.id}
                    data-testid={`check-${c.url}`}
                    style={{ opacity: c.enabled ? 1 : 0.6 }}
                  >
                    <Table.Td>
                      <Text size="sm" dir="ltr" ta="start" style={{ overflowWrap: "anywhere" }}>
                        {c.url}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {c.last_checked_at
                          ? formatDateTime(c.last_checked_at, lang)
                          : t("webservers.checks.never")}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge
                        color={
                          c.status === "down"
                            ? "red"
                            : c.status === "up"
                              ? c.failures
                                ? "orange"
                                : "green"
                              : "gray"
                        }
                        variant="light"
                      >
                        {c.status
                          ? t(`webservers.checks.status.${c.status}`)
                          : t("webservers.checks.status.pending")}
                      </Badge>
                      {c.status === "down" && c.down_since && (
                        <Text size="xs" c="dimmed">
                          {t("webservers.checks.downSince", {
                            time: formatDateTime(c.down_since, lang),
                          })}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" dir="ltr">
                        {c.last_code ??
                          (c.last_error
                            ? t(`webservers.checks.errors.${c.last_error}`, {
                                defaultValue: c.last_error,
                              })
                            : "—")}
                        {c.last_ms !== null && ` · ${c.last_ms} ms`}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      {c.uptime !== null ? `${formatNumber(c.uptime, lang)}%` : "—"}
                    </Table.Td>
                    <Table.Td>
                      <Spark check={c} />
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap" justify="flex-end">
                        <Tooltip label={t("webservers.checks.runNow")}>
                          <ActionIcon
                            variant="subtle"
                            aria-label={`${t("webservers.checks.runNow")} ${c.url}`}
                            loading={run.isPending && run.variables === c.id}
                            onClick={() => run.mutate(c.id)}
                          >
                            <Play size={16} />
                          </ActionIcon>
                        </Tooltip>
                        <Switch
                          size="xs"
                          checked={c.enabled}
                          aria-label={t("webservers.checks.enabled")}
                          onChange={(e) =>
                            toggle.mutate({ id: c.id, enabled: e.currentTarget.checked })
                          }
                        />
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label={`${t("common.delete")} ${c.url}`}
                          onClick={() => setConfirm(c)}
                        >
                          <Trash size={16} />
                        </ActionIcon>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      <Text size="xs" c="dimmed">
        {t("webservers.checks.hint")}
      </Text>
      <ConfirmDialog
        opened={confirm !== null}
        title={t("webservers.checks.delete")}
        body={confirm?.url ?? ""}
        confirmLabel={t("common.delete")}
        loading={remove.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() =>
          confirm && remove.mutate(confirm.id, { onSettled: () => setConfirm(null) })
        }
      />
    </Stack>
  );
}

// --- the audit log ---

function ActivityTab({ server }: { server: ServerRef }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const [page, setPage] = useState(1);
  const actions = useWebActions(server, page);
  const [shown, setShown] = useState<WebActionItem | null>(null);
  if (actions.isPending) return <Loader />;
  if (actions.isError) return <Alert color="red">{errorMessage(t, actions.error)}</Alert>;
  const { items, total, page_size } = actions.data;
  return (
    <Paper withBorder p="md">
      {items.length === 0 ? (
        <Text c="dimmed" ta="center">
          {t("webservers.activity.empty")}
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={760}>
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("webservers.activity.time")}</Table.Th>
                <Table.Th>{t("webservers.activity.action")}</Table.Th>
                <Table.Th>{t("webservers.activity.target")}</Table.Th>
                <Table.Th>{t("webservers.activity.by")}</Table.Th>
                <Table.Th>{t("webservers.activity.result")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((item) => (
                <Table.Tr
                  key={item.id}
                  style={{ cursor: item.output ? "pointer" : undefined }}
                  onClick={() => item.output && setShown(item)}
                >
                  <Table.Td>{formatDateTime(item.created_at, lang)}</Table.Td>
                  <Table.Td>
                    {t(`webservers.activity.actions.${item.action}`, {
                      defaultValue: item.action,
                    })}
                    <Text size="xs" c="dimmed">
                      {KIND_LABEL[item.kind as WebServerKind] ?? item.kind}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" dir="ltr" ta="start" style={{ overflowWrap: "anywhere" }}>
                      {item.target || "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{item.actor}</Text>
                    <Text size="xs" c="dimmed">
                      {t(`webservers.activity.sources.${item.source}`, {
                        defaultValue: item.source,
                      })}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge
                      color={
                        item.result === "ok" ? "green" : item.result === "running" ? "blue" : "red"
                      }
                      variant="light"
                    >
                      {item.result === "ok"
                        ? t("webservers.activity.ok")
                        : item.result === "running"
                          ? t("webservers.job.running")
                          : t(`webservers.result.${item.result}`, {
                              defaultValue: t(`errors.${item.result}`, {
                                defaultValue: item.result,
                              }),
                            })}
                    </Badge>
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
      <Modal
        opened={shown !== null}
        onClose={() => setShown(null)}
        title={t("webservers.activity.output")}
        size="lg"
      >
        <Code block dir="ltr" style={{ maxHeight: "60vh", overflow: "auto" }}>
          {shown?.output}
        </Code>
      </Modal>
    </Paper>
  );
}

// --- settings ---

function SettingsTab({ server }: { server: ServerRef }) {
  const { t } = useTranslation();
  const settings = useWebSettings(server);
  const save = useSaveWebSettings(server);
  const [values, setValues] = useState<WebSettings | null>(null);
  useEffect(() => {
    if (settings.data && values === null) setValues(settings.data);
  }, [settings.data, values]);
  if (settings.isError) return <Alert color="red">{errorMessage(t, settings.error)}</Alert>;
  if (!values) return <Loader />;
  const set = <K extends keyof WebSettings>(key: K, value: WebSettings[K]) =>
    setValues((prev) => (prev ? { ...prev, [key]: value } : prev));
  const numbers: [keyof WebSettings, number, number][] = [
    ["cert_warning_days", 0, 90],
    ["check_interval_minutes", 1, 1440],
    ["check_timeout_seconds", 1, 60],
    ["check_failures", 1, 20],
  ];
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(values, {
          onSuccess: (data) => {
            setValues(data);
            notifications.show({ color: "green", message: t("webservers.settings.saved") });
          },
        });
      }}
    >
      <Stack gap="md">
        <Paper withBorder p="lg">
          <Stack gap="md">
            <Switch
              label={t("webservers.settings.readOnly")}
              description={t("webservers.settings.readOnlyHint")}
              checked={values.read_only}
              onChange={(e) => set("read_only", e.currentTarget.checked)}
            />
            <TextInput
              label={t("webservers.settings.acmeEmail")}
              description={t("webservers.settings.acmeEmailHint")}
              value={values.acme_email ?? ""}
              onChange={(e) => set("acme_email", e.currentTarget.value || null)}
              dir="ltr"
            />
          </Stack>
        </Paper>
        <Paper withBorder p="lg">
          <Title order={4} mb="sm">
            {t("webservers.settings.alerts")}
          </Title>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            {numbers.map(([key, min, max]) => (
              <NumberInput
                key={key}
                label={t(`webservers.settings.${key}`)}
                min={min}
                max={max}
                value={values[key] as number}
                onChange={(v) => set(key, (typeof v === "number" ? v : min) as never)}
              />
            ))}
          </SimpleGrid>
          <Text size="xs" c="dimmed" mt="sm">
            {t("webservers.settings.alertsHint")}
          </Text>
        </Paper>
        {save.isError && <Alert color="red">{errorMessage(t, save.error)}</Alert>}
        <Group justify="flex-end">
          <Button type="submit" loading={save.isPending}>
            {t("common.save")}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

// --- the page ---

function Overview({ server }: { server: ServerRef }) {
  const { t } = useTranslation();
  const list = useWebServers(server);
  const available = Boolean(list.data?.available && list.data.servers.length);
  const status = useWebStatus(server, available);
  const settings = useWebSettings(server);
  const containers = useContainers(server, available);
  const readOnly = settings.data?.read_only ?? false;
  const [creating, setCreating] = useState(false);
  const servers = list.data?.servers ?? [];
  const kinds = servers.filter((s) => !s.error).map((s) => s.kind);
  const targets = useMemo(
    () =>
      (containers.data?.containers ?? []).flatMap((c) =>
        c.ports
          .filter((p) => p.public)
          .map((p) => ({
            value: `http://127.0.0.1:${p.public}`,
            label: `${c.name} — 127.0.0.1:${p.public} → ${p.private}`,
          })),
      ),
    [containers.data],
  );

  if (list.isPending) return <Loader />;
  if (list.isError) return <AgentProblem error={list.error} />;
  if (!list.data.available) return <NotMounted />;
  if (servers.length === 0) {
    return (
      <SetupHelp title={t("webservers.noneTitle")}>
        <Text size="sm">{t("webservers.none")}</Text>
      </SetupHelp>
    );
  }
  return (
    <Stack gap={18}>
      <Group justify="space-between">
        {readOnly ? (
          <Badge color="gray" variant="light" leftSection={<Lock size={12} />}>
            {t("webservers.readOnly")}
          </Badge>
        ) : (
          <span />
        )}
        <Group gap="xs">
          <Button
            variant="default"
            onClick={() => list.refetch()}
            loading={list.isFetching}
            leftSection={<ArrowClockwise size={14} />}
          >
            {t("webservers.reload")}
          </Button>
          <Button
            leftSection={<Plus size={16} />}
            disabled={readOnly || kinds.length === 0}
            onClick={() => setCreating(true)}
          >
            {t("webservers.new.button")}
          </Button>
        </Group>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing={12}>
        {servers.map((ws) => (
          <ServiceCard
            key={ws.kind}
            ws={ws}
            status={status.data?.servers.find((s) => s.kind === ws.kind)}
            statusError={status.error}
            server={server}
            readOnly={readOnly}
          />
        ))}
        <CertbotCard server={server} kind={kinds[0] ?? "nginx"} readOnly={readOnly} />
      </SimpleGrid>
      <Tabs defaultValue="sites" keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="sites" leftSection={<Globe size={16} />}>
            {t("webservers.tabs.sites")}
          </Tabs.Tab>
          <Tabs.Tab value="checks" leftSection={<Play size={16} />}>
            {t("webservers.tabs.checks")}
          </Tabs.Tab>
          <Tabs.Tab value="activity" leftSection={<ClockCountdown size={16} />}>
            {t("webservers.tabs.activity")}
          </Tabs.Tab>
          <Tabs.Tab value="settings" leftSection={<GearSix size={16} />}>
            {t("webservers.tabs.settings")}
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="sites">
          <SitesTab server={server} servers={servers} readOnly={readOnly} />
        </Tabs.Panel>
        <Tabs.Panel value="checks">
          <ChecksTab server={server} />
        </Tabs.Panel>
        <Tabs.Panel value="activity">
          <ActivityTab server={server} />
        </Tabs.Panel>
        <Tabs.Panel value="settings">
          <SettingsTab server={server} />
        </Tabs.Panel>
      </Tabs>
      <NewSiteModal
        opened={creating}
        onClose={() => setCreating(false)}
        server={server}
        kinds={kinds}
        targets={targets}
      />
    </Stack>
  );
}

export function WebServersPage() {
  const { t } = useTranslation();
  const server = useCurrentServer().id;
  return (
    <Stack gap={18}>
      <PageHeader
        help="webservers"
        title={t("webservers.title")}
        badge={<ServerBadge />}
        subtitle={t("webservers.subtitle")}
      />
      <Overview key={server ?? 0} server={server} />
    </Stack>
  );
}
