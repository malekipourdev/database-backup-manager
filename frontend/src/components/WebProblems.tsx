import {
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import type { ReactNode } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { errorMessage } from "../api/client";
import type { ServerRef } from "../api/containers";
import {
  type WebProblem,
  type WebServer,
  type WebServerKind,
  useRemoveBrokenLinks,
} from "../api/webservers";
import { formatNumber } from "../i18n";
import { ConfirmDialog } from "./ConfirmDialog";
import { CheckCircle, FileDashed, FileX, LinkBreak, Warning } from "./Icons";
import { WebResultAlert } from "./WebDialogs";

const KIND_LABEL: Record<WebServerKind, string> = { nginx: "nginx", apache: "Apache" };

export interface Problem extends WebProblem {
  server: WebServerKind;
}

export function problemsOf(servers: WebServer[]): Problem[] {
  return servers.flatMap((ws) => (ws.problems ?? []).map((p) => ({ ...p, server: ws.kind })));
}

function Path({ children }: { children: ReactNode }) {
  return (
    <Text
      component="code"
      size="sm"
      dir="ltr"
      ff="var(--font-mono)"
      style={{ overflowWrap: "anywhere", display: "block", textAlign: "start" }}
    >
      {children}
    </Text>
  );
}

function Section(props: {
  icon: ReactNode;
  color: string;
  title: string;
  hint: string;
  count: number;
  action?: ReactNode;
  children: ReactNode;
}) {
  const { i18n } = useTranslation();
  return (
    <Paper withBorder p={0} style={{ overflow: "hidden" }}>
      <Group
        justify="space-between"
        px="md"
        py="sm"
        wrap="nowrap"
        align="flex-start"
        style={{
          borderBottom: "1px solid var(--color-neutral-800)",
          borderInlineStart: `3px solid var(--mantine-color-${props.color}-6)`,
        }}
      >
        <Group gap="sm" wrap="nowrap" align="flex-start">
          <span style={{ color: `var(--mantine-color-${props.color}-5)`, marginTop: 2 }}>
            {props.icon}
          </span>
          <div>
            <Group gap={8}>
              <Title order={5}>{props.title}</Title>
              <Badge color={props.color} variant="light">
                {formatNumber(props.count, i18n.language)}
              </Badge>
            </Group>
            <Text size="sm" c="dimmed" maw={720}>
              {props.hint}
            </Text>
          </div>
        </Group>
        {props.action}
      </Group>
      <Table.ScrollContainer minWidth={560}>{props.children}</Table.ScrollContainer>
    </Paper>
  );
}

function Tile(props: { icon: ReactNode; color: string; label: string; count: number }) {
  const { i18n } = useTranslation();
  return (
    <Paper withBorder p="md" style={{ opacity: props.count ? 1 : 0.55 }}>
      <Group gap="sm" wrap="nowrap">
        <span
          className="cl-icon-tile"
          style={{
            color: `var(--mantine-color-${props.color}-4)`,
            background: `color-mix(in srgb, var(--mantine-color-${props.color}-9) 35%, transparent)`,
          }}
        >
          {props.icon}
        </span>
        <div>
          <Text fw={700} size="xl" lh={1.1}>
            {formatNumber(props.count, i18n.language)}
          </Text>
          <Text size="sm" c="dimmed">
            {props.label}
          </Text>
        </div>
      </Group>
    </Paper>
  );
}

/** The configuration problems found while reading the web servers, grouped by what they are. */
export function ProblemsTab(props: { server: ServerRef; servers: WebServer[]; readOnly: boolean }) {
  const { t } = useTranslation();
  const problems = problemsOf(props.servers);
  const remove = useRemoveBrokenLinks(props.server);
  const [confirm, setConfirm] = useState<WebServerKind | null>(null);
  const broken = problems.filter((p) => p.kind === "broken_link");
  const unreadable = problems.filter((p) => p.kind === "unreadable");
  const includes = problems.filter((p) => p.kind === "include_missing");
  const other = problems.filter((p) => p.kind === "too_deep" || p.kind === "other");
  const errors = props.servers.filter((ws) => ws.error);

  if (problems.length === 0 && errors.length === 0) {
    return (
      <Paper withBorder p="xl" data-testid="no-problems">
        <Stack align="center" gap="xs">
          <span className="cl-icon-tile" style={{ color: "var(--mantine-color-green-5)" }}>
            <CheckCircle size={22} />
          </span>
          <Text fw={500}>{t("webservers.problems.none")}</Text>
          <Text size="sm" c="dimmed" ta="center" maw={480}>
            {t("webservers.problems.noneHint")}
          </Text>
        </Stack>
      </Paper>
    );
  }

  const brokenKinds = [...new Set(broken.map((p) => p.server))];
  return (
    <Stack gap="md" data-testid="problems">
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing={12}>
        <Tile
          icon={<LinkBreak size={20} />}
          color="red"
          label={t("webservers.problems.broken.short")}
          count={broken.length}
        />
        <Tile
          icon={<FileX size={20} />}
          color="orange"
          label={t("webservers.problems.unreadable.short")}
          count={unreadable.length}
        />
        <Tile
          icon={<FileDashed size={20} />}
          color="yellow"
          label={t("webservers.problems.include.short")}
          count={includes.length}
        />
        <Tile
          icon={<Warning size={20} />}
          color="gray"
          label={t("webservers.problems.other.short")}
          count={other.length + errors.length}
        />
      </SimpleGrid>

      {errors.map((ws) => (
        <Alert
          key={ws.kind}
          color="red"
          title={t("webservers.problems.mainError", { name: KIND_LABEL[ws.kind] })}
        >
          <Path>{ws.error}</Path>
        </Alert>
      ))}

      {remove.isError && <Alert color="red">{errorMessage(t, remove.error)}</Alert>}
      <WebResultAlert result={remove.data} />

      {broken.length > 0 && (
        <Section
          icon={<LinkBreak size={20} />}
          color="red"
          title={t("webservers.problems.broken.title")}
          hint={t("webservers.problems.broken.hint")}
          count={broken.length}
          action={
            <Group gap="xs" wrap="nowrap">
              {brokenKinds.map((kind) => (
                <Button
                  key={kind}
                  size="xs"
                  color="red"
                  variant="light"
                  disabled={props.readOnly}
                  loading={remove.isPending && remove.variables?.kind === kind}
                  onClick={() => setConfirm(kind)}
                >
                  {brokenKinds.length > 1
                    ? t("webservers.problems.broken.removeFor", { name: KIND_LABEL[kind] })
                    : t("webservers.problems.broken.remove")}
                </Button>
              ))}
            </Group>
          }
        >
          <Table verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("webservers.problems.broken.link")}</Table.Th>
                <Table.Th>{t("webservers.problems.broken.target")}</Table.Th>
                <Table.Th w={90}>{t("webservers.columns.server")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {broken.map((p) => (
                <Table.Tr key={`${p.server}${p.path}`}>
                  <Table.Td>
                    <Path>{p.path}</Path>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c="red.4" dir="ltr" ta="start" ff="var(--font-mono)">
                      {p.target}
                    </Text>
                  </Table.Td>
                  <Table.Td>{KIND_LABEL[p.server]}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Section>
      )}

      {unreadable.length > 0 && (
        <Section
          icon={<FileX size={20} />}
          color="orange"
          title={t("webservers.problems.unreadable.title")}
          hint={t("webservers.problems.unreadable.hint")}
          count={unreadable.length}
        >
          <Table verticalSpacing="xs">
            <Table.Tbody>
              {unreadable.map((p) => (
                <Table.Tr key={`${p.server}${p.path}`}>
                  <Table.Td>
                    <Path>{p.path}</Path>
                  </Table.Td>
                  <Table.Td w={220}>
                    <Badge color="orange" variant="light">
                      {t(`webservers.problems.reasons.${p.reason ?? "unreadable"}`, {
                        defaultValue: p.reason ?? "",
                      })}
                    </Badge>
                  </Table.Td>
                  <Table.Td w={90}>{KIND_LABEL[p.server]}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Section>
      )}

      {includes.length > 0 && (
        <Section
          icon={<FileDashed size={20} />}
          color="yellow"
          title={t("webservers.problems.include.title")}
          hint={t("webservers.problems.include.hint")}
          count={includes.length}
        >
          <Table verticalSpacing="xs">
            <Table.Tbody>
              {includes.map((p) => (
                <Table.Tr key={`${p.server}${p.path}${p.source}${p.line}`}>
                  <Table.Td>
                    <Path>{p.path}</Path>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {t("webservers.problems.include.in")}
                    </Text>
                    <Path>
                      {p.source}:{p.line}
                    </Path>
                  </Table.Td>
                  <Table.Td w={90}>{KIND_LABEL[p.server]}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Section>
      )}

      {other.length > 0 && (
        <Section
          icon={<Warning size={20} />}
          color="gray"
          title={t("webservers.problems.other.title")}
          hint={t("webservers.problems.other.hint")}
          count={other.length}
        >
          <Table verticalSpacing="xs">
            <Table.Tbody>
              {other.map((p, i) => (
                <Table.Tr key={i}>
                  <Table.Td>
                    <Path>
                      {p.kind === "too_deep"
                        ? `${t("webservers.problems.tooDeep")} — ${p.source}:${p.line}`
                        : p.message}
                    </Path>
                  </Table.Td>
                  <Table.Td w={90}>{KIND_LABEL[p.server]}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Section>
      )}

      <ConfirmDialog
        opened={confirm !== null}
        title={t("webservers.problems.broken.remove")}
        body={t("webservers.problems.broken.confirm", {
          n: broken.filter((p) => p.server === confirm).length,
        })}
        confirmLabel={t("webservers.problems.broken.remove")}
        loading={remove.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() =>
          confirm &&
          remove.mutate(
            {
              kind: confirm,
              paths: broken.filter((p) => p.server === confirm).map((p) => p.path ?? ""),
            },
            { onSettled: () => setConfirm(null) },
          )
        }
      />
    </Stack>
  );
}
