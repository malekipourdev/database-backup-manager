import {
  Alert,
  Badge,
  Button,
  Collapse,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  TextInput,
  UnstyledButton,
} from "@mantine/core";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { errorMessage } from "../api/client";
import { type Project, useProjects } from "../api/projects";
import { DeployStatusBadge } from "../components/DeployStatusBadge";
import { CaretDown, Folder, MagnifyingGlass, Plus, RocketLaunch } from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { ServerBadge } from "../components/ServerBadge";
import { formatDateTime, formatNumber } from "../i18n";

const CLOSED_KEY = "mbp.projects.closed";

function readClosed(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(CLOSED_KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((v) => typeof v === "string") : [];
  } catch {
    return []; // storage can be unavailable: every folder starts open
  }
}

function storeClosed(closed: string[]): void {
  try {
    localStorage.setItem(CLOSED_KEY, JSON.stringify(closed));
  } catch {
    // Remembering which folders are closed is a convenience only.
  }
}

function Grid({ projects }: { projects: Project[] }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(270px, 1fr))",
        gap: 12,
      }}
    >
      {projects.map((project) => (
        <ProjectCard key={project.id} project={project} />
      ))}
    </div>
  );
}

/** One folder: a heading that opens and closes it, and its projects. */
function FolderSection(props: {
  name: string;
  projects: Project[];
  open: boolean;
  onToggle: () => void;
}) {
  const { t, i18n } = useTranslation();
  const id = `folder-${props.name || "none"}`;
  return (
    <Stack gap={10} data-testid={id}>
      <UnstyledButton
        onClick={props.onToggle}
        aria-expanded={props.open}
        aria-controls={`${id}-items`}
        style={{ display: "flex", alignItems: "center", gap: 8 }}
      >
        <CaretDown
          size={14}
          style={{
            transform: props.open ? undefined : "rotate(-90deg)",
            transition: "transform 120ms",
          }}
          aria-hidden
        />
        <Folder size={18} aria-hidden />
        <Text fw={600}>{props.name || t("projects.noFolder")}</Text>
        <Badge variant="light" color="gray">
          {formatNumber(props.projects.length, i18n.language)}
        </Badge>
      </UnstyledButton>
      <Collapse in={props.open} id={`${id}-items`}>
        <Grid projects={props.projects} />
      </Collapse>
    </Stack>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const { t, i18n } = useTranslation();
  const last = project.last_deployment;
  return (
    <Link
      to={`/projects/${project.id}`}
      className="cl-card"
      data-testid={`project-${project.name}`}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span className="cl-icon-tile">
          <RocketLaunch size={20} />
        </span>
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 3 }}>
          <Text fw={500} truncate dir="ltr" ta="start">
            {project.name}
          </Text>
          <Text size="xs" c="var(--color-neutral-500)" dir="ltr" ta="start" truncate>
            {project.repo_url}
          </Text>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div className="cl-kv">
          <span>{t("projects.fields.server")}</span>
          <span>{project.server_name}</span>
        </div>
        <div className="cl-kv">
          <span>{t("projects.fields.branch")}</span>
          <code dir="ltr">{project.branch}</code>
        </div>
        <div className="cl-kv">
          <span>{t("projects.current")}</span>
          <code dir="ltr">{project.last_success?.commit_sha?.slice(0, 8) ?? "—"}</code>
        </div>
      </div>
      <div className="cl-card-foot">
        {last ? (
          <>
            <DeployStatusBadge d={last} />
            <Text size="xs" c="var(--color-neutral-500)">
              {formatDateTime(last.requested_at, i18n.language)}
            </Text>
          </>
        ) : (
          <Badge color="gray" variant="light">
            {t("projects.never")}
          </Badge>
        )}
      </div>
    </Link>
  );
}

export function ProjectsPage() {
  const { t } = useTranslation();
  const projects = useProjects();
  const [search, setSearch] = useState("");
  const [closed, setClosed] = useState<string[]>(readClosed);
  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const shown = (projects.data ?? []).filter(
      (p) =>
        !needle ||
        `${p.name} ${p.repo_url} ${p.folder ?? ""} ${p.server_name}`.toLowerCase().includes(needle),
    );
    const byFolder = new Map<string, Project[]>();
    for (const p of shown)
      byFolder.set(p.folder ?? "", [...(byFolder.get(p.folder ?? "") ?? []), p]);
    return [...byFolder.entries()].sort(([a], [b]) =>
      a === "" ? 1 : b === "" ? -1 : a.localeCompare(b),
    );
  }, [projects.data, search]);
  const hasFolders = (projects.data ?? []).some((p) => p.folder);
  const toggle = (name: string) => {
    const next = closed.includes(name) ? closed.filter((c) => c !== name) : [...closed, name];
    setClosed(next);
    storeClosed(next);
  };
  return (
    <Stack gap={18}>
      <PageHeader
        help="projects-overview"
        title={t("projects.title")}
        badge={<ServerBadge />}
        subtitle={t("projects.subtitle")}
        actions={
          <Button component={Link} to="/projects/new" leftSection={<Plus size={16} />}>
            {t("projects.add")}
          </Button>
        }
      />
      {projects.isPending && <Loader />}
      {projects.isError && <Alert color="red">{errorMessage(t, projects.error)}</Alert>}
      {projects.data && projects.data.length === 0 && (
        <Paper withBorder p="xl">
          <Stack align="center" gap="xs">
            <span className="cl-icon-tile">
              <RocketLaunch size={20} />
            </span>
            <Text fw={500}>{t("projects.empty")}</Text>
            <Text c="dimmed" size="sm" ta="center" maw={520}>
              {t("projects.emptyHint")}
            </Text>
          </Stack>
        </Paper>
      )}
      {projects.data && projects.data.length > 0 && (
        <>
          {projects.data.length > 6 && (
            <Group>
              <TextInput
                placeholder={t("projects.search")}
                aria-label={t("projects.search")}
                leftSection={<MagnifyingGlass size={14} />}
                value={search}
                onChange={(e) => setSearch(e.currentTarget.value)}
                w={320}
              />
            </Group>
          )}
          {groups.length === 0 && <Text c="dimmed">{t("projects.noMatch")}</Text>}
          {hasFolders
            ? groups.map(([name, items]) => (
                <FolderSection
                  key={name || "-"}
                  name={name}
                  projects={items}
                  open={Boolean(search.trim()) || !closed.includes(name)}
                  onToggle={() => toggle(name)}
                />
              ))
            : groups.map(([name, items]) => <Grid key={name || "-"} projects={items} />)}
        </>
      )}
    </Stack>
  );
}
