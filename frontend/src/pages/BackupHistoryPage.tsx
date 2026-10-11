import {
  Alert,
  Button,
  Group,
  Loader,
  MultiSelect,
  Pagination,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { type RunQuery, type RunStatus, type SortColumn, useRunHistory } from "../api/backups";
import { errorMessage } from "../api/client";
import { useInstances } from "../api/instances";
import { PageHeader } from "../components/PageHeader";
import { RunTable, type SortState } from "../components/RunTable";
import { formatNumber } from "../i18n";

const PAGE_SIZE = 50;
const STATUSES: RunStatus[] = ["queued", "running", "success", "failed"];
const SORTS: SortColumn[] = [
  "requested_at",
  "duration_ms",
  "file_size",
  "instance_name",
  "database_name",
  "status",
];

/** "YYYY-MM-DD" (local day) -> ISO instant at that day's local midnight, optionally +1 day. */
function dayToIso(day: string, addDays = 0): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date + addDays).toISOString();
}

export function queryFromParams(params: URLSearchParams): RunQuery {
  const instance = params.get("instance_id");
  const sort = params.get("sort") as SortColumn | null;
  const from = params.get("from");
  const to = params.get("to");
  return {
    instanceId: instance ? Number(instance) : undefined,
    database: params.get("database") || undefined,
    statuses: params
      .getAll("status")
      .filter((s): s is RunStatus => STATUSES.includes(s as RunStatus)),
    // The "to" day is inclusive in the UI and exclusive in the API.
    from: from ? dayToIso(from) : undefined,
    to: to ? dayToIso(to, 1) : undefined,
    sort: sort && SORTS.includes(sort) ? sort : "requested_at",
    order: params.get("order") === "asc" ? "asc" : "desc",
    page: Math.max(1, Number(params.get("page") ?? 1) || 1),
    pageSize: PAGE_SIZE,
  };
}

export function BackupHistoryPage() {
  const { t, i18n } = useTranslation();
  const [params, setParams] = useSearchParams();
  const query = queryFromParams(params);
  const history = useRunHistory(query);
  const instances = useInstances();

  const update = (changes: Record<string, string | string[] | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      next.delete(key);
      if (Array.isArray(value)) value.forEach((v) => next.append(key, v));
      else if (value) next.set(key, value);
    }
    if (!("page" in changes)) next.delete("page");
    setParams(next, { replace: true });
  };

  const sortState: SortState = { sort: query.sort ?? "requested_at", order: query.order ?? "desc" };
  const pages = Math.max(1, Math.ceil((history.data?.total ?? 0) / PAGE_SIZE));

  return (
    <Stack gap="md">
      <PageHeader title={t("history.title")} subtitle={t("history.subtitle")} />

      <Paper withBorder p="md">
        <Group align="flex-end" wrap="wrap" gap="sm">
          <Select
            label={t("history.instance")}
            placeholder={t("history.anyInstance")}
            clearable
            data={(instances.data ?? []).map((i) => ({ value: String(i.id), label: i.name }))}
            value={params.get("instance_id")}
            onChange={(value) => update({ instance_id: value })}
            w={200}
          />
          <TextInput
            label={t("history.database")}
            dir="ltr"
            value={params.get("database") ?? ""}
            onChange={(e) => update({ database: e.currentTarget.value })}
            w={180}
          />
          <MultiSelect
            label={t("history.status")}
            data={STATUSES.map((s) => ({ value: s, label: t(`runStatus.${s}`) }))}
            value={params.getAll("status")}
            onChange={(value) => update({ status: value })}
            w={240}
          />
          <TextInput
            type="date"
            label={t("history.from")}
            value={params.get("from") ?? ""}
            onChange={(e) => update({ from: e.currentTarget.value })}
            w={160}
          />
          <TextInput
            type="date"
            label={t("history.to")}
            value={params.get("to") ?? ""}
            onChange={(e) => update({ to: e.currentTarget.value })}
            w={160}
          />
          <Button variant="default" onClick={() => setParams(new URLSearchParams())}>
            {t("history.clear")}
          </Button>
        </Group>
      </Paper>

      {history.isPending && <Loader />}
      {history.isError && <Alert color="red">{errorMessage(t, history.error)}</Alert>}
      {history.data && (
        <Paper withBorder>
          {history.data.items.length === 0 ? (
            <Text c="dimmed" p="lg" ta="center">
              {t("history.empty")}
            </Text>
          ) : (
            <RunTable
              runs={history.data.items}
              showInstance
              sort={sortState}
              onSort={(next) => update({ sort: next.sort, order: next.order })}
            />
          )}
        </Paper>
      )}

      {history.data && (
        <Group justify="space-between">
          <Text size="sm" c="dimmed">
            {t("history.total", {
              formattedCount: formatNumber(history.data.total, i18n.language),
            })}
          </Text>
          {pages > 1 && (
            <Pagination
              total={pages}
              value={query.page ?? 1}
              onChange={(page) => update({ page: String(page) })}
            />
          )}
        </Group>
      )}
    </Stack>
  );
}
