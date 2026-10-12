import { Alert, Badge, Button, Loader, Paper, Stack, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { errorMessage } from "../api/client";
import { type Project, useProjects } from "../api/projects";
import { DeployStatusBadge } from "../components/DeployStatusBadge";
import { Plus, RocketLaunch } from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { ServerBadge } from "../components/ServerBadge";
import { formatDateTime } from "../i18n";

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
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(270px, 1fr))",
            gap: 12,
          }}
        >
          {projects.data.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
    </Stack>
  );
}
