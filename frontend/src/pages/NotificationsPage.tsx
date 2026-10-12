import {
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  NumberInput,
  Pagination,
  Paper,
  PasswordInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ApiError, errorMessage } from "../api/client";
import {
  CHANNELS,
  type Channel,
  type NotificationSettings,
  type NotificationSettingsInput,
  type Severity,
  useNotificationLog,
  useNotificationSettings,
  useSaveNotificationSettings,
  useTestNotification,
} from "../api/notifications";
import { renderAlert } from "../alerts";
import { PageHeader } from "../components/PageHeader";
import { timezoneOptions } from "../components/ScheduleForm";
import { formatDateTime } from "../i18n";

const SEVERITY_COLORS: Record<Severity, string> = { info: "blue", warning: "yellow", error: "red" };

function toInput(s: NotificationSettings): NotificationSettingsInput {
  return {
    rules: s.rules,
    cooldown_minutes: s.cooldown_minutes,
    stale_hours: s.stale_hours,
    disk_free_percent: s.disk_free_percent,
    daily_summary_time: s.daily_summary_time,
    timezone: s.timezone,
    webhook_enabled: s.webhook_enabled,
    webhook_url: s.webhook_url,
    webhook_secret: "",
    clear_webhook_secret: false,
  };
}

function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useTranslation();
  return (
    <Badge color={SEVERITY_COLORS[severity]} variant="light" size="sm" style={{ flexShrink: 0 }}>
      {t(`alerts.severity.${severity}`)}
    </Badge>
  );
}

function SettingsForm({ settings }: { settings: NotificationSettings }) {
  const { t } = useTranslation();
  const save = useSaveNotificationSettings();
  const test = useTestNotification();
  const [values, setValues] = useState(toInput(settings));
  const zones = useMemo(() => timezoneOptions(settings.timezone), [settings.timezone]);
  const set = <K extends keyof NotificationSettingsInput>(
    key: K,
    value: NotificationSettingsInput[K],
  ) => setValues((prev) => ({ ...prev, [key]: value }));
  const setRule = (event: string, enabled: boolean, channels: Channel[]) =>
    setValues((prev) => ({ ...prev, rules: { ...prev.rules, [event]: { enabled, channels } } }));
  const fieldError = (field: string) =>
    save.error instanceof ApiError && save.error.fields?.[field]
      ? t(`alerts.validation.${save.error.fields[field]}`, {
          defaultValue: t("validation.invalid"),
        })
      : null;

  return (
    <Stack gap="md">
      <Paper withBorder p="lg">
        <Title order={4} mb="xs">
          {t("alerts.rules.title")}
        </Title>
        <Text size="sm" c="dimmed" mb="sm">
          {t("alerts.rules.hint")}
        </Text>
        <Table.ScrollContainer minWidth={640}>
          <Table verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("alerts.rules.event")}</Table.Th>
                <Table.Th>{t("alerts.rules.severity")}</Table.Th>
                <Table.Th>{t("alerts.rules.enabled")}</Table.Th>
                {CHANNELS.map((c) => (
                  <Table.Th key={c}>{t(`alerts.channels.${c}`)}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {settings.events.map(({ name, severity }) => {
                const rule = values.rules[name] ?? { enabled: true, channels: [...CHANNELS] };
                return (
                  <Table.Tr key={name} data-testid={`rule-${name}`}>
                    <Table.Td>
                      <Text size="sm">{t(`alerts.names.${name}`)}</Text>
                      <Text size="xs" c="dimmed">
                        {t(`alerts.descriptions.${name}`)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <SeverityBadge severity={severity} />
                    </Table.Td>
                    <Table.Td>
                      <Switch
                        aria-label={t("alerts.rules.enabled")}
                        checked={rule.enabled}
                        onChange={(e) => setRule(name, e.currentTarget.checked, rule.channels)}
                      />
                    </Table.Td>
                    {CHANNELS.map((channel) => (
                      <Table.Td key={channel}>
                        <Checkbox
                          aria-label={t(`alerts.channels.${channel}`)}
                          disabled={!rule.enabled}
                          checked={rule.channels.includes(channel)}
                          onChange={(e) =>
                            setRule(
                              name,
                              rule.enabled,
                              e.currentTarget.checked
                                ? [...rule.channels, channel]
                                : rule.channels.filter((c) => c !== channel),
                            )
                          }
                        />
                      </Table.Td>
                    ))}
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        <Text size="xs" c="dimmed" mt="xs">
          {t("alerts.rules.botNote")}{" "}
          <Anchor component={Link} to="/bots" size="xs">
            {t("nav.bots")}
          </Anchor>
        </Text>
      </Paper>

      <Paper withBorder p="lg">
        <Title order={4} mb="sm">
          {t("alerts.thresholds.title")}
        </Title>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <NumberInput
            label={t("alerts.thresholds.stale")}
            description={t("alerts.thresholds.staleHelp")}
            min={1}
            max={720}
            allowDecimal={false}
            value={values.stale_hours}
            onChange={(v) => set("stale_hours", Number(v) || 1)}
          />
          <NumberInput
            label={t("alerts.thresholds.disk")}
            description={t("alerts.thresholds.diskHelp")}
            min={1}
            max={90}
            allowDecimal={false}
            value={values.disk_free_percent}
            onChange={(v) => set("disk_free_percent", Number(v) || 1)}
          />
          <NumberInput
            label={t("alerts.thresholds.cooldown")}
            description={t("alerts.thresholds.cooldownHelp")}
            min={0}
            max={10080}
            allowDecimal={false}
            value={values.cooldown_minutes}
            onChange={(v) => set("cooldown_minutes", Number(v) || 0)}
          />
          <TextInput
            type="time"
            label={t("alerts.thresholds.summary")}
            description={t("alerts.thresholds.summaryHelp")}
            dir="ltr"
            value={values.daily_summary_time}
            onChange={(e) => set("daily_summary_time", e.currentTarget.value)}
            error={fieldError("daily_summary_time")}
          />
          <Select
            label={t("alerts.thresholds.timezone")}
            description={t("alerts.thresholds.timezoneHelp")}
            searchable
            allowDeselect={false}
            data={zones}
            value={values.timezone}
            onChange={(v) => v && set("timezone", v)}
            error={fieldError("timezone")}
          />
        </SimpleGrid>
      </Paper>

      <Paper withBorder p="lg">
        <Title order={4} mb="xs">
          {t("alerts.webhook.title")}
        </Title>
        <Text size="sm" c="dimmed" mb="sm">
          {t("alerts.webhook.hint")}
        </Text>
        <Stack gap="sm">
          <Switch
            label={t("alerts.webhook.enabled")}
            checked={values.webhook_enabled}
            onChange={(e) => set("webhook_enabled", e.currentTarget.checked)}
          />
          <TextInput
            label={t("alerts.webhook.url")}
            placeholder={t("alerts.webhook.urlPlaceholder")}
            dir="ltr"
            value={values.webhook_url}
            onChange={(e) => set("webhook_url", e.currentTarget.value)}
            error={fieldError("webhook_url")}
          />
          <PasswordInput
            label={t("alerts.webhook.secret")}
            description={
              settings.has_webhook_secret
                ? t("alerts.webhook.secretStored")
                : t("alerts.webhook.secretHelp")
            }
            dir="ltr"
            autoComplete="new-password"
            value={values.webhook_secret}
            onChange={(e) => set("webhook_secret", e.currentTarget.value)}
          />
          {settings.has_webhook_secret && (
            <Checkbox
              label={t("alerts.webhook.clearSecret")}
              checked={values.clear_webhook_secret}
              onChange={(e) => set("clear_webhook_secret", e.currentTarget.checked)}
            />
          )}
        </Stack>
      </Paper>

      {Boolean(save.error) && !(save.error instanceof ApiError && save.error.fields) && (
        <Alert color="red">{errorMessage(t, save.error)}</Alert>
      )}
      {test.data && (
        <Alert color="blue" title={t("alerts.test.results")} data-testid="test-results">
          {Object.entries(test.data.results).map(([channel, result]) => (
            <Text size="sm" key={channel}>
              {t(`alerts.channels.${channel}`)}:{" "}
              {t(`alerts.delivery.${result.split(":")[0]}`, { defaultValue: result })}
              {result.includes(":") && (
                <span dir="ltr"> ({result.split(":").slice(1).join(":").trim()})</span>
              )}
            </Text>
          ))}
        </Alert>
      )}
      <Group justify="space-between">
        <Button
          variant="default"
          loading={test.isPending}
          onClick={() => test.mutate([...CHANNELS])}
        >
          {t("alerts.test.button")}
        </Button>
        <Button
          loading={save.isPending}
          onClick={() =>
            save.mutate(values, {
              onSuccess: (data) => {
                setValues(toInput(data));
                notifications.show({ color: "green", message: t("settings.saved") });
              },
            })
          }
        >
          {t("common.save")}
        </Button>
      </Group>
    </Stack>
  );
}

function AlertHistory() {
  const { t, i18n } = useTranslation();
  const [page, setPage] = useState(1);
  const [severity, setSeverity] = useState<string>("all");
  const log = useNotificationLog(page, severity === "all" ? null : severity);
  useEffect(() => setPage(1), [severity]);
  const data = log.data;
  return (
    <Paper withBorder p="lg">
      <Group justify="space-between" mb="sm" wrap="wrap">
        <Title order={4}>{t("alerts.history.title")}</Title>
        <SegmentedControl
          size="xs"
          value={severity}
          onChange={setSeverity}
          data={[
            { value: "all", label: t("alerts.history.all") },
            { value: "error", label: t("alerts.severity.error") },
            { value: "warning", label: t("alerts.severity.warning") },
            { value: "info", label: t("alerts.severity.info") },
          ]}
        />
      </Group>
      {log.isPending && <Loader size="sm" />}
      {data && data.items.length === 0 && (
        <Text size="sm" c="dimmed">
          {t("alerts.history.empty")}
        </Text>
      )}
      {data && data.items.length > 0 && (
        <>
          <Table.ScrollContainer minWidth={760}>
            <Table verticalSpacing="xs" data-testid="alert-history">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("alerts.history.time")}</Table.Th>
                  <Table.Th>{t("alerts.rules.severity")}</Table.Th>
                  <Table.Th>{t("alerts.history.message")}</Table.Th>
                  <Table.Th>{t("alerts.history.delivery")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.items.map((item) => (
                  <Table.Tr key={item.id}>
                    <Table.Td style={{ whiteSpace: "nowrap" }}>
                      {formatDateTime(item.created_at, i18n.language)}
                    </Table.Td>
                    <Table.Td style={{ width: 90 }}>
                      <SeverityBadge severity={item.severity} />
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                        {renderAlert(item, t, i18n.language)}
                      </Text>
                      {item.run_id !== null && (
                        <Anchor component={Link} to={`/backups`} size="xs">
                          {t("alerts.history.viewBackups")}
                        </Anchor>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {item.suppressed ? (
                        <Tooltip label={t("alerts.history.suppressedHelp")}>
                          <Badge color="gray" variant="outline" size="sm">
                            {t("alerts.history.suppressed")}
                          </Badge>
                        </Tooltip>
                      ) : (
                        <Group gap={4}>
                          {Object.entries(item.channels).map(([channel, result]) => (
                            <Tooltip key={channel} label={result}>
                              <Badge
                                size="sm"
                                variant="light"
                                color={
                                  result.startsWith("sent")
                                    ? "green"
                                    : result.startsWith("failed")
                                      ? "red"
                                      : "gray"
                                }
                              >
                                {t(`alerts.channels.${channel}`)}
                              </Badge>
                            </Tooltip>
                          ))}
                        </Group>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {data.total > data.page_size && (
            <Group justify="center" mt="sm">
              <Pagination
                total={Math.ceil(data.total / data.page_size)}
                value={page}
                onChange={setPage}
                size="sm"
              />
            </Group>
          )}
        </>
      )}
    </Paper>
  );
}

export function NotificationsPage() {
  const { t } = useTranslation();
  const settings = useNotificationSettings();
  return (
    <Stack gap="md">
      <PageHeader help="notifications" title={t("alerts.title")} subtitle={t("alerts.hint")} />
      {settings.isPending && <Loader />}
      {settings.isError && <Alert color="red">{errorMessage(t, settings.error)}</Alert>}
      {settings.data && <SettingsForm settings={settings.data} />}
      <AlertHistory />
    </Stack>
  );
}
