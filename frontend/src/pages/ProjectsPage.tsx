import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Menu,
  Modal,
  Paper,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { errorMessage, isApiError } from "../api/client";
import {
  type Project,
  type ProjectFolder,
  useFolderMutations,
  useProjectFolders,
  useProjects,
} from "../api/projects";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DeployStatusBadge } from "../components/DeployStatusBadge";
import {
  ArrowLeft,
  ArrowRight,
  Folder,
  MagnifyingGlass,
  PencilSimple,
  Plus,
  RocketLaunch,
  Trash,
  X,
} from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { ServerBadge } from "../components/ServerBadge";
import { formatDateTime, formatNumber } from "../i18n";

const GRID = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(270px, 1fr))",
  gap: 12,
} as const;

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

/** A folder tile: its name, how many projects (here and everywhere) and their last deploys. */
function FolderCard(props: { folder: ProjectFolder; projects: Project[] }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const failed = props.projects.filter((p) => p.last_deployment?.status === "failed").length;
  const running = props.projects.filter((p) =>
    ["queued", "running"].includes(p.last_deployment?.status ?? ""),
  ).length;
  return (
    <Link
      to={`/projects?folder=${encodeURIComponent(props.folder.name)}`}
      className="cl-card"
      data-testid={`folder-${props.folder.name}`}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span
          className="cl-icon-tile"
          style={{ background: "var(--color-accent-900)", color: "var(--color-accent-300)" }}
        >
          <Folder size={22} weight="fill" />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Text fw={600} truncate>
            {props.folder.name}
          </Text>
          <Text size="xs" c="var(--color-neutral-500)">
            {t("projects.folders.count", { n: formatNumber(props.projects.length, lang) })}
            {props.folder.projects > props.projects.length &&
              ` · ${t("projects.folders.elsewhere", {
                n: formatNumber(props.folder.projects - props.projects.length, lang),
              })}`}
          </Text>
        </div>
      </div>
      <Group gap={6}>
        {failed > 0 && (
          <Badge color="red" variant="light">
            {t("projects.folders.failed", { n: formatNumber(failed, lang) })}
          </Badge>
        )}
        {running > 0 && (
          <Badge color="blue" variant="light">
            {t("projects.folders.deploying", { n: formatNumber(running, lang) })}
          </Badge>
        )}
        {failed === 0 && running === 0 && props.projects.length > 0 && (
          <Badge color="green" variant="light">
            {t("projects.folders.allGood")}
          </Badge>
        )}
        {props.projects.length === 0 && (
          <Badge color="gray" variant="light">
            {t("projects.folders.empty")}
          </Badge>
        )}
      </Group>
    </Link>
  );
}

/** Asks for a folder name: to create a folder or rename one. */
function FolderNameModal(props: {
  opened: boolean;
  title: string;
  initial: string;
  confirm: string;
  loading: boolean;
  error: unknown;
  onClose: () => void;
  onSubmit: (name: string) => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(props.initial);
  return (
    <Modal opened={props.opened} onClose={props.onClose} title={props.title} centered>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) props.onSubmit(name.trim());
        }}
      >
        <Stack gap="md">
          <TextInput
            label={t("projects.folders.name")}
            description={t("projects.folders.nameHint")}
            placeholder={t("projects.fields.folderPlaceholder")}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            maxLength={60}
            data-autofocus
            error={
              props.error
                ? isApiError(props.error, "validation_error")
                  ? t("projects.validation.invalid_folder")
                  : errorMessage(t, props.error)
                : null
            }
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={props.onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" loading={props.loading} disabled={!name.trim()}>
              {props.confirm}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function EmptyState({ title, hint }: { title: string; hint: string }) {
  return (
    <Paper withBorder p="xl">
      <Stack align="center" gap="xs">
        <span className="cl-icon-tile">
          <RocketLaunch size={20} />
        </span>
        <Text fw={500}>{title}</Text>
        <Text c="dimmed" size="sm" ta="center" maw={520}>
          {hint}
        </Text>
      </Stack>
    </Paper>
  );
}

/** Inside one folder: its projects, and adding one right there. */
function FolderView(props: { folder: ProjectFolder | null; name: string; projects: Project[] }) {
  const { t, i18n } = useTranslation();
  const Back = i18n.dir(i18n.language) === "rtl" ? ArrowRight : ArrowLeft;
  const { rename, remove } = useFolderMutations();
  const [, setParams] = useSearchParams();
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const newProject = `/projects/new?folder=${encodeURIComponent(props.name)}`;
  return (
    <Stack gap={18}>
      <PageHeader
        help="projects-overview"
        title={
          <Group gap={10} wrap="nowrap">
            <Folder size={26} weight="fill" color="var(--color-accent-300)" />
            <span>{props.name}</span>
          </Group>
        }
        badge={<ServerBadge />}
        subtitle={t("projects.folders.inside")}
        back={{ to: "/projects", label: t("projects.title") }}
        actions={
          <Group gap="xs">
            {props.folder && (
              <Menu position="bottom-end">
                <Menu.Target>
                  <Button variant="default">{t("projects.folders.manage")}</Button>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item
                    leftSection={<PencilSimple size={14} />}
                    onClick={() => setRenaming(true)}
                  >
                    {t("projects.folders.rename")}
                  </Menu.Item>
                  <Tooltip
                    label={t("projects.folders.notEmpty")}
                    disabled={props.folder.projects === 0}
                  >
                    <Menu.Item
                      color="red"
                      leftSection={<Trash size={14} />}
                      disabled={props.folder.projects > 0}
                      onClick={() => setDeleting(true)}
                    >
                      {t("projects.folders.delete")}
                    </Menu.Item>
                  </Tooltip>
                </Menu.Dropdown>
              </Menu>
            )}
            <Button component={Link} to={newProject} leftSection={<Plus size={16} />}>
              {t("projects.folders.addHere")}
            </Button>
          </Group>
        }
      />
      {props.projects.length === 0 ? (
        <Paper withBorder p="xl">
          <Stack align="center" gap="sm">
            <span className="cl-icon-tile">
              <Folder size={20} />
            </span>
            <Text fw={500}>{t("projects.folders.emptyTitle")}</Text>
            <Text c="dimmed" size="sm" ta="center" maw={480}>
              {t("projects.folders.emptyHint")}
            </Text>
            <Button component={Link} to={newProject} leftSection={<Plus size={16} />}>
              {t("projects.folders.addHere")}
            </Button>
            <Anchor component={Link} to="/projects" size="sm">
              <Group gap={4}>
                <Back size={12} />
                {t("projects.title")}
              </Group>
            </Anchor>
          </Stack>
        </Paper>
      ) : (
        <div style={GRID}>
          {props.projects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
      {props.folder && renaming && (
        <FolderNameModal
          opened
          title={t("projects.folders.rename")}
          initial={props.folder.name}
          confirm={t("common.save")}
          loading={rename.isPending}
          error={rename.error}
          onClose={() => setRenaming(false)}
          onSubmit={(name) =>
            rename.mutate(
              { id: props.folder!.id, name },
              {
                onSuccess: (folder) => {
                  setRenaming(false);
                  setParams({ folder: folder.name });
                  if (folder.projects > 0) {
                    notifications.show({ message: t("projects.folders.renamedHint") });
                  }
                },
              },
            )
          }
        />
      )}
      <ConfirmDialog
        opened={deleting}
        title={t("projects.folders.delete")}
        body={t("projects.folders.deleteConfirm", { name: props.name })}
        confirmLabel={t("common.delete")}
        loading={remove.isPending}
        onCancel={() => setDeleting(false)}
        onConfirm={() =>
          props.folder &&
          remove.mutate(props.folder.id, {
            onSuccess: () => setParams({}),
            onSettled: () => setDeleting(false),
          })
        }
      />
    </Stack>
  );
}

export function ProjectsPage() {
  const { t } = useTranslation();
  const projects = useProjects();
  const folders = useProjectFolders();
  const { create } = useFolderMutations();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const current = params.get("folder");

  const list = projects.data ?? [];
  const byFolder = useMemo(() => {
    const map = new Map<string, Project[]>();
    for (const p of list) {
      if (p.folder) map.set(p.folder, [...(map.get(p.folder) ?? []), p]);
    }
    return map;
  }, [list]);
  const folderList = useMemo(() => {
    const known = folders.data ?? [];
    // A project's folder not yet in the list (it appears there on the next load).
    const extra = [...byFolder.keys()]
      .filter((name) => !known.some((f) => f.name === name))
      .map((name, i) => ({ id: -1 - i, name, created_at: "", projects: 0 }));
    return [...known, ...extra].sort((a, b) => a.name.localeCompare(b.name));
  }, [folders.data, byFolder]);

  if (projects.isPending) return <Loader />;
  if (projects.isError) return <Alert color="red">{errorMessage(t, projects.error)}</Alert>;

  if (current !== null) {
    const folder = folderList.find((f) => f.name === current) ?? null;
    return (
      <FolderView
        folder={folder && folder.id > 0 ? folder : null}
        name={current}
        projects={byFolder.get(current) ?? []}
      />
    );
  }

  const needle = search.trim().toLowerCase();
  const found = needle
    ? list.filter((p) =>
        `${p.name} ${p.repo_url} ${p.folder ?? ""} ${p.server_name}`.toLowerCase().includes(needle),
      )
    : [];
  const loose = list.filter((p) => !p.folder);

  return (
    <Stack gap={18}>
      <PageHeader
        help="projects-overview"
        title={t("projects.title")}
        badge={<ServerBadge />}
        subtitle={t("projects.subtitle")}
        actions={
          <Group gap="xs">
            <Button
              variant="default"
              leftSection={<Folder size={16} />}
              onClick={() => {
                create.reset();
                setCreating(true);
              }}
            >
              {t("projects.folders.new")}
            </Button>
            <Button component={Link} to="/projects/new" leftSection={<Plus size={16} />}>
              {t("projects.add")}
            </Button>
          </Group>
        }
      />
      {list.length > 0 && (
        <TextInput
          placeholder={t("projects.search")}
          aria-label={t("projects.search")}
          leftSection={<MagnifyingGlass size={14} />}
          rightSection={
            search ? (
              <ActionIcon
                variant="subtle"
                size="sm"
                aria-label={t("common.close")}
                onClick={() => setSearch("")}
              >
                <X size={12} />
              </ActionIcon>
            ) : null
          }
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          maw={360}
        />
      )}
      {needle ? (
        found.length === 0 ? (
          <Text c="dimmed">{t("projects.noMatch")}</Text>
        ) : (
          <div style={GRID}>
            {found.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
        )
      ) : (
        <>
          {list.length === 0 && folderList.length === 0 && (
            <EmptyState title={t("projects.empty")} hint={t("projects.emptyHint")} />
          )}
          {folderList.length > 0 && (
            <Stack gap={8}>
              <Text fw={600} c="var(--color-neutral-300)">
                {t("projects.folders.title")}
              </Text>
              <div style={GRID}>
                {folderList.map((folder) => (
                  <FolderCard
                    key={folder.name}
                    folder={folder}
                    projects={byFolder.get(folder.name) ?? []}
                  />
                ))}
              </div>
            </Stack>
          )}
          {loose.length > 0 && (
            <Stack gap={8} data-testid="folder-none">
              {folderList.length > 0 && (
                <Text fw={600} c="var(--color-neutral-300)">
                  {t("projects.noFolder")}
                </Text>
              )}
              <div style={GRID}>
                {loose.map((project) => (
                  <ProjectCard key={project.id} project={project} />
                ))}
              </div>
            </Stack>
          )}
        </>
      )}
      {creating && (
        <FolderNameModal
          opened
          title={t("projects.folders.new")}
          initial=""
          confirm={t("projects.folders.create")}
          loading={create.isPending}
          error={create.error}
          onClose={() => setCreating(false)}
          onSubmit={(name) =>
            create.mutate(name, {
              onSuccess: (folder) => {
                setCreating(false);
                setParams({ folder: folder.name });
              },
            })
          }
        />
      )}
    </Stack>
  );
}
