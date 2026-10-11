import { Alert, Badge, Button, Loader, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useRunHistory } from "../api/backups";
import { errorMessage } from "../api/client";
import { type Instance, useInstances } from "../api/instances";
import { useRemoteStorage } from "../api/storage";
import { CloudArrowUp, CloudCheck, Database, HardDrives, Plus } from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { formatDateTime, formatNumber } from "../i18n";

function startOfToday(): string {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
}

function Stat(props: { icon: React.ReactNode; label: string; value: string; note: string }) {
  return (
    <div className="cl-stat">
      <div className="cl-stat-label">
        {props.icon}
        <span>{props.label}</span>
      </div>
      <div className="cl-stat-value">{props.value}</div>
      <div className="cl-stat-note">{props.note}</div>
    </div>
  );
}

function Stats({ instances }: { instances: Instance[] }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const today = useRunHistory({ from: startOfToday(), page: 1, pageSize: 200 });
  const remote = useRemoteStorage();
  const runs = today.data?.items ?? [];
  const count = (status: string) => runs.filter((r) => r.status === status).length;
  const ok = instances.filter((i) => i.last_test_ok === true).length;
  const bad = instances.filter((i) => i.last_test_ok === false).length;
  const remoteOn = remote.data && remote.data.has_secret && remote.data.bucket;
  let endpoint = t("instances.stats.aws");
  try {
    if (remote.data?.endpoint_url) endpoint = new URL(remote.data.endpoint_url).hostname;
  } catch {
    // keep the default label
  }
  return (
    <SimpleGrid cols={{ base: 1, xs: 3 }} spacing={12}>
      <Stat
        icon={<HardDrives size={15} />}
        label={t("instances.stats.servers")}
        value={formatNumber(instances.length, lang)}
        note={t("instances.stats.serversNote", {
          ok: formatNumber(ok, lang),
          bad: formatNumber(bad, lang),
        })}
      />
      <Stat
        icon={<CloudCheck size={15} />}
        label={t("instances.stats.today")}
        value={formatNumber(count("success"), lang)}
        note={t("instances.stats.todayNote", {
          failed: formatNumber(count("failed"), lang),
          running: formatNumber(count("running") + count("queued"), lang),
        })}
      />
      <Stat
        icon={<CloudArrowUp size={15} />}
        label={t("instances.stats.remote")}
        value={remoteOn ? remote.data!.bucket : t("instances.stats.remoteOff")}
        note={
          remoteOn
            ? `${endpoint} · ${
                remote.data!.enabled
                  ? t("instances.stats.uploadOn")
                  : t("instances.stats.uploadOff")
              }`
            : t("instances.stats.remoteHint")
        }
      />
    </SimpleGrid>
  );
}

function InstanceCard({ instance }: { instance: Instance }) {
  const { t, i18n } = useTranslation();
  const tone =
    instance.last_test_ok === true ? "ok" : instance.last_test_ok === false ? "bad" : undefined;
  return (
    <Link to={`/instances/${instance.id}`} className="cl-card">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span className="cl-icon-tile">
          <Database size={20} />
        </span>
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 3 }}>
          <Text fw={500} truncate>
            {instance.name}
          </Text>
          <Text size="xs" c="var(--color-neutral-500)" dir="ltr" ta="start">
            {instance.server_type
              ? `${t(`connection.serverType.${instance.server_type}`)} ${instance.server_version}`
              : t("common.notAvailable")}
          </Text>
        </div>
        <span className="cl-dot" data-tone={tone} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div className="cl-kv">
          <span>{t("instances.columns.address")}</span>
          <code dir="ltr">
            {instance.host}:{instance.port}
          </code>
        </div>
        <div className="cl-kv">
          <span>{t("instances.columns.username")}</span>
          <code dir="ltr">{instance.username}</code>
        </div>
      </div>
      <div className="cl-card-foot">
        {instance.last_test_at ? (
          <>
            <Badge color={instance.last_test_ok ? "green" : "red"} variant="light">
              {instance.last_test_ok
                ? t("instances.testOk")
                : t(`errors.${instance.last_test_error_code ?? "server_error"}`)}
            </Badge>
            <Text size="xs" c="var(--color-neutral-500)">
              {formatDateTime(instance.last_test_at, i18n.language)}
            </Text>
          </>
        ) : (
          <Badge color="gray" variant="light">
            {t("instances.notTested")}
          </Badge>
        )}
      </div>
    </Link>
  );
}

export function InstancesPage() {
  const { t } = useTranslation();
  const instances = useInstances();

  return (
    <Stack gap={18}>
      <PageHeader
        title={t("instances.title")}
        subtitle={t("instances.subtitle")}
        actions={
          <Button component={Link} to="/instances/new" leftSection={<Plus size={16} />}>
            {t("instances.add")}
          </Button>
        }
      />

      {instances.isPending && <Loader />}
      {instances.isError && <Alert color="red">{errorMessage(t, instances.error)}</Alert>}

      {instances.data && <Stats instances={instances.data} />}

      {instances.data && instances.data.length === 0 && (
        <Paper withBorder p="xl">
          <Stack align="center" gap="xs">
            <span className="cl-icon-tile">
              <Database size={20} />
            </span>
            <Text fw={500}>{t("instances.empty")}</Text>
            <Text c="dimmed" size="sm" ta="center">
              {t("instances.emptyHint")}
            </Text>
          </Stack>
        </Paper>
      )}

      {instances.data && instances.data.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(270px, 1fr))",
            gap: 12,
          }}
        >
          {instances.data.map((instance) => (
            <InstanceCard key={instance.id} instance={instance} />
          ))}
        </div>
      )}
    </Stack>
  );
}
