import {
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Pagination,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { errorMessage } from "../api/client";
import { useContainers } from "../api/containers";
import {
  type Project,
  isActive,
  useDeleteProject,
  useDeploy,
  useDeployments,
  useProject,
  useProjectState,
} from "../api/projects";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ContainerStateBadge } from "../components/ContainerStateBadge";
import { DeploymentDrawer } from "../components/DeploymentDrawer";
import { DeployStatusBadge } from "../components/DeployStatusBadge";
import { PencilSimple, RocketLaunch, Trash } from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { formatDuration } from "../format";
import { formatDateTime } from "../i18n";

function Services({ project }: { project: Project }) {
  const { t } = useTranslation();
  const containers = useContainers(project.server_id);
  const mine = (containers.data?.containers ?? []).filter((c) => c.project === project.name);
  return (
    <Paper withBorder p="lg">
      <Group justify="space-between" mb="sm">
        <Title order={4}>{t("projects.services")}</Title>
        <Anchor component={Link} to={`/containers?server=${project.server_id}`} size="sm">
          {t("projects.allContainers")}
        </Anchor>
      </Group>
      {containers.isError && (
        <Text size="sm" c="dimmed">
          {errorMessage(t, containers.error)}
        </Text>
      )}
      {containers.data && mine.length === 0 && (
        <Text size="sm" c="dimmed">
          {t("projects.noServices")}
        </Text>
      )}
      <Stack gap={6}>
        {mine.map((c) => (
          <Group key={c.id} justify="space-between" wrap="nowrap">
            <Text size="sm" dir="ltr" truncate>
              {c.service ?? c.name}
            </Text>
            <ContainerStateBadge c={c} />
          </Group>
        ))}
      </Stack>
    </Paper>
  );
}

function Deployments(props: { project: Project; onOpen: (id: number) => void }) {
  const { t, i18n } = useTranslation();
  const [page, setPage] = useState(1);
  const live = isActive(props.project.last_deployment);
  const list = useDeployments(props.project.id, page, live);
  if (list.isPending) return <Loader />;
  if (list.isError) return <Alert color="red">{errorMessage(t, list.error)}</Alert>;
  const { items, total, page_size } = list.data;
  return (
    <Paper withBorder p="lg">
      <Title order={4} mb="sm">
        {t("projects.history")}
      </Title>
      {items.length === 0 ? (
        <Text c="dimmed" size="sm">
          {t("projects.never")}
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={680}>
          <Table highlightOnHover verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("projects.columns.status")}</Table.Th>
                <Table.Th>{t("projects.columns.commit")}</Table.Th>
                <Table.Th>{t("projects.columns.by")}</Table.Th>
                <Table.Th>{t("projects.columns.time")}</Table.Th>
                <Table.Th>{t("projects.columns.duration")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((d) => (
                <Table.Tr
                  key={d.id}
                  onClick={() => props.onOpen(d.id)}
                  style={{ cursor: "pointer" }}
                  data-testid={`deployment-${d.id}`}
                >
                  <Table.Td>
                    <DeployStatusBadge d={d} />
                  </Table.Td>
                  <Table.Td maw={320}>
                    <Text size="sm" dir="ltr" ta="start">
                      {d.commit_sha ? d.commit_sha.slice(0, 8) : d.ref}
                    </Text>
                    {d.commit_message && (
                      <Text size="xs" c="dimmed" truncate>
                        {d.commit_message}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{d.actor}</Text>
                    <Text size="xs" c="dimmed">
                      {t(`containers.activity.sources.${d.trigger}`, { defaultValue: d.trigger })}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{formatDateTime(d.requested_at, i18n.language)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {d.started_at && d.finished_at
                        ? formatDuration(
                            new Date(d.finished_at).getTime() - new Date(d.started_at).getTime(),
                            t,
                            i18n.language,
                          )
                        : "—"}
                    </Text>
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

export function ProjectDetailPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const id = Number(useParams().id);
  const project = useProject(id);
  const state = useProjectState(id);
  const deploy = useDeploy(id);
  const remove = useDeleteProject();
  const [confirm, setConfirm] = useState<{ ref: string | null } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [down, setDown] = useState(true);
  const [open, setOpen] = useState<number | null>(null);
  const lastKey = `${project.data?.last_deployment?.id}:${project.data?.last_deployment?.status}`;
  const refetchState = state.refetch;
  useEffect(() => {
    // A deploy finished (or started): the commit on the server may have changed.
    void refetchState();
  }, [lastKey, refetchState]);

  if (project.isPending) return <Loader />;
  if (project.isError) return <Alert color="red">{errorMessage(t, project.error)}</Alert>;
  const p = project.data;
  const active = isActive(p.last_deployment);

  const start = (ref: string | null) =>
    deploy.mutate(ref, {
      onSuccess: (d) => {
        setConfirm(null);
        setOpen(d.id);
      },
      onError: (error) => {
        setConfirm(null);
        notifications.show({ color: "red", message: errorMessage(t, error) });
      },
    });

  return (
    <Stack gap={18}>
      <PageHeader
        help="deploy"
        title={p.name}
        subtitle={`${p.repo_url} · ${p.branch}`}
        actions={
          <Group gap="xs">
            <Button
              variant="default"
              component={Link}
              to={`/projects/${p.id}/edit`}
              leftSection={<PencilSimple size={16} />}
            >
              {t("common.edit")}
            </Button>
            <Button
              variant="default"
              color="red"
              leftSection={<Trash size={16} />}
              disabled={active}
              onClick={() => setDeleting(true)}
            >
              {t("common.delete")}
            </Button>
            <Button
              leftSection={<RocketLaunch size={16} />}
              loading={deploy.isPending}
              disabled={active}
              onClick={() => setConfirm({ ref: null })}
            >
              {active ? t("projects.deploying") : t("projects.deploy")}
            </Button>
          </Group>
        }
      />

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing={12}>
        <Paper withBorder p="lg">
          <Title order={4} mb="sm">
            {t("projects.onServer")}
          </Title>
          <Stack gap={8}>
            <div className="cl-kv">
              <span>{t("projects.current")}</span>
              <code dir="ltr">
                {state.data?.available
                  ? (state.data.commit_sha?.slice(0, 8) ?? t("projects.notCheckedOut"))
                  : "—"}
              </code>
            </div>
            {state.data?.commit_message && (
              <Text size="sm" c="dimmed">
                {state.data.commit_message}
              </Text>
            )}
            {state.data && !state.data.available && (
              <Text size="xs" c="dimmed">
                {t(`errors.${state.data.error_code}`, {
                  defaultValue: state.data.error_code ?? "",
                })}
              </Text>
            )}
            <div className="cl-kv">
              <span>{t("projects.fields.composeFile")}</span>
              <code dir="ltr">{p.compose_file}</code>
            </div>
            <div className="cl-kv">
              <span>{t("projects.sections.env")}</span>
              <span>{p.env_names.length ? p.env_names.join(", ") : "—"}</span>
            </div>
            <div className="cl-kv">
              <span>{t("projects.sections.backup")}</span>
              <span>
                {p.backup_databases.length ? (
                  <>
                    {p.backup_databases.join(", ")}{" "}
                    {p.backup_required && (
                      <Badge size="xs" variant="light">
                        {t("projects.required")}
                      </Badge>
                    )}
                  </>
                ) : (
                  t("projects.noBackup")
                )}
              </span>
            </div>
            {p.last_success && (
              <Text size="xs" c="dimmed">
                {t("projects.lastSuccess", {
                  time: formatDateTime(
                    p.last_success.finished_at ?? p.last_success.requested_at,
                    i18n.language,
                  ),
                })}
              </Text>
            )}
          </Stack>
        </Paper>
        <Services project={p} />
      </SimpleGrid>

      <Deployments project={p} onOpen={setOpen} />

      <DeploymentDrawer
        id={open}
        onClose={() => setOpen(null)}
        onRedeploy={active ? undefined : (commit) => setConfirm({ ref: commit })}
      />
      <ConfirmDialog
        opened={confirm !== null}
        title={confirm?.ref ? t("projects.redeployTitle") : t("projects.deployTitle")}
        body={
          confirm?.ref
            ? t("projects.redeployBody", { name: p.name, commit: confirm.ref.slice(0, 8) })
            : t("projects.deployBody", { name: p.name, branch: p.branch })
        }
        confirmLabel={confirm?.ref ? t("projects.redeploy") : t("projects.deploy")}
        loading={deploy.isPending}
        onConfirm={() => confirm && start(confirm.ref)}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        opened={deleting}
        title={t("projects.deleteTitle")}
        body={t("projects.deleteBody", { name: p.name })}
        confirmLabel={t("common.delete")}
        loading={remove.isPending}
        onConfirm={() =>
          remove.mutate(
            { id: p.id, down },
            {
              onSuccess: () => {
                notifications.show({ color: "green", message: t("projects.deleted") });
                navigate("/projects");
              },
              onError: (error) => {
                setDeleting(false);
                notifications.show({ color: "red", message: errorMessage(t, error) });
              },
            },
          )
        }
        onCancel={() => setDeleting(false)}
      >
        {p.last_deployment && (
          <Checkbox
            mb="lg"
            label={t("projects.deleteDown")}
            description={t("projects.deleteDownHint")}
            checked={down}
            onChange={(e) => setDown(e.currentTarget.checked)}
          />
        )}
      </ConfirmDialog>
    </Stack>
  );
}
