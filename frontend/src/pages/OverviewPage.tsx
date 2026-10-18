import { Alert, Button, Loader, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useRunHistory } from "../api/backups";
import { errorMessage } from "../api/client";
import { useContainers, useServerInfo } from "../api/containers";
import { useInstances } from "../api/instances";
import { useProjects } from "../api/projects";
import { DeployStatusBadge } from "../components/DeployStatusBadge";
import {
  Archive,
  CheckCircle,
  Cube,
  Database,
  HardDrives,
  Plus,
  RocketLaunch,
  Warning,
} from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { RunStatusBadge } from "../components/RunStatusBadge";
import { ServerBadge } from "../components/ServerBadge";
import { ServerDot } from "../components/ServerSwitcher";
import { formatBytes } from "../format";
import { formatDateTime, formatNumber, formatPercent } from "../i18n";
import { useCurrentServer } from "../server/CurrentServer";

const DAY_MS = 24 * 60 * 60 * 1000;

function Tile(props: {
  to: string;
  icon: ReactNode;
  label: string;
  value: ReactNode;
  note: ReactNode;
  testId?: string;
}) {
  return (
    <Link to={props.to} className="cl-stat cl-stat-link" data-testid={props.testId}>
      <span className="cl-stat-label">
        {props.icon}
        <span>{props.label}</span>
      </span>
      <span className="cl-stat-value">{props.value}</span>
      <span className="cl-stat-note">{props.note}</span>
    </Link>
  );
}

function Section(props: { id: string; title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <Paper withBorder p="md" component="section" aria-labelledby={props.id}>
      <div className="cl-section-head">
        <Title order={2} size="h5" id={props.id}>
          {props.title}
        </Title>
        {props.action}
      </div>
      {props.children}
    </Paper>
  );
}

interface AttentionItem {
  key: string;
  tone: "bad" | "warn";
  text: string;
  to: string;
}

/**
 * The current server at a glance: its health, the last day's backups, its containers and
 * projects, and everything that needs a look, each linking to the page that deals with it.
 */
export function OverviewPage() {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const { server, id: serverId } = useCurrentServer();
  // Fixed while the page is open, so the query (and its cache key) stays the same.
  const [since] = useState(() => new Date(Date.now() - DAY_MS).toISOString());
  const lastDay = useRunHistory({ server: serverId, from: since, page: 1, pageSize: 200 });
  const recent = useRunHistory({ server: serverId, page: 1, pageSize: 6 });
  const info = useServerInfo(serverId, Boolean(server?.paired));
  const containers = useContainers(serverId, Boolean(server?.paired));
  const projects = useProjects();
  const instances = useInstances();

  const n = (value: number) => formatNumber(value, lang);
  const runs = lastDay.data?.items ?? [];
  const count = (...statuses: string[]) => runs.filter((r) => statuses.includes(r.status)).length;
  const failedRuns = count("failed");
  const list = containers.data?.containers ?? [];
  const running = list.filter((c) => c.state === "running").length;
  const problems = list.filter((c) => c.problem);
  const failedDeploys = (projects.data ?? []).filter((p) => p.last_deployment?.status === "failed");
  const host = info.data?.host;
  const percentUsed = (total?: number | null, free?: number | null) =>
    total && free !== null && free !== undefined ? ((total - free) * 100) / total : null;
  const memory = percentUsed(host?.memory_total, host?.memory_available);
  const disk = percentUsed(host?.disk_total, host?.disk_free);

  const attention: AttentionItem[] = [];
  if (server?.last_error) {
    attention.push({
      key: "server",
      tone: "bad",
      text: t("overview.attention.server", { name: server.name, error: server.last_error }),
      to: "/servers",
    });
  }
  if (failedRuns > 0) {
    attention.push({
      key: "runs",
      tone: "bad",
      text: t("overview.attention.backups", { count: failedRuns, n: n(failedRuns) }),
      to: "/backups",
    });
  }
  for (const c of problems) {
    attention.push({
      key: `container:${c.name}`,
      tone: c.problem === "unhealthy" ? "warn" : "bad",
      text: t("overview.attention.container", {
        name: c.name,
        problem: t(`containers.problem.${c.problem}`),
      }),
      to: "/containers",
    });
  }
  if (containers.isError) {
    attention.push({
      key: "containers",
      tone: "warn",
      text: t("overview.attention.containersUnavailable", {
        reason: errorMessage(t, containers.error),
      }),
      to: "/containers",
    });
  }
  for (const p of failedDeploys) {
    attention.push({
      key: `project:${p.id}`,
      tone: "bad",
      text: t("overview.attention.deploy", { name: p.name }),
      to: `/projects/${p.id}`,
    });
  }
  for (const instance of instances.data ?? []) {
    if (instance.last_test_ok === false) {
      attention.push({
        key: `instance:${instance.id}`,
        tone: "warn",
        text: t("overview.attention.database", { name: instance.name }),
        to: `/instances/${instance.id}`,
      });
    }
  }
  const checking = lastDay.isPending || projects.isPending || instances.isPending;

  const deploys = (projects.data ?? [])
    .filter((p) => p.last_deployment)
    .sort((a, b) => b.last_deployment!.requested_at.localeCompare(a.last_deployment!.requested_at))
    .slice(0, 5);

  return (
    <Stack gap={18}>
      <PageHeader
        help="overview"
        title={t("overview.title")}
        badge={<ServerBadge />}
        subtitle={t("overview.subtitle")}
        actions={
          <>
            <Button
              component={Link}
              to="/instances/new"
              leftSection={<Plus size={16} aria-hidden />}
            >
              {t("overview.addDatabase")}
            </Button>
            <Button
              component={Link}
              to="/projects/new"
              variant="subtle"
              leftSection={<Plus size={16} aria-hidden />}
            >
              {t("overview.addProject")}
            </Button>
          </>
        }
      />

      <SimpleGrid cols={{ base: 1, xs: 2, lg: 4 }} spacing={12}>
        <Tile
          to="/servers"
          testId="tile-server"
          icon={<HardDrives size={15} aria-hidden />}
          label={t("overview.server")}
          value={
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              {server && <ServerDot server={server} />}
              <span className="cl-truncate">{server?.name ?? t("common.notAvailable")}</span>
            </span>
          }
          note={
            host
              ? t("overview.serverUsage", {
                  cpu: host.cpu_percent === null ? "—" : formatPercent(host.cpu_percent, lang),
                  memory: memory === null ? "—" : formatPercent(memory, lang),
                  disk: disk === null ? "—" : formatPercent(disk, lang),
                })
              : info.isError
                ? t("overview.serverUsageUnavailable")
                : server?.docker_version
                  ? t("overview.docker", { version: server.docker_version })
                  : t("common.notAvailable")
          }
        />
        <Tile
          to="/backups"
          testId="tile-backups"
          icon={<Archive size={15} aria-hidden />}
          label={t("overview.backups")}
          value={lastDay.data ? n(count("success")) : "…"}
          note={t("overview.backupsNote", {
            failed: n(failedRuns),
            running: n(count("running", "queued")),
          })}
        />
        <Tile
          to="/containers"
          testId="tile-containers"
          icon={<Cube size={15} aria-hidden />}
          label={t("overview.containers")}
          value={
            containers.data
              ? t("overview.containersValue", { running: n(running), total: n(list.length) })
              : containers.isError
                ? t("overview.unavailable")
                : "…"
          }
          note={
            problems.length
              ? t("overview.containersProblems", { count: problems.length, n: n(problems.length) })
              : containers.data
                ? t("overview.containersOk")
                : t("overview.containersHint")
          }
        />
        <Tile
          to="/projects"
          testId="tile-projects"
          icon={<RocketLaunch size={15} aria-hidden />}
          label={t("overview.projects")}
          value={projects.data ? n(projects.data.length) : "…"}
          note={
            failedDeploys.length
              ? t("overview.projectsFailed", {
                  count: failedDeploys.length,
                  n: n(failedDeploys.length),
                })
              : t("overview.projectsNote", { n: n(instances.data?.length ?? 0) })
          }
        />
      </SimpleGrid>

      <Section id="overview-attention" title={t("overview.attention.title")}>
        {checking ? (
          <Loader size="sm" aria-label={t("common.loading")} />
        ) : attention.length === 0 ? (
          <Text size="sm" className="cl-all-good">
            <CheckCircle size={18} aria-hidden />
            {t("overview.attention.none")}
          </Text>
        ) : (
          <ul className="cl-attention" aria-live="polite">
            {attention.map((item) => (
              <li key={item.key} data-tone={item.tone}>
                <Warning size={16} aria-hidden />
                <Link to={item.to}>{item.text}</Link>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing={12}>
        <Section
          id="overview-backups"
          title={t("overview.recentBackups")}
          action={
            <Button component={Link} to="/backups" variant="subtle" size="compact-sm">
              {t("overview.viewAll")}
            </Button>
          }
        >
          {recent.isError && <Alert color="red">{errorMessage(t, recent.error)}</Alert>}
          {recent.data && recent.data.items.length === 0 && (
            <Text size="sm" c="dimmed">
              {t("overview.noBackups")}
            </Text>
          )}
          {recent.data && recent.data.items.length > 0 && (
            <ul className="cl-activity">
              {recent.data.items.map((run) => (
                <li key={run.id}>
                  <Database size={16} aria-hidden />
                  <span className="cl-activity-main">
                    <span className="cl-truncate">{run.database_name}</span>
                    <span className="cl-activity-meta">
                      {run.instance_name} · {formatDateTime(run.requested_at, lang)}
                      {run.file_size !== null && ` · ${formatBytes(run.file_size, t, lang)}`}
                    </span>
                  </span>
                  <RunStatusBadge status={run.status} />
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section
          id="overview-deploys"
          title={t("overview.recentDeploys")}
          action={
            <Button component={Link} to="/projects" variant="subtle" size="compact-sm">
              {t("overview.viewAll")}
            </Button>
          }
        >
          {projects.isError && <Alert color="red">{errorMessage(t, projects.error)}</Alert>}
          {projects.data && deploys.length === 0 && (
            <Text size="sm" c="dimmed">
              {t("overview.noDeploys")}
            </Text>
          )}
          {deploys.length > 0 && (
            <ul className="cl-activity">
              {deploys.map((p) => (
                <li key={p.id}>
                  <RocketLaunch size={16} aria-hidden />
                  <span className="cl-activity-main">
                    <Link to={`/projects/${p.id}`} className="cl-truncate">
                      {p.name}
                    </Link>
                    <span className="cl-activity-meta">
                      <span dir="ltr">
                        {p.last_deployment!.commit_sha?.slice(0, 8) ?? p.last_deployment!.ref}
                      </span>{" "}
                      · {formatDateTime(p.last_deployment!.requested_at, lang)}
                    </span>
                  </span>
                  <DeployStatusBadge d={p.last_deployment!} />
                </li>
              ))}
            </ul>
          )}
        </Section>
      </SimpleGrid>
    </Stack>
  );
}
