import {
  Alert,
  Anchor,
  Badge,
  Button,
  Code,
  Drawer,
  Group,
  Loader,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  Textarea,
  Tooltip,
} from "@mantine/core";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { errorMessage } from "../api/client";
import type { ServerRef } from "../api/containers";
import {
  type Domain,
  type WebCertificate,
  type WebResult,
  daysLeft,
  fetchBackup,
  useRestore,
  useSaveFile,
  useSetEnabled,
  useSetMaintenance,
  useWebBackups,
  useWebFile,
  useWebLogs,
} from "../api/webservers";
import { formatDateTime, formatNumber } from "../i18n";
import { ConfigCode } from "./ConfigCode";
import { ConfirmDialog } from "./ConfirmDialog";
import { WebResultAlert } from "./WebDialogs";

const LINES = ["100", "500", "2000"];
const KIND_LABEL = { nginx: "nginx", apache: "Apache" } as const;

/** "20261027T101500123456Z" -> an ISO time. */
export function backupTime(name: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/.exec(name);
  return m ? `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}Z` : name;
}

function ConfigTab(props: {
  server: ServerRef;
  domain: Domain;
  file: string;
  line: number | null;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  const kind = props.domain.server;
  const file = useWebFile(props.server, kind, props.file);
  const save = useSaveFile(props.server);
  const [draft, setDraft] = useState<string | null>(null);
  useEffect(() => {
    setDraft(null);
    save.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.file]);

  if (file.isPending) return <Loader />;
  if (file.isError) return <Alert color="red">{errorMessage(t, file.error)}</Alert>;
  const editing = draft !== null;
  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Text size="xs" c="dimmed" dir="ltr">
          {file.data.path}
        </Text>
        {editing ? (
          <Group gap="xs">
            <Button size="xs" variant="default" onClick={() => setDraft(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              size="xs"
              loading={save.isPending}
              disabled={draft === file.data.content}
              onClick={() =>
                save.mutate(
                  { kind, path: file.data.path, content: draft, sha256: file.data.sha256 },
                  { onSuccess: (result) => result.ok && setDraft(null) },
                )
              }
            >
              {t("webservers.site.saveAndReload")}
            </Button>
          </Group>
        ) : (
          <Tooltip label={t("webservers.readOnlyHint")} disabled={!props.readOnly}>
            <Button
              size="xs"
              variant="light"
              disabled={props.readOnly}
              onClick={() => {
                save.reset();
                setDraft(file.data.content);
              }}
            >
              {t("common.edit")}
            </Button>
          </Tooltip>
        )}
      </Group>
      {save.isError && <Alert color="red">{errorMessage(t, save.error)}</Alert>}
      <WebResultAlert result={save.data} />
      {editing ? (
        <>
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.currentTarget.value)}
            autosize
            minRows={16}
            maxRows={40}
            dir="ltr"
            spellCheck={false}
            styles={{ input: { fontFamily: "var(--font-mono)", fontSize: 12.5 } }}
            aria-label={t("webservers.site.editor")}
          />
          <Text size="xs" c="dimmed">
            {t("webservers.site.saveHint")}
          </Text>
        </>
      ) : (
        <ConfigCode text={file.data.content} line={props.line} />
      )}
    </Stack>
  );
}

function VersionsTab(props: {
  server: ServerRef;
  domain: Domain;
  file: string;
  readOnly: boolean;
}) {
  const { t, i18n } = useTranslation();
  const kind = props.domain.server;
  const backups = useWebBackups(props.server, kind, props.file);
  const restore = useRestore(props.server);
  const [preview, setPreview] = useState<{ name: string; content: string } | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  if (backups.isPending) return <Loader />;
  if (backups.isError) return <Alert color="red">{errorMessage(t, backups.error)}</Alert>;
  const open = async (name: string) => {
    setLoading(name);
    setError(null);
    try {
      setPreview({
        name,
        content: (await fetchBackup(props.server, kind, props.file, name)).content,
      });
    } catch (exc) {
      setError(exc);
    } finally {
      setLoading(null);
    }
  };
  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        {t("webservers.site.versionsHint")}
      </Text>
      {backups.data.backups.length === 0 ? (
        <Text c="dimmed">{t("webservers.site.noVersions")}</Text>
      ) : (
        <Table verticalSpacing={6}>
          <Table.Tbody>
            {backups.data.backups.map((name) => (
              <Table.Tr key={name}>
                <Table.Td>{formatDateTime(backupTime(name), i18n.language)}</Table.Td>
                <Table.Td>
                  <Group gap="xs" justify="flex-end">
                    <Button
                      size="xs"
                      variant="subtle"
                      loading={loading === name}
                      onClick={() => open(name)}
                    >
                      {t("webservers.site.view")}
                    </Button>
                    <Button
                      size="xs"
                      variant="light"
                      disabled={props.readOnly}
                      onClick={() => setConfirm(name)}
                    >
                      {t("webservers.site.restore")}
                    </Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {error !== null && <Alert color="red">{errorMessage(t, error)}</Alert>}
      {restore.isError && <Alert color="red">{errorMessage(t, restore.error)}</Alert>}
      <WebResultAlert result={restore.data} />
      {preview && (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            {formatDateTime(backupTime(preview.name), i18n.language)}
          </Text>
          <ConfigCode text={preview.content} />
        </Stack>
      )}
      <ConfirmDialog
        opened={confirm !== null}
        title={t("webservers.site.restore")}
        body={t("webservers.site.restoreConfirm")}
        confirmLabel={t("webservers.site.restore")}
        loading={restore.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() =>
          confirm &&
          restore.mutate(
            { kind, path: props.file, backup: confirm },
            { onSettled: () => setConfirm(null) },
          )
        }
      />
    </Stack>
  );
}

function LogsTab(props: { server: ServerRef; domain: Domain }) {
  const { t } = useTranslation();
  const files = useMemo(() => {
    const out: { value: string; label: string }[] = [];
    for (const site of props.domain.sites) {
      for (const which of ["access", "error"] as const) {
        const path = site.logs?.[which];
        if (path && !out.some((o) => o.value === path)) {
          out.push({ value: path, label: `${t(`webservers.site.log.${which}`)} — ${path}` });
        }
      }
    }
    return out;
  }, [props.domain, t]);
  const [path, setPath] = useState<string | null>(files[0]?.value ?? null);
  const [lines, setLines] = useState("100");
  const logs = useWebLogs(props.server, props.domain.server, path, Number(lines));
  if (files.length === 0) return <Text c="dimmed">{t("webservers.site.noLogs")}</Text>;
  return (
    <Stack gap="sm">
      <Group gap="sm" align="flex-end">
        <Select
          label={t("webservers.site.logFile")}
          data={files}
          value={path}
          onChange={setPath}
          style={{ flex: 1, minWidth: 220 }}
          dir="ltr"
        />
        <SegmentedControl value={lines} onChange={setLines} data={LINES} />
        <Button variant="light" onClick={() => logs.refetch()} loading={logs.isFetching}>
          {t("webservers.reload")}
        </Button>
      </Group>
      {logs.isError && <Alert color="red">{errorMessage(t, logs.error)}</Alert>}
      {logs.data && (
        <Code
          block
          dir="ltr"
          data-testid="web-log"
          style={{ maxHeight: "60vh", overflow: "auto", whiteSpace: "pre" }}
        >
          {logs.data.lines.length ? logs.data.lines.join("\n") : t("webservers.site.emptyLog")}
        </Code>
      )}
    </Stack>
  );
}

export function WebSiteDrawer(props: {
  server: ServerRef;
  domain: Domain | null;
  readOnly: boolean;
  certificates: Record<string, WebCertificate>;
  monitored: boolean;
  onClose: () => void;
  onCertificate: (domain: Domain) => void;
  onMonitor: (url: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const { domain } = props;
  const files = useMemo(() => [...new Set((domain?.sites ?? []).map((s) => s.file))], [domain]);
  const [file, setFile] = useState<string | null>(files[0] ?? null);
  useEffect(() => setFile(files[0] ?? null), [files]);
  const setEnabled = useSetEnabled(props.server);
  const setMaintenance = useSetMaintenance(props.server);
  const [result, setResult] = useState<WebResult | null>(null);
  const [confirm, setConfirm] = useState<"disable" | "maintenance" | null>(null);
  useEffect(() => setResult(null), [domain]);
  if (!domain) return <Drawer opened={false} onClose={props.onClose} />;

  const site = domain.sites.find((s) => s.file === file) ?? domain.sites[0];
  const cert = domain.sites
    .map((s) => (s.certificate ? props.certificates[s.certificate] : undefined))
    .find(Boolean);
  const days = daysLeft(cert);
  const plainName = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test(domain.name);
  const url = `${domain.ssl ? "https" : "http"}://${domain.name}/`;
  const busy = setEnabled.isPending || setMaintenance.isPending;
  const kind = domain.server;
  const done = (r: WebResult) => setResult(r);
  const error = setEnabled.error ?? setMaintenance.error;

  return (
    <Drawer
      opened
      onClose={props.onClose}
      position={i18n.dir(lang) === "rtl" ? "left" : "right"}
      size="xl"
      title={
        <Group gap="xs">
          <Text fw={600} dir="ltr">
            {domain.name || t("webservers.catchAll")}
          </Text>
          <Badge variant="light" color="gray">
            {KIND_LABEL[kind]}
          </Badge>
          {domain.maintenance && (
            <Badge color="orange" variant="light">
              {t("webservers.maintenance")}
            </Badge>
          )}
          {!domain.enabled && (
            <Badge color="gray" variant="outline">
              {t("webservers.disabled")}
            </Badge>
          )}
        </Group>
      }
    >
      <Stack gap="md">
        <Group gap="xs">
          {domain.enabled && !domain.maintenance && (
            <Button
              size="xs"
              variant="light"
              color="red"
              disabled={props.readOnly || busy}
              onClick={() => setConfirm("disable")}
            >
              {t("webservers.site.disable")}
            </Button>
          )}
          {!domain.enabled && (
            <Button
              size="xs"
              variant="light"
              disabled={props.readOnly}
              loading={setEnabled.isPending}
              onClick={() =>
                setEnabled.mutate({ kind, path: site.file, enabled: true }, { onSuccess: done })
              }
            >
              {t("webservers.site.enable")}
            </Button>
          )}
          {domain.enabled && (
            <Button
              size="xs"
              variant="light"
              color="orange"
              disabled={props.readOnly || busy}
              loading={setMaintenance.isPending}
              onClick={() =>
                domain.maintenance
                  ? setMaintenance.mutate({ kind, path: site.file, on: false }, { onSuccess: done })
                  : setConfirm("maintenance")
              }
            >
              {domain.maintenance
                ? t("webservers.site.maintenanceOff")
                : t("webservers.site.maintenanceOn")}
            </Button>
          )}
          {plainName && domain.enabled && (
            <Button
              size="xs"
              variant="light"
              color="teal"
              disabled={props.readOnly}
              onClick={() => props.onCertificate(domain)}
            >
              {domain.ssl
                ? t("webservers.site.renewCertificate")
                : t("webservers.site.getCertificate")}
            </Button>
          )}
          {plainName && domain.enabled && !props.monitored && (
            <Button size="xs" variant="light" onClick={() => props.onMonitor(url)}>
              {t("webservers.site.monitor")}
            </Button>
          )}
          {plainName && domain.enabled && (
            <Anchor href={url} target="_blank" rel="noopener noreferrer" size="sm" dir="ltr">
              {url}
            </Anchor>
          )}
        </Group>
        {props.readOnly && (
          <Text size="xs" c="dimmed">
            {t("webservers.readOnlyHint")}
          </Text>
        )}
        {error && <Alert color="red">{errorMessage(t, error)}</Alert>}
        <WebResultAlert result={result} />
        {cert && (
          <Text size="sm" c={days !== null && days < 14 ? "orange" : undefined}>
            {cert.error
              ? t(`errors.${cert.error}`, { defaultValue: cert.error })
              : t("webservers.site.certificate", {
                  issuer: cert.issuer ?? "—",
                  date: cert.not_after ? formatDateTime(cert.not_after, lang) : "—",
                  days: formatNumber(days ?? 0, lang),
                })}
          </Text>
        )}
        {files.length > 1 && (
          <Select
            label={t("webservers.site.file")}
            data={files}
            value={file}
            onChange={setFile}
            dir="ltr"
          />
        )}
        <Tabs defaultValue="config" keepMounted={false}>
          <Tabs.List mb="sm">
            <Tabs.Tab value="config">{t("webservers.site.tabs.config")}</Tabs.Tab>
            <Tabs.Tab value="logs">{t("webservers.site.tabs.logs")}</Tabs.Tab>
            <Tabs.Tab value="versions">{t("webservers.site.tabs.versions")}</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="config">
            {file && (
              <ConfigTab
                server={props.server}
                domain={domain}
                file={file}
                line={site.file === file ? site.line : null}
                readOnly={props.readOnly}
              />
            )}
          </Tabs.Panel>
          <Tabs.Panel value="logs">
            <LogsTab server={props.server} domain={domain} />
          </Tabs.Panel>
          <Tabs.Panel value="versions">
            {file && (
              <VersionsTab
                server={props.server}
                domain={domain}
                file={file}
                readOnly={props.readOnly}
              />
            )}
          </Tabs.Panel>
        </Tabs>
      </Stack>
      <ConfirmDialog
        opened={confirm !== null}
        title={
          confirm === "disable" ? t("webservers.site.disable") : t("webservers.site.maintenanceOn")
        }
        body={
          confirm === "disable"
            ? t("webservers.site.disableConfirm", { file: site.file })
            : t("webservers.site.maintenanceConfirm")
        }
        confirmLabel={
          confirm === "disable" ? t("webservers.site.disable") : t("webservers.site.maintenanceOn")
        }
        loading={busy}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          const after = { onSuccess: done, onSettled: () => setConfirm(null) };
          if (confirm === "disable") {
            setEnabled.mutate({ kind, path: site.file, enabled: false }, after);
          } else {
            setMaintenance.mutate({ kind, path: site.file, on: true }, after);
          }
        }}
      />
    </Drawer>
  );
}
