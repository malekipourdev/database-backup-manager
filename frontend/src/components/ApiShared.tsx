import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Code,
  CopyButton,
  Group,
  Modal,
  MultiSelect,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { type Server, useServers } from "../api/servers";

import { Check, Copy, Warning } from "./Icons";

const METHOD_COLORS: Record<string, string> = {
  GET: "blue",
  POST: "green",
  PUT: "orange",
  PATCH: "yellow",
  DELETE: "red",
};

export function MethodBadge({ method }: { method: string }) {
  const upper = method.toUpperCase();
  return (
    <Badge
      color={METHOD_COLORS[upper] ?? "gray"}
      variant="light"
      radius="sm"
      w={64}
      ff="var(--font-mono)"
      style={{ flexShrink: 0 }}
    >
      {upper}
    </Badge>
  );
}

export function HttpStatusBadge({ status }: { status: number }) {
  const color = status >= 500 ? "red" : status >= 400 ? "orange" : status >= 300 ? "gray" : "green";
  return (
    <Badge color={color} variant="light" radius="sm" ff="var(--font-mono)">
      {status}
    </Badge>
  );
}

export function CopyIcon({ value }: { value: string }) {
  const { t } = useTranslation();
  return (
    <CopyButton value={value} timeout={1500}>
      {({ copied, copy }) => (
        <Tooltip label={copied ? t("backups.copied") : t("backups.copy")} withArrow>
          <ActionIcon
            variant="subtle"
            color={copied ? "green" : "gray"}
            onClick={copy}
            aria-label={t("backups.copy")}
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
          </ActionIcon>
        </Tooltip>
      )}
    </CopyButton>
  );
}

/** Monospace text on one line with a copy button (an address, a key prefix). */
export function CopyLine({ value, label }: { value: string; label?: string }) {
  return (
    <Group gap={6} wrap="nowrap">
      <TextInput
        readOnly
        value={value}
        dir="ltr"
        aria-label={label}
        styles={{ input: { fontFamily: "var(--font-mono)" } }}
        style={{ flex: 1, minWidth: 0 }}
        onFocus={(e) => e.currentTarget.select()}
      />
      <CopyIcon value={value} />
    </Group>
  );
}

/** A block of code (a command, a payload) with a copy button. */
export function CodeBlock({
  code,
  title,
  maxHeight,
}: {
  code: string;
  title?: ReactNode;
  maxHeight?: number;
}) {
  return (
    <Paper withBorder radius="md" style={{ overflow: "hidden" }}>
      <Group
        justify="space-between"
        px="sm"
        py={4}
        style={{ borderBottom: "1px solid var(--color-neutral-800)" }}
      >
        <Text size="xs" c="dimmed" fw={500}>
          {title}
        </Text>
        <CopyIcon value={code} />
      </Group>
      <ScrollArea.Autosize mah={maxHeight ?? 360} type="auto">
        <Code
          block
          dir="ltr"
          style={{ background: "transparent", whiteSpace: "pre", fontSize: 12.5, lineHeight: 1.6 }}
        >
          {code}
        </Code>
      </ScrollArea.Autosize>
    </Paper>
  );
}

/** A secret (key, signing secret) shown once, right after it was made. */
export function SecretModal(props: {
  opened: boolean;
  title: string;
  hint: string;
  secret: string;
  children?: ReactNode;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Modal
      opened={props.opened}
      onClose={props.onClose}
      title={props.title}
      size="lg"
      centered
      closeOnClickOutside={false}
    >
      <Stack gap="md">
        <Alert color="yellow" variant="light" icon={<Warning size={18} />}>
          {props.hint}
        </Alert>
        <CopyLine value={props.secret} label={props.title} />
        {props.children}
        <Group justify="flex-end">
          <Button onClick={props.onClose}>{t("api.secretSaved")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** A number with a caption, for the summary row. */
export function Stat(props: { label: string; value: ReactNode; icon: ReactNode; color: string }) {
  return (
    <Paper withBorder p="md" radius="md">
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
        <div style={{ minWidth: 0 }}>
          <Text fw={700} size="xl" lh={1.1}>
            {props.value}
          </Text>
          <Text size="sm" c="dimmed" truncate>
            {props.label}
          </Text>
        </div>
      </Group>
    </Paper>
  );
}

/** Which servers a key reaches, or whose events a webhook gets: all of them, or some. */
export function ServerLimitPicker(props: {
  value: number[] | null;
  onChange: (value: number[] | null) => void;
  label: string;
  allHint: string;
  someHint: string;
  error?: string | null;
}) {
  const { t } = useTranslation();
  const servers = useServers().data ?? [];
  const some = props.value !== null;
  return (
    <div>
      <Text size="sm" fw={500} mb={6}>
        {props.label}
      </Text>
      <SegmentedControl
        fullWidth
        value={some ? "some" : "all"}
        onChange={(v) => props.onChange(v === "all" ? null : (props.value ?? []))}
        data={[
          { value: "all", label: t("api.servers.all") },
          { value: "some", label: t("api.servers.some") },
        ]}
      />
      <Text size="xs" c="dimmed" mt={6}>
        {some ? props.someHint : props.allHint}
      </Text>
      {some && (
        <MultiSelect
          mt="sm"
          data={servers.map((s) => ({ value: String(s.id), label: serverLabel(t, s) }))}
          value={(props.value ?? []).map(String)}
          onChange={(ids) => props.onChange(ids.map(Number))}
          placeholder={t("api.servers.pick")}
          aria-label={props.label}
          error={props.error}
          searchable
        />
      )}
    </div>
  );
}

function serverLabel(t: (k: string) => string, server: Server): string {
  return server.kind === "local" ? `${server.name} (${t("api.servers.local")})` : server.name;
}

/** The servers of a key or webhook, as badges. */
export function ServerLimitSummary({ ids }: { ids: number[] | null }) {
  const { t } = useTranslation();
  const servers = useServers().data ?? [];
  if (ids === null) {
    return (
      <Badge variant="light" color="grape">
        {t("api.servers.all")}
      </Badge>
    );
  }
  if (ids.length === 0) {
    return (
      <Badge variant="light" color="red">
        {t("api.servers.none")}
      </Badge>
    );
  }
  const names = new Map(servers.map((s) => [s.id, s.name]));
  return (
    <Group gap={4}>
      {ids.map((id) => (
        <Badge key={id} variant="light" color="cyan" size="sm">
          {names.get(id) ?? `#${id}`}
        </Badge>
      ))}
    </Group>
  );
}
