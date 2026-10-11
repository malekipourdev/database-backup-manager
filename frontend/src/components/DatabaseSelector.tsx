import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Pagination,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { errorMessage } from "../api/client";
import { type DatabaseList, useDatabases, useSaveSelection } from "../api/instances";
import { formatNumber } from "../i18n";

const PAGE_SIZE = 100;

function selectedOf(list: DatabaseList | undefined): Set<string> {
  return new Set(list?.databases.filter((d) => d.selected).map((d) => d.name) ?? []);
}

function sameSet(a: Set<string>, b: Set<string>): boolean {
  return a.size === b.size && [...a].every((x) => b.has(x));
}

interface DatabaseSelectorViewProps {
  list: DatabaseList;
  saving: boolean;
  onSave: (names: string[]) => void;
  onRetry: () => void;
}

/** Presentational part, separated so it can be tested without network access. */
export function DatabaseSelectorView({ list, saving, onSave, onRetry }: DatabaseSelectorViewProps) {
  const { t, i18n } = useTranslation();
  const [filter, setFilter] = useState("");
  const [showSystem, setShowSystem] = useState(false);
  const [page, setPage] = useState(1);
  const saved = useMemo(() => selectedOf(list), [list]);
  const [draft, setDraft] = useState<Set<string>>(saved);

  // Reset the draft whenever fresh data arrives from the server.
  useEffect(() => setDraft(saved), [saved]);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return list.databases.filter(
      (d) =>
        (showSystem || !d.is_system || d.selected) &&
        (!needle || d.name.toLowerCase().includes(needle)),
    );
  }, [list, filter, showSystem]);

  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageItems = visible.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  const dirty = !sameSet(draft, saved);

  const toggle = (name: string, checked: boolean) => {
    setDraft((prev) => {
      const next = new Set(prev);
      if (checked) next.add(name);
      else next.delete(name);
      return next;
    });
  };

  return (
    <Stack gap="sm">
      {!list.reachable && (
        <Alert color="orange" title={t(`errors.${list.error_code ?? "server_error"}`)}>
          <Text size="sm">{t("databases.unreachable")}</Text>
          <Button size="xs" variant="light" mt="xs" onClick={onRetry}>
            {t("common.retry")}
          </Button>
        </Alert>
      )}

      <Group justify="space-between" wrap="wrap">
        <TextInput
          placeholder={t("databases.filter")}
          aria-label={t("databases.filter")}
          value={filter}
          onChange={(e) => {
            setFilter(e.currentTarget.value);
            setPage(1);
          }}
          style={{ flex: "1 1 220px" }}
        />
        <Switch
          label={t("databases.showSystem")}
          checked={showSystem}
          onChange={(e) => setShowSystem(e.currentTarget.checked)}
        />
      </Group>

      {list.reachable && (
        <Text size="xs" c="dimmed">
          {t("databases.privilegesNote")}
        </Text>
      )}

      {visible.length === 0 ? (
        <Text c="dimmed" size="sm">
          {list.databases.length === 0 ? t("databases.empty") : t("databases.noMatches")}
        </Text>
      ) : (
        <div className="cl-db-grid">
          {pageItems.map((db) => (
            <Group
              key={db.name}
              gap="xs"
              wrap="nowrap"
              className="cl-db-tile"
              data-checked={draft.has(db.name) || undefined}
            >
              <Checkbox
                label={
                  <span dir="ltr" className="mono">
                    {db.name}
                  </span>
                }
                checked={draft.has(db.name)}
                disabled={!db.selectable}
                onChange={(e) => toggle(db.name, e.currentTarget.checked)}
              />
              {db.is_system && (
                <Badge size="xs" variant="light" color="gray">
                  {t("databases.systemBadge")}
                </Badge>
              )}
              {db.missing && (
                <Tooltip label={t("databases.missingHint")} multiline w={260}>
                  <Badge size="xs" variant="light" color="orange">
                    {t("databases.missingBadge")}
                  </Badge>
                </Tooltip>
              )}
            </Group>
          ))}
        </div>
      )}

      {pageCount > 1 && <Pagination total={pageCount} value={currentPage} onChange={setPage} />}

      <Group justify="space-between">
        <Text size="sm">
          {t("databases.selectedCount", {
            count: draft.size,
            formattedCount: formatNumber(draft.size, i18n.language),
          })}
        </Text>
        <Group gap="xs">
          <Button variant="default" disabled={!dirty || saving} onClick={() => setDraft(saved)}>
            {t("databases.reset")}
          </Button>
          <Button disabled={!dirty} loading={saving} onClick={() => onSave([...draft].sort())}>
            {t("databases.save")}
          </Button>
        </Group>
      </Group>
    </Stack>
  );
}

export function DatabaseSelector({ instanceId }: { instanceId: number }) {
  const { t } = useTranslation();
  const databases = useDatabases(instanceId);
  const save = useSaveSelection(instanceId);

  if (databases.isPending) return <Loader size="sm" />;
  if (databases.isError) {
    return (
      <Alert color="red" title={errorMessage(t, databases.error)}>
        <Button size="xs" variant="light" onClick={() => void databases.refetch()}>
          {t("common.retry")}
        </Button>
      </Alert>
    );
  }

  return (
    <DatabaseSelectorView
      list={databases.data}
      saving={save.isPending}
      onRetry={() => void databases.refetch()}
      onSave={(names) =>
        save.mutate(names, {
          onSuccess: () => notifications.show({ color: "green", message: t("databases.saved") }),
          onError: (error) => notifications.show({ color: "red", message: errorMessage(t, error) }),
        })
      }
    />
  );
}
