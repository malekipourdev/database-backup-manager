import {
  Alert,
  Badge,
  Button,
  Code,
  Drawer,
  Group,
  Loader,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
} from "@mantine/core";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { errorMessage } from "../api/client";
import { type ContainerDetails, useContainer, useContainerLogs } from "../api/containers";
import { formatDateTime, formatNumber } from "../i18n";
import { DownloadSimple } from "./Icons";
import { ContainerStateBadge } from "./ContainerStateBadge";

const TAILS = ["100", "500", "1000", "5000"];

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Table.Tr>
      <Table.Td w={160} c="var(--color-neutral-400)" style={{ verticalAlign: "top" }}>
        {label}
      </Table.Td>
      <Table.Td style={{ wordBreak: "break-word" }}>{children}</Table.Td>
    </Table.Tr>
  );
}

function Overview({ c }: { c: ContainerDetails }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const ltr = (value: React.ReactNode) => (
    <Text span dir="ltr" ff="var(--font-mono)" size="sm">
      {value}
    </Text>
  );
  return (
    <Stack gap="md">
      <Table verticalSpacing={6} withRowBorders={false}>
        <Table.Tbody>
          <Row label={t("containers.fields.state")}>
            <ContainerStateBadge c={c} />
          </Row>
          <Row label={t("containers.fields.image")}>{ltr(c.image)}</Row>
          {c.project && (
            <Row label={t("containers.fields.project")}>
              {ltr(c.service ? `${c.project} / ${c.service}` : c.project)}
            </Row>
          )}
          <Row label={t("containers.fields.id")}>{ltr(c.id)}</Row>
          {c.started_at && (
            <Row label={t("containers.fields.startedAt")}>{formatDateTime(c.started_at, lang)}</Row>
          )}
          {c.finished_at && c.state !== "running" && (
            <Row label={t("containers.fields.finishedAt")}>
              {formatDateTime(c.finished_at, lang)}
              {c.exit_code !== null &&
                ` — ${t("containers.exitCode", { code: formatNumber(c.exit_code, lang) })}`}
              {c.oom_killed && ` — ${t("containers.oom")}`}
            </Row>
          )}
          <Row label={t("containers.fields.restartPolicy")}>
            {t(`containers.policy.${c.restart_policy}`, { defaultValue: c.restart_policy })}
            {c.restart_count > 0 &&
              ` — ${t("containers.restarts", { n: formatNumber(c.restart_count, lang) })}`}
          </Row>
          {c.health && (
            <Row label={t("containers.fields.health")}>
              {t(`containers.health.${c.health}`, { defaultValue: c.health })}
              {c.health_last_output && c.health !== "healthy" && (
                <Code block mt={6} dir="ltr">
                  {c.health_last_output}
                </Code>
              )}
            </Row>
          )}
          <Row label={t("containers.fields.ports")}>
            {c.ports.length
              ? ltr(
                  c.ports
                    .map((p) =>
                      p.public ? `${p.public}→${p.private}/${p.type}` : `${p.private}/${p.type}`,
                    )
                    .join("  "),
                )
              : t("common.notAvailable")}
          </Row>
          <Row label={t("containers.fields.networks")}>
            {c.networks.length
              ? ltr(c.networks.map((n) => (n.ip ? `${n.name} (${n.ip})` : n.name)).join(", "))
              : t("common.notAvailable")}
          </Row>
          <Row label={t("containers.fields.mounts")}>
            {c.mounts.length ? (
              <Stack gap={2}>
                {c.mounts.map((m) => (
                  <Text key={`${m.source}-${m.destination}`} size="sm" dir="ltr" ta="start">
                    {`${m.source ?? "?"} → ${m.destination ?? "?"}`}
                    {m.read_only ? ` (${t("containers.readOnlyMount")})` : ""}
                  </Text>
                ))}
              </Stack>
            ) : (
              t("common.notAvailable")
            )}
          </Row>
          <Row label={t("containers.fields.env")}>
            <Stack gap={6}>
              <Group gap={4}>
                {c.env_names.map((name) => (
                  <Badge key={name} variant="outline" color="gray" tt="none" dir="ltr">
                    {name}
                  </Badge>
                ))}
              </Group>
              <Text size="xs" c="dimmed">
                {t("containers.envHint")}
              </Text>
            </Stack>
          </Row>
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function Logs({ name }: { name: string }) {
  const { t, i18n } = useTranslation();
  const [tail, setTail] = useState("500");
  const [follow, setFollow] = useState(false);
  const [filter, setFilter] = useState("");
  const logs = useContainerLogs(name, Number(tail), follow);
  const box = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => {
    const all = logs.data?.lines ?? [];
    const needle = filter.trim().toLowerCase();
    return needle ? all.filter((line) => line.text.toLowerCase().includes(needle)) : all;
  }, [logs.data, filter]);

  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines]);

  const download = () => {
    const text = (logs.data?.lines ?? [])
      .map((line) => `${line.time ?? ""} ${line.stream === "stderr" ? "[err] " : ""}${line.text}`)
      .join("\n");
    const url = URL.createObjectURL(new Blob([`${text}\n`], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name}.log`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Stack gap="sm">
      <Group gap="sm" wrap="wrap">
        <SegmentedControl
          size="xs"
          value={tail}
          onChange={setTail}
          data={TAILS.map((value) => ({
            value,
            label: formatNumber(Number(value), i18n.language),
          }))}
          aria-label={t("containers.logs.lines")}
        />
        <Switch
          size="sm"
          label={t("containers.logs.follow")}
          checked={follow}
          onChange={(e) => setFollow(e.currentTarget.checked)}
        />
        <TextInput
          size="xs"
          placeholder={t("containers.logs.search")}
          aria-label={t("containers.logs.search")}
          value={filter}
          onChange={(e) => setFilter(e.currentTarget.value)}
          style={{ flex: "1 1 140px" }}
        />
        <Button
          size="xs"
          variant="default"
          leftSection={<DownloadSimple size={14} />}
          onClick={download}
          disabled={!logs.data?.lines.length}
        >
          {t("containers.logs.download")}
        </Button>
      </Group>
      {logs.isPending && <Loader size="sm" />}
      {logs.isError && <Alert color="red">{errorMessage(t, logs.error)}</Alert>}
      {logs.data && (
        <div
          ref={box}
          dir="ltr"
          data-testid="log-box"
          style={{
            background: "var(--color-neutral-950, #0b0b10)",
            border: "1px solid var(--color-neutral-800)",
            borderRadius: 10,
            padding: "10px 12px",
            height: "60vh",
            overflow: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            lineHeight: 1.55,
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            textAlign: "left",
          }}
        >
          {lines.length === 0 && (
            <Text size="sm" c="dimmed">
              {t("containers.logs.empty")}
            </Text>
          )}
          {lines.map((line, index) => (
            <div
              key={index}
              style={{
                color: line.stream === "stderr" ? "var(--color-danger-300, #fca5a5)" : undefined,
              }}
            >
              {line.time && (
                <span style={{ color: "var(--color-neutral-500)" }}>
                  {line.time.slice(0, 19).replace("T", " ")}{" "}
                </span>
              )}
              {line.text}
            </div>
          ))}
        </div>
      )}
    </Stack>
  );
}

export function ContainerDrawer({ name, onClose }: { name: string | null; onClose: () => void }) {
  const { t } = useTranslation();
  const container = useContainer(name);
  return (
    <Drawer
      opened={Boolean(name)}
      onClose={onClose}
      position="right"
      size="xl"
      title={
        <Text fw={600} dir="ltr">
          {name}
        </Text>
      }
    >
      {container.isPending && <Loader size="sm" />}
      {container.isError && <Alert color="red">{errorMessage(t, container.error)}</Alert>}
      {container.data && name && (
        <Tabs defaultValue="overview" keepMounted={false}>
          <Tabs.List mb="md">
            <Tabs.Tab value="overview">{t("containers.tabs.overview")}</Tabs.Tab>
            <Tabs.Tab value="logs">{t("containers.tabs.logs")}</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="overview">
            <Overview c={container.data} />
          </Tabs.Panel>
          <Tabs.Panel value="logs">
            <Logs name={name} />
          </Tabs.Panel>
        </Tabs>
      )}
    </Drawer>
  );
}
