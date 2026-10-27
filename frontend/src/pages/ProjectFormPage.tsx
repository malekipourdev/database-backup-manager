import {
  ActionIcon,
  Alert,
  Button,
  Group,
  Loader,
  MultiSelect,
  Paper,
  PasswordInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  TagsInput,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, errorMessage } from "../api/client";
import { useDatabases, useInstances } from "../api/instances";
import { useCurrentServer } from "../server/CurrentServer";
import {
  type AuthType,
  type Project,
  type ProjectInput,
  useProject,
  useSaveProject,
} from "../api/projects";
import { Plus, Trash } from "../components/Icons";
import { PageHeader } from "../components/PageHeader";

interface EnvRow {
  key: number;
  name: string;
  /** Empty with stored=true keeps the stored value. */
  value: string;
  stored: boolean;
}

const REPO_PLACEHOLDER = "https://github.com/acme/shop.git";
const KEY_PLACEHOLDER = "-----BEGIN OPENSSH PRIVATE KEY-----";

let nextKey = 1;
const row = (name = "", stored = false): EnvRow => ({ key: nextKey++, name, value: "", stored });

function initial(
  project?: Project,
  serverId: number | null = null,
): ProjectInput & { rows: EnvRow[] } {
  return {
    name: project?.name ?? "",
    server_id: project?.server_id ?? serverId,
    repo_url: project?.repo_url ?? "",
    branch: project?.branch ?? "main",
    compose_file: project?.compose_file ?? "docker-compose.yml",
    auth_type: project?.auth_type ?? "none",
    credential: "",
    clear_credential: false,
    env: [],
    rows: (project?.env_names ?? []).map((name) => row(name, true)),
    backup_instance_id: project?.backup_instance_id ?? null,
    backup_databases: project?.backup_databases ?? [],
    backup_required: project?.backup_required ?? true,
    web_domains: project?.web_domains ?? [],
    web_target: project?.web_target ?? null,
  };
}

function BackupFields(props: {
  instanceId: number | null;
  databases: string[];
  required: boolean;
  onChange: (values: {
    instanceId?: number | null;
    databases?: string[];
    required?: boolean;
  }) => void;
}) {
  const { t } = useTranslation();
  const instances = useInstances();
  const dbs = useDatabases(props.instanceId ?? 0);
  const options = useMemo(() => {
    const live = props.instanceId
      ? (dbs.data?.databases ?? []).filter((d) => d.selectable).map((d) => d.name)
      : [];
    return [...new Set([...live, ...props.databases])].sort();
  }, [dbs.data, props.databases, props.instanceId]);
  return (
    <Stack gap="sm">
      <Select
        label={t("projects.fields.backupInstance")}
        placeholder={t("projects.fields.noBackup")}
        clearable
        data={(instances.data ?? []).map((i) => ({ value: String(i.id), label: i.name }))}
        value={props.instanceId ? String(props.instanceId) : null}
        onChange={(v) => props.onChange({ instanceId: v ? Number(v) : null, databases: [] })}
      />
      {props.instanceId && (
        <>
          <MultiSelect
            label={t("projects.fields.backupDatabases")}
            data={options}
            value={props.databases}
            onChange={(v) => props.onChange({ databases: v })}
            searchable
            dir="ltr"
          />
          <Switch
            label={t("projects.fields.backupRequired")}
            description={t("projects.fields.backupRequiredHint")}
            checked={props.required}
            onChange={(e) => props.onChange({ required: e.currentTarget.checked })}
          />
        </>
      )}
    </Stack>
  );
}

/** The server the project is deployed on: the selected one for a new project. */
function ServerNote({ serverId, deployed }: { serverId: number | null; deployed: boolean }) {
  const { t } = useTranslation();
  const { servers } = useCurrentServer();
  const server = servers.find((s) => s.id === serverId);
  if (!server) return null;
  return (
    <Text size="sm" c="dimmed" data-testid="project-server">
      {t("projects.onServer", { name: server.name })}
      {deployed ? ` ${t("projects.fields.serverLocked")}` : ""}
    </Text>
  );
}

function Form({ project }: { project?: Project }) {
  const { t } = useTranslation();
  const currentId = useCurrentServer().id;
  const navigate = useNavigate();
  const save = useSaveProject(project?.id);
  const [values, setValues] = useState(() => initial(project, currentId));
  const set = <K extends keyof typeof values>(key: K, value: (typeof values)[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));
  const fields = save.error instanceof ApiError ? (save.error.fields ?? {}) : {};
  const fieldError = (name: string) =>
    fields[name]
      ? t(`projects.validation.${fields[name]}`, { defaultValue: t("validation.invalid") })
      : null;
  const deployed = Boolean(project?.last_deployment);
  const envError = fieldError("env");

  const submit = () => {
    const { rows, ...rest } = values;
    const payload: ProjectInput = {
      ...rest,
      env: rows
        .filter((r) => r.name.trim())
        .map((r) => ({
          name: r.name.trim(),
          value: r.stored && r.value === "" ? null : r.value,
        })),
    };
    save.mutate(payload, {
      onSuccess: (saved) => {
        notifications.show({ color: "green", message: t("projects.saved") });
        navigate(`/projects/${saved.id}`);
      },
    });
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <Stack gap="md" maw={820}>
        <Paper withBorder p="lg">
          <Title order={4} mb="sm">
            {t("projects.sections.source")}
          </Title>
          <Stack gap="sm">
            <TextInput
              label={t("projects.fields.name")}
              description={
                deployed ? t("projects.fields.nameLocked") : t("projects.fields.nameHint")
              }
              required
              dir="ltr"
              value={values.name}
              disabled={deployed}
              onChange={(e) => set("name", e.currentTarget.value.toLowerCase())}
              error={fieldError("name")}
            />
            <ServerNote serverId={values.server_id} deployed={deployed} />
            <TextInput
              label={t("projects.fields.repoUrl")}
              description={t("projects.fields.repoUrlHint")}
              required
              dir="ltr"
              placeholder={REPO_PLACEHOLDER}
              value={values.repo_url}
              onChange={(e) => set("repo_url", e.currentTarget.value)}
              error={fieldError("repo_url")}
            />
            <Group grow align="flex-start">
              <TextInput
                label={t("projects.fields.branch")}
                required
                dir="ltr"
                value={values.branch}
                onChange={(e) => set("branch", e.currentTarget.value)}
                error={fieldError("branch")}
              />
              <TextInput
                label={t("projects.fields.composeFile")}
                description={t("projects.fields.composeFileHint")}
                required
                dir="ltr"
                value={values.compose_file}
                onChange={(e) => set("compose_file", e.currentTarget.value)}
                error={fieldError("compose_file")}
              />
            </Group>
          </Stack>
        </Paper>

        <Paper withBorder p="lg">
          <Title order={4} mb={4}>
            {t("projects.sections.access")}
          </Title>
          <Text size="sm" c="dimmed" mb="sm">
            {t("projects.accessHint")}
          </Text>
          <Stack gap="sm">
            <SegmentedControl
              value={values.auth_type}
              onChange={(v) => set("auth_type", v as AuthType)}
              data={(["none", "token", "ssh_key"] as AuthType[]).map((value) => ({
                value,
                label: t(`projects.auth.${value}`),
              }))}
            />
            {values.auth_type === "token" && (
              <PasswordInput
                label={t("projects.fields.token")}
                description={
                  project?.has_credential && project.auth_type === "token"
                    ? t("projects.fields.keepCredential")
                    : t("projects.fields.tokenHint")
                }
                dir="ltr"
                autoComplete="off"
                value={values.credential}
                onChange={(e) => set("credential", e.currentTarget.value)}
                error={fieldError("credential")}
              />
            )}
            {values.auth_type === "ssh_key" && (
              <Textarea
                label={t("projects.fields.sshKey")}
                description={
                  project?.has_credential && project.auth_type === "ssh_key"
                    ? t("projects.fields.keepCredential")
                    : t("projects.fields.sshKeyHint")
                }
                dir="ltr"
                autosize
                minRows={3}
                maxRows={10}
                placeholder={KEY_PLACEHOLDER}
                styles={{ input: { fontFamily: "var(--font-mono)", fontSize: 12 } }}
                value={values.credential}
                onChange={(e) => set("credential", e.currentTarget.value)}
                error={fieldError("credential")}
              />
            )}
          </Stack>
        </Paper>

        <Paper withBorder p="lg">
          <Title order={4} mb={4}>
            {t("projects.sections.env")}
          </Title>
          <Text size="sm" c="dimmed" mb="sm">
            {t("projects.envHint")}
          </Text>
          <Stack gap="xs">
            {values.rows.map((r, index) => (
              <Group key={r.key} gap="xs" wrap="nowrap" align="flex-start">
                <TextInput
                  aria-label={t("projects.fields.envName")}
                  placeholder={t("projects.fields.envName")}
                  dir="ltr"
                  style={{ flex: "0 0 35%" }}
                  value={r.name}
                  onChange={(e) => {
                    const name = e.currentTarget.value;
                    set(
                      "rows",
                      values.rows.map((x, i) => (i === index ? { ...x, name } : x)),
                    );
                  }}
                />
                <PasswordInput
                  aria-label={t("projects.fields.envValue")}
                  placeholder={
                    r.stored ? t("projects.fields.envStored") : t("projects.fields.envValue")
                  }
                  dir="ltr"
                  autoComplete="off"
                  style={{ flex: 1 }}
                  value={r.value}
                  onChange={(e) => {
                    const value = e.currentTarget.value;
                    set(
                      "rows",
                      values.rows.map((x, i) => (i === index ? { ...x, value } : x)),
                    );
                  }}
                />
                <ActionIcon
                  variant="subtle"
                  color="red"
                  size="lg"
                  aria-label={t("projects.removeVar")}
                  onClick={() =>
                    set(
                      "rows",
                      values.rows.filter((_, i) => i !== index),
                    )
                  }
                >
                  <Trash size={16} />
                </ActionIcon>
              </Group>
            ))}
            {envError && (
              <Text size="sm" c="red">
                {envError}
              </Text>
            )}
            <Group>
              <Button
                variant="default"
                size="xs"
                leftSection={<Plus size={14} />}
                onClick={() => set("rows", [...values.rows, row()])}
              >
                {t("projects.addVar")}
              </Button>
            </Group>
          </Stack>
        </Paper>

        <Paper withBorder p="lg">
          <Title order={4} mb={4}>
            {t("projects.sections.backup")}
          </Title>
          <Text size="sm" c="dimmed" mb="sm">
            {t("projects.backupHint")}
          </Text>
          <BackupFields
            instanceId={values.backup_instance_id}
            databases={values.backup_databases}
            required={values.backup_required}
            onChange={(v) =>
              setValues((prev) => ({
                ...prev,
                ...(v.instanceId !== undefined ? { backup_instance_id: v.instanceId } : {}),
                ...(v.databases !== undefined ? { backup_databases: v.databases } : {}),
                ...(v.required !== undefined ? { backup_required: v.required } : {}),
              }))
            }
          />
        </Paper>

        <Paper withBorder p="lg">
          <Title order={4} mb={4}>
            {t("projects.sections.web")}
          </Title>
          <Text size="sm" c="dimmed" mb="sm">
            {t("projects.webHint")}
          </Text>
          <Stack gap="md">
            <TagsInput
              label={t("projects.fields.webDomains")}
              placeholder={`app.example.com`}
              value={values.web_domains}
              onChange={(v) => setValues((prev) => ({ ...prev, web_domains: v }))}
              splitChars={[",", " "]}
              dir="ltr"
              error={fieldError("web_domains")}
            />
            <TextInput
              label={t("projects.fields.webTarget")}
              description={t("projects.fields.webTargetHint")}
              placeholder={`http://127.0.0.1:8080`}
              value={values.web_target ?? ""}
              onChange={(e) => {
                const value = e.currentTarget.value;
                setValues((prev) => ({ ...prev, web_target: value || null }));
              }}
              dir="ltr"
              error={fieldError("web_target")}
            />
          </Stack>
        </Paper>

        {save.isError && !Object.keys(fields).length && (
          <Alert color="red">{errorMessage(t, save.error)}</Alert>
        )}
        {Boolean(Object.keys(fields).length) && (
          <Alert color="red">{t("errors.validation_error")}</Alert>
        )}
        <Group justify="flex-end">
          <Button
            variant="default"
            component={Link}
            to={project ? `/projects/${project.id}` : "/projects"}
          >
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={save.isPending}>
            {t("common.save")}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function ProjectFormPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const editing = id !== undefined;
  const project = useProject(Number(id), editing);
  const [ready, setReady] = useState(!editing);
  useEffect(() => {
    if (project.data) setReady(true);
  }, [project.data]);
  return (
    <Stack gap={18}>
      <PageHeader
        help="add-project"
        title={editing ? t("projects.editTitle") : t("projects.newTitle")}
        subtitle={t("projects.formSubtitle")}
      />
      {editing && project.isPending && <Loader />}
      {editing && project.isError && <Alert color="red">{errorMessage(t, project.error)}</Alert>}
      {ready && <Form project={project.data} />}
    </Stack>
  );
}
