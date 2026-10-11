import {
  ActionIcon,
  Anchor,
  Button,
  Code,
  Collapse,
  CopyButton,
  Group,
  Stack,
  Table,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type BackupRun,
  type SortColumn,
  downloadUrl,
  isActive,
  isLatestSuccess,
  useDeleteRun,
} from "../api/backups";
import { errorMessage } from "../api/client";
import { formatBytes, formatDuration } from "../format";
import { formatDateTime } from "../i18n";
import { ConfirmDialog } from "./ConfirmDialog";
import { RunStatusBadge } from "./RunStatusBadge";

export interface SortState {
  sort: SortColumn;
  order: "asc" | "desc";
}

interface RunTableProps {
  runs: BackupRun[];
  showInstance?: boolean;
  sort?: SortState;
  onSort?: (sort: SortState) => void;
}

function StatusCell({ run }: { run: BackupRun }) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <Stack gap={4}>
      <RunStatusBadge status={run.status} />
      {run.status === "running" && (
        <Text size="xs" c="dimmed">
          {t("backups.progress", {
            size: formatBytes(run.bytes_processed, t, i18n.language),
            elapsed: formatDuration(run.elapsed_ms, t, i18n.language),
          })}
        </Text>
      )}
      {run.status === "queued" && (
        <Text size="xs" c="dimmed">
          {t("backups.waiting")}
        </Text>
      )}
      {run.status === "failed" && run.error_code && (
        <>
          <Text size="xs" c="red">
            {t(`errors.${run.error_code}`, { defaultValue: t("errors.internal_error") })}
          </Text>
          <Anchor component="button" size="xs" onClick={() => setOpen((v) => !v)}>
            {t("backups.details")}
          </Anchor>
          <Collapse in={open}>
            <Text size="xs">{t(`backups.explain.${run.error_code}`, { defaultValue: "" })}</Text>
            {run.error_message && (
              <Code block mt={4} dir="ltr" style={{ whiteSpace: "pre-wrap", maxWidth: 420 }}>
                {run.error_message}
              </Code>
            )}
          </Collapse>
        </>
      )}
    </Stack>
  );
}

function SortHeader({
  column,
  label,
  sort,
  onSort,
}: {
  column: SortColumn;
  label: string;
  sort?: SortState;
  onSort?: (sort: SortState) => void;
}) {
  const { t } = useTranslation();
  if (!onSort) return <Table.Th>{label}</Table.Th>;
  const active = sort?.sort === column;
  const arrow = active ? (sort?.order === "asc" ? " ▲" : " ▼") : "";
  return (
    <Table.Th>
      <UnstyledButton
        aria-label={t("history.sortBy", { column: label })}
        onClick={() =>
          onSort({ sort: column, order: active && sort?.order === "desc" ? "asc" : "desc" })
        }
        fw={active ? 700 : 600}
        fz="sm"
      >
        {label}
        {arrow}
      </UnstyledButton>
    </Table.Th>
  );
}

export function RunTable({ runs, showInstance = false, sort, onSort }: RunTableProps) {
  const { t, i18n } = useTranslation();
  const remove = useDeleteRun();
  const [pending, setPending] = useState<{ run: BackupRun; latest: boolean } | null>(null);

  const askDelete = async (run: BackupRun) => {
    let latest = false;
    try {
      latest = await isLatestSuccess(run);
    } catch {
      // Fall back to the regular confirmation text.
    }
    setPending({ run, latest });
  };

  const confirmDelete = () => {
    if (!pending) return;
    remove.mutate(pending.run.id, {
      onSuccess: () => {
        notifications.show({ color: "green", message: t("history.deleted") });
        setPending(null);
      },
      onError: (error) => {
        notifications.show({ color: "red", message: errorMessage(t, error) });
        setPending(null);
      },
    });
  };

  const header = (column: SortColumn, label: string) => (
    <SortHeader column={column} label={label} sort={sort} onSort={onSort} />
  );

  return (
    <>
      <Table.ScrollContainer minWidth={900}>
        <Table verticalSpacing="sm" highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              {showInstance && header("instance_name", t("backups.columns.instance"))}
              {header("database_name", t("backups.columns.database"))}
              {header("status", t("backups.columns.status"))}
              {header("requested_at", t("backups.columns.requested"))}
              {header("duration_ms", t("backups.columns.duration"))}
              {header("file_size", t("backups.columns.size"))}
              <Table.Th>{t("backups.columns.compression")}</Table.Th>
              <Table.Th>{t("backups.columns.checksum")}</Table.Th>
              <Table.Th>{t("backups.columns.actions")}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {runs.map((run) => (
              <Table.Tr key={run.id}>
                {showInstance && (
                  <Table.Td>
                    {run.instance_id === null
                      ? t("history.deletedInstance", { name: run.instance_name })
                      : run.instance_name}
                  </Table.Td>
                )}
                <Table.Td>
                  <span dir="ltr">{run.database_name}</span>
                </Table.Td>
                <Table.Td>
                  <StatusCell run={run} />
                </Table.Td>
                <Table.Td>{formatDateTime(run.requested_at, i18n.language)}</Table.Td>
                <Table.Td>{formatDuration(run.duration_ms, t, i18n.language)}</Table.Td>
                <Table.Td>{formatBytes(run.file_size, t, i18n.language)}</Table.Td>
                <Table.Td>
                  {run.compression
                    ? t(`backups.compression.${run.compression}`)
                    : t("common.notAvailable")}
                </Table.Td>
                <Table.Td>
                  {run.checksum_sha256 ? (
                    <CopyButton value={run.checksum_sha256}>
                      {({ copied, copy }) => (
                        <Tooltip label={copied ? t("backups.copied") : t("backups.copy")}>
                          <UnstyledButton onClick={copy}>
                            <Code dir="ltr">{run.checksum_sha256!.slice(0, 12)}…</Code>
                          </UnstyledButton>
                        </Tooltip>
                      )}
                    </CopyButton>
                  ) : (
                    t("common.notAvailable")
                  )}
                </Table.Td>
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    {run.status === "success" &&
                      (run.file_available ? (
                        <Button
                          component="a"
                          href={downloadUrl(run.id)}
                          download
                          size="xs"
                          variant="light"
                        >
                          {t("backups.download")}
                        </Button>
                      ) : (
                        <Button size="xs" variant="light" disabled>
                          {t("backups.fileMissing")}
                        </Button>
                      ))}
                    {!isActive(run) && (
                      <Tooltip label={t("backups.delete")}>
                        <ActionIcon
                          color="red"
                          variant="subtle"
                          aria-label={t("backups.delete")}
                          onClick={() => void askDelete(run)}
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                            <path
                              d="M6 6l12 12M18 6L6 18"
                              stroke="currentColor"
                              strokeWidth="2.5"
                              strokeLinecap="round"
                            />
                          </svg>
                        </ActionIcon>
                      </Tooltip>
                    )}
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>

      <ConfirmDialog
        opened={pending !== null}
        title={t("history.deleteTitle")}
        body={
          pending
            ? t(pending.latest ? "history.deleteConfirmLatest" : "history.deleteConfirm", {
                database: pending.run.database_name,
                date: formatDateTime(pending.run.requested_at, i18n.language),
              })
            : ""
        }
        confirmLabel={t("backups.delete")}
        loading={remove.isPending}
        onConfirm={confirmDelete}
        onCancel={() => setPending(null)}
      />
    </>
  );
}
