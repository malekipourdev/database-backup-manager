import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  TagsInput,
  Text,
  TextInput,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { errorMessage } from "../api/client";
import type { ServerRef } from "../api/containers";
import {
  type SiteTemplate,
  type WebResult,
  type WebServerKind,
  useCreateSite,
  usePhpSockets,
  useStartJob,
  useWebJob,
} from "../api/webservers";

const KIND_LABEL: Record<WebServerKind, string> = { nginx: "nginx", apache: "Apache" };

/** The outcome of a change: done, or why the web server refused it (with its output). */
export function WebResultAlert({ result }: { result: WebResult | null | undefined }) {
  const { t } = useTranslation();
  if (!result) return null;
  if (result.ok) {
    return (
      <Alert color="green" data-testid="web-result">
        {t("webservers.result.ok")}
      </Alert>
    );
  }
  return (
    <Alert
      color="red"
      data-testid="web-result"
      title={t(`webservers.result.${result.code}`, {
        defaultValue: t("webservers.result.failed"),
      })}
    >
      <Stack gap={6}>
        <Text size="sm">{t("webservers.result.undone")}</Text>
        {result.output && (
          <Code block dir="ltr" style={{ maxHeight: 220, overflow: "auto" }}>
            {result.output}
          </Code>
        )}
      </Stack>
    </Alert>
  );
}

/** A certbot job's progress, polled until it ends. */
export function JobPanel({ server, id }: { server: ServerRef; id: string }) {
  const { t } = useTranslation();
  const job = useWebJob(server, id);
  if (job.isError) return <Alert color="red">{errorMessage(t, job.error)}</Alert>;
  const data = job.data;
  return (
    <Stack gap="xs" data-testid="web-job">
      <Group gap="xs">
        {(!data || data.status === "running") && <Loader size="xs" />}
        <Badge
          color={data?.status === "success" ? "green" : data?.status === "failed" ? "red" : "blue"}
          variant="light"
        >
          {t(`webservers.job.${data?.status ?? "running"}`)}
        </Badge>
      </Group>
      {data?.output && (
        <Code block dir="ltr" style={{ maxHeight: 260, overflow: "auto" }}>
          {data.output}
        </Code>
      )}
    </Stack>
  );
}

const TEMPLATES: SiteTemplate[] = ["proxy", "php", "static", "redirect"];

export function NewSiteModal(props: {
  opened: boolean;
  onClose: () => void;
  server: ServerRef;
  kinds: WebServerKind[];
  /** Published container ports to offer as proxy targets. */
  targets: { label: string; value: string }[];
}) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<WebServerKind>(props.kinds[0] ?? "nginx");
  const [template, setTemplate] = useState<SiteTemplate>("proxy");
  const [domains, setDomains] = useState<string[]>([]);
  const [target, setTarget] = useState("http://127.0.0.1:8080");
  const [root, setRoot] = useState("/var/www/");
  const [fpm, setFpm] = useState("");
  const [permanent, setPermanent] = useState(true);
  const [keepPath, setKeepPath] = useState(true);
  const create = useCreateSite(props.server);
  const sockets = usePhpSockets(props.server, props.opened && template === "php");
  useEffect(() => {
    if (!fpm && sockets.data?.sockets[0]) setFpm(sockets.data.sockets[0]);
  }, [sockets.data, fpm]);
  useEffect(() => {
    if (props.kinds.length && !props.kinds.includes(kind)) setKind(props.kinds[0]);
  }, [props.kinds, kind]);

  const close = () => {
    create.reset();
    props.onClose();
  };
  const submit = () =>
    create.mutate({
      kind,
      template,
      domains,
      target: template === "proxy" || template === "redirect" ? target : null,
      root: template === "php" || template === "static" ? root : null,
      php_fpm: template === "php" ? fpm : null,
      permanent,
      keep_path: keepPath,
    });

  return (
    <Modal opened={props.opened} onClose={close} title={t("webservers.new.title")} size="lg">
      <Stack gap="md">
        {props.kinds.length > 1 && (
          <SegmentedControl
            value={kind}
            onChange={(v) => setKind(v as WebServerKind)}
            data={props.kinds.map((k) => ({ value: k, label: KIND_LABEL[k] }))}
          />
        )}
        <SegmentedControl
          value={template}
          onChange={(v) => setTemplate(v as SiteTemplate)}
          data={TEMPLATES.map((v) => ({ value: v, label: t(`webservers.new.templates.${v}`) }))}
        />
        <Text size="sm" c="dimmed">
          {t(`webservers.new.hints.${template}`)}
        </Text>
        <TagsInput
          label={t("webservers.new.domains")}
          description={t("webservers.new.domainsHint")}
          placeholder={`example.com`}
          value={domains}
          onChange={setDomains}
          dir="ltr"
          splitChars={[",", " "]}
          required
        />
        {template === "proxy" && (
          <>
            <TextInput
              label={t("webservers.new.target")}
              description={t("webservers.new.targetHint")}
              value={target}
              onChange={(e) => setTarget(e.currentTarget.value)}
              dir="ltr"
            />
            {props.targets.length > 0 && (
              <Select
                label={t("webservers.new.fromContainer")}
                placeholder={t("webservers.new.pickContainer")}
                data={props.targets}
                onChange={(v) => v && setTarget(v)}
                searchable
                clearable
              />
            )}
          </>
        )}
        {template === "redirect" && (
          <>
            <TextInput
              label={t("webservers.new.redirectTo")}
              placeholder={`https://example.com`}
              value={target}
              onChange={(e) => setTarget(e.currentTarget.value)}
              dir="ltr"
            />
            <Switch
              label={t("webservers.new.permanent")}
              checked={permanent}
              onChange={(e) => setPermanent(e.currentTarget.checked)}
            />
            <Switch
              label={t("webservers.new.keepPath")}
              checked={keepPath}
              onChange={(e) => setKeepPath(e.currentTarget.checked)}
            />
          </>
        )}
        {(template === "php" || template === "static") && (
          <TextInput
            label={t("webservers.new.root")}
            value={root}
            onChange={(e) => setRoot(e.currentTarget.value)}
            dir="ltr"
          />
        )}
        {template === "php" && (
          <Select
            label={t("webservers.new.fpm")}
            description={t("webservers.new.fpmHint")}
            data={[...new Set([...(sockets.data?.sockets ?? []), ...(fpm ? [fpm] : [])])]}
            value={fpm || null}
            onChange={(v) => setFpm(v ?? "")}
            searchable
            onSearchChange={(v) => v && setFpm(v)}
            dir="ltr"
          />
        )}
        <Text size="xs" c="dimmed">
          {t("webservers.new.safety")}
        </Text>
        {create.isError && <Alert color="red">{errorMessage(t, create.error)}</Alert>}
        <WebResultAlert result={create.data} />
        <Group justify="flex-end">
          <Button variant="default" onClick={close}>
            {create.data?.ok ? t("common.close") : t("common.cancel")}
          </Button>
          {!create.data?.ok && (
            <Button onClick={submit} loading={create.isPending} disabled={domains.length === 0}>
              {t("webservers.new.create")}
            </Button>
          )}
        </Group>
      </Stack>
    </Modal>
  );
}

/** Get a Let's Encrypt certificate with certbot for some names, then follow the job. */
export function CertbotModal(props: {
  opened: boolean;
  onClose: () => void;
  server: ServerRef;
  kind: WebServerKind;
  domains: string[];
  installed: boolean;
}) {
  const { t } = useTranslation();
  const [domains, setDomains] = useState<string[]>(props.domains);
  const [email, setEmail] = useState("");
  const [redirect, setRedirect] = useState(true);
  const start = useStartJob(props.server);
  useEffect(() => {
    if (props.opened) {
      setDomains(props.domains);
      start.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.opened]);
  const job = start.data?.id ?? null;
  return (
    <Modal
      opened={props.opened}
      onClose={props.onClose}
      title={t("webservers.certbot.title")}
      size="lg"
    >
      <Stack gap="md">
        {!props.installed && <Alert color="yellow">{t("webservers.certbot.notInstalled")}</Alert>}
        <Text size="sm">{t("webservers.certbot.intro")}</Text>
        <TagsInput
          label={t("webservers.new.domains")}
          value={domains}
          onChange={setDomains}
          dir="ltr"
          splitChars={[",", " "]}
          disabled={Boolean(job)}
        />
        <TextInput
          label={t("webservers.certbot.email")}
          description={t("webservers.certbot.emailHint")}
          value={email}
          onChange={(e) => setEmail(e.currentTarget.value)}
          dir="ltr"
          disabled={Boolean(job)}
        />
        <Switch
          label={t("webservers.certbot.redirect")}
          checked={redirect}
          onChange={(e) => setRedirect(e.currentTarget.checked)}
          disabled={Boolean(job)}
        />
        {start.isError && <Alert color="red">{errorMessage(t, start.error)}</Alert>}
        {job && <JobPanel server={props.server} id={job} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={props.onClose}>
            {job ? t("common.close") : t("common.cancel")}
          </Button>
          {!job && (
            <Button
              loading={start.isPending}
              disabled={domains.length === 0 || !props.installed}
              onClick={() =>
                start.mutate({
                  path: `/webservers/${props.kind}/certbot/issue`,
                  body: { domains, email: email.trim() || null, redirect },
                })
              }
            >
              {t("webservers.certbot.issue")}
            </Button>
          )}
        </Group>
      </Stack>
    </Modal>
  );
}
