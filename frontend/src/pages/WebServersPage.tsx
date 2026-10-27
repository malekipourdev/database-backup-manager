import {
  Alert,
  Anchor,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { errorMessage, isApiError } from "../api/client";
import {
  type Domain,
  type WebServer,
  type WebSite,
  domainsOf,
  servedBy,
  useWebServers,
} from "../api/webservers";
import { Globe, Lock, MagnifyingGlass, Warning } from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { ServerBadge } from "../components/ServerBadge";
import { formatNumber } from "../i18n";
import { useCurrentServer } from "../server/CurrentServer";

type Filter = "enabled" | "all";
const KIND_LABEL = { nginx: "nginx", apache: "Apache" } as const;
const PLAIN_HOST = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/i;

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

function ServerCard({ ws }: { ws: WebServer }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const enabled = ws.sites.filter((s) => s.enabled).length;
  return (
    <Paper withBorder p="md" data-testid={`webserver-${ws.kind}`}>
      <Stack gap={8}>
        <Group justify="space-between" wrap="nowrap">
          <Group gap={8} wrap="nowrap">
            <Globe size={18} />
            <Text fw={600}>{KIND_LABEL[ws.kind]}</Text>
          </Group>
          {ws.error ? (
            <Badge color="red" variant="light">
              {t("webservers.unreadable")}
            </Badge>
          ) : (
            <Badge color="teal" variant="light">
              {t("webservers.sitesCount", { n: formatNumber(enabled, lang) })}
            </Badge>
          )}
        </Group>
        <div className="cl-kv">
          <span>{t("webservers.config")}</span>
          <code dir="ltr">{ws.config}</code>
        </div>
        <div className="cl-kv">
          <span>{t("webservers.filesRead")}</span>
          <span>{formatNumber(ws.files, lang)}</span>
        </div>
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
      </Stack>
    </Paper>
  );
}

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

function DomainRow({ d }: { d: Domain }) {
  const { t } = useTranslation();
  const site = servedBy(d);
  const files = [...new Set(d.sites.map((s) => `${s.file}:${s.line}`))];
  const redirectsToHttps = d.sites.some((s) => !s.ssl && s.redirect?.startsWith("https://"));
  return (
    <Table.Tr
      data-testid={`domain-${d.name || "catch-all"}`}
      style={{ opacity: d.enabled ? 1 : 0.6 }}
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
            >
              {d.name}
            </Anchor>
          ) : (
            <Text size="sm" dir="ltr" ta="start" style={{ overflowWrap: "anywhere" }}>
              {d.name}
            </Text>
          )}
          <Group gap={4}>
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
        {d.ssl ? (
          <Tooltip
            label={d.sites.find((s) => s.certificate)?.certificate ?? t("webservers.https")}
            disabled={!d.sites.some((s) => s.certificate)}
          >
            <Badge color="teal" variant="light" leftSection={<Lock size={11} />}>
              {redirectsToHttps ? t("webservers.httpsForced") : t("webservers.https")}
            </Badge>
          </Tooltip>
        ) : (
          <Badge color="orange" variant="light">
            {t("webservers.httpOnly")}
          </Badge>
        )}
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

function Domains({ servers }: { servers: WebServer[] }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const [filter, setFilter] = useState<Filter>("enabled");
  const [search, setSearch] = useState("");
  const all = useMemo(() => domainsOf(servers), [servers]);
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

  return (
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
        <Table.ScrollContainer minWidth={860}>
          <Table verticalSpacing="sm" layout="fixed" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w="22%">{t("webservers.columns.domain")}</Table.Th>
                <Table.Th w="9%">{t("webservers.columns.server")}</Table.Th>
                <Table.Th w="9%">{t("webservers.columns.ports")}</Table.Th>
                <Table.Th w="13%">{t("webservers.columns.https")}</Table.Th>
                <Table.Th w="27%">{t("webservers.columns.serves")}</Table.Th>
                <Table.Th w="20%">{t("webservers.columns.file")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {shown.map((d) => (
                <DomainRow key={`${d.server}-${d.enabled}-${d.name}`} d={d} />
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Paper>
  );
}

export function WebServersPage() {
  const { t } = useTranslation();
  const server = useCurrentServer().id;
  const list = useWebServers(server);
  return (
    <Stack gap={18}>
      <PageHeader
        help="webservers"
        title={t("webservers.title")}
        badge={<ServerBadge />}
        subtitle={t("webservers.subtitle")}
        actions={
          <Button variant="light" onClick={() => list.refetch()} loading={list.isFetching}>
            {t("webservers.reload")}
          </Button>
        }
      />
      {list.isPending && <Loader />}
      {list.isError && <AgentProblem error={list.error} />}
      {list.data && !list.data.available && <NotMounted />}
      {list.data?.available && list.data.servers.length === 0 && (
        <SetupHelp title={t("webservers.noneTitle")}>
          <Text size="sm">{t("webservers.none")}</Text>
        </SetupHelp>
      )}
      {list.data?.available && list.data.servers.length > 0 && (
        <>
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing={12}>
            {list.data.servers.map((ws) => (
              <ServerCard key={ws.kind} ws={ws} />
            ))}
          </SimpleGrid>
          <Domains servers={list.data.servers} />
        </>
      )}
    </Stack>
  );
}
