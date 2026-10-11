import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  Select,
  Switch,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { errorMessage } from "../api/client";
import { useInstances } from "../api/instances";
import {
  type Schedule,
  type ScheduleInput,
  toInput,
  useCreateSchedule,
  useDeleteSchedule,
  useSchedules,
  useUpdateSchedule,
} from "../api/schedules";
import { formatDateTime } from "../i18n";
import { ConfirmDialog } from "./ConfirmDialog";
import { CRON_PRESETS, EMPTY_SCHEDULE, ScheduleForm } from "./ScheduleForm";

const RESULT_COLORS: Record<string, string> = {
  queued: "green",
  partially_queued: "yellow",
  already_in_progress: "yellow",
};

function When({ schedule }: { schedule: Schedule }) {
  const { t } = useTranslation();
  const preset = CRON_PRESETS.find((p) => p.cron === schedule.cron);
  return (
    <Text size="sm">
      {preset ? t(`schedules.presets.${preset.key}`) : <span dir="ltr">{schedule.cron}</span>}{" "}
      <Text span size="xs" c="dimmed" dir="ltr">
        ({schedule.timezone})
      </Text>
    </Text>
  );
}

type Editing = { mode: "create" } | { mode: "edit"; schedule: Schedule };

/** Schedules of one instance, or of all instances when `instanceId` is omitted. */
export function ScheduleList({ instanceId }: { instanceId?: number }) {
  const { t, i18n } = useTranslation();
  const schedules = useSchedules(instanceId);
  const instances = useInstances();
  const create = useCreateSchedule();
  const update = useUpdateSchedule();
  const remove = useDeleteSchedule();
  const [editing, setEditing] = useState<Editing | null>(null);
  const [targetInstance, setTargetInstance] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Schedule | null>(null);
  const showInstance = instanceId === undefined;

  const close = () => {
    setEditing(null);
    create.reset();
    update.reset();
  };

  const save = (body: ScheduleInput) => {
    const onSuccess = () => {
      notifications.show({ color: "green", message: t("schedules.saved") });
      close();
    };
    if (editing?.mode === "edit") {
      update.mutate({ id: editing.schedule.id, body }, { onSuccess });
      return;
    }
    const target = instanceId ?? Number(targetInstance);
    if (!target) return;
    create.mutate({ instanceId: target, body }, { onSuccess });
  };

  const toggle = (schedule: Schedule, enabled: boolean) =>
    update.mutate(
      { id: schedule.id, body: { ...toInput(schedule), enabled } },
      { onError: (error) => notifications.show({ color: "red", message: errorMessage(t, error) }) },
    );

  const items = schedules.data ?? [];
  const instanceOptions = (instances.data ?? []).map((i) => ({
    value: String(i.id),
    label: i.name,
  }));

  return (
    <>
      <Group justify="flex-end" mb="sm">
        <Button
          size="xs"
          onClick={() => {
            setTargetInstance(instanceOptions[0]?.value ?? null);
            setEditing({ mode: "create" });
          }}
          disabled={showInstance && instanceOptions.length === 0}
        >
          {t("schedules.add")}
        </Button>
      </Group>

      {schedules.isError && <Text c="red">{errorMessage(t, schedules.error)}</Text>}
      {schedules.isSuccess && items.length === 0 && (
        <Text size="sm" c="dimmed">
          {t("schedules.empty")}
        </Text>
      )}
      {items.length > 0 && (
        <Table.ScrollContainer minWidth={760}>
          <Table verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("schedules.fields.name")}</Table.Th>
                {showInstance && <Table.Th>{t("backups.columns.instance")}</Table.Th>}
                <Table.Th>{t("schedules.columns.when")}</Table.Th>
                <Table.Th>{t("schedules.fields.scope")}</Table.Th>
                <Table.Th>{t("schedules.columns.nextRun")}</Table.Th>
                <Table.Th>{t("schedules.columns.lastRun")}</Table.Th>
                <Table.Th>{t("schedules.fields.enabled")}</Table.Th>
                <Table.Th>{t("backups.columns.actions")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((schedule) => (
                <Table.Tr key={schedule.id}>
                  <Table.Td>{schedule.name}</Table.Td>
                  {showInstance && <Table.Td>{schedule.instance_name}</Table.Td>}
                  <Table.Td>
                    <When schedule={schedule} />
                  </Table.Td>
                  <Table.Td>
                    {schedule.scope === "all" ? (
                      t("schedules.scope.all")
                    ) : (
                      <span dir="ltr">{schedule.database}</span>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {schedule.next_run_at
                      ? formatDateTime(schedule.next_run_at, i18n.language)
                      : t("common.notAvailable")}
                  </Table.Td>
                  <Table.Td>
                    {schedule.last_fired_at ? (
                      <Group gap={4} wrap="nowrap">
                        <Badge
                          variant="light"
                          color={RESULT_COLORS[schedule.last_result ?? ""] ?? "red"}
                        >
                          {t(`schedules.result.${schedule.last_result}`, {
                            defaultValue: t("errors.internal_error"),
                          })}
                        </Badge>
                        <Text size="xs" c="dimmed">
                          {formatDateTime(schedule.last_fired_at, i18n.language)}
                        </Text>
                      </Group>
                    ) : (
                      t("schedules.neverRun")
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Switch
                      aria-label={t("schedules.fields.enabled")}
                      checked={schedule.enabled}
                      onChange={(e) => toggle(schedule, e.currentTarget.checked)}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <Button
                        size="xs"
                        variant="default"
                        onClick={() => setEditing({ mode: "edit", schedule })}
                      >
                        {t("common.edit")}
                      </Button>
                      <Tooltip label={t("common.delete")}>
                        <ActionIcon
                          color="red"
                          variant="subtle"
                          aria-label={t("common.delete")}
                          onClick={() => setDeleting(schedule)}
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
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <Modal
        opened={editing !== null}
        onClose={close}
        title={editing?.mode === "edit" ? t("schedules.editTitle") : t("schedules.createTitle")}
        size="lg"
      >
        {editing && (
          <ScheduleForm
            initial={editing.mode === "edit" ? toInput(editing.schedule) : EMPTY_SCHEDULE}
            saving={create.isPending || update.isPending}
            error={create.error ?? update.error}
            onSave={save}
            onCancel={close}
            header={
              showInstance &&
              editing.mode === "create" && (
                <Select
                  label={t("backups.columns.instance")}
                  data={instanceOptions}
                  value={targetInstance}
                  onChange={setTargetInstance}
                  allowDeselect={false}
                  required
                />
              )
            }
          />
        )}
      </Modal>

      <ConfirmDialog
        opened={deleting !== null}
        title={t("schedules.deleteTitle")}
        body={deleting ? t("schedules.deleteConfirm", { name: deleting.name }) : ""}
        confirmLabel={t("common.delete")}
        loading={remove.isPending}
        onConfirm={() =>
          deleting &&
          remove.mutate(deleting.id, {
            onSuccess: () => {
              notifications.show({ color: "green", message: t("schedules.deleted") });
              setDeleting(null);
            },
            onError: (error) => {
              notifications.show({ color: "red", message: errorMessage(t, error) });
              setDeleting(null);
            },
          })
        }
        onCancel={() => setDeleting(null)}
      />
    </>
  );
}
