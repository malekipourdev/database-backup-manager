import {
  Alert,
  Badge,
  Button,
  Code,
  CopyButton,
  Group,
  List,
  Loader,
  Modal,
  Paper,
  PasswordInput,
  PinInput,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type TwoFactorSetup,
  useDisableTwoFactor,
  useEnableTwoFactor,
  useMe,
  useRegenerateRecoveryCodes,
  useStartTwoFactorSetup,
  useTwoFactorStatus,
} from "../api/auth";
import { ApiError, errorMessage } from "../api/client";
import { ShieldCheck } from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { formatNumber } from "../i18n";

function fieldError(t: (k: string) => string, error: unknown, field: string): string | null {
  if (!(error instanceof ApiError) || !error.fields?.[field]) return null;
  return t(`account.validation.${error.fields[field]}`);
}

/** Recovery codes, shown once, with copy and download. */
function RecoveryCodesView({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const { t } = useTranslation();
  const text = codes.join("\n");
  const download = () => {
    const url = URL.createObjectURL(new Blob([`${text}\n`], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "mbp-recovery-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Stack gap="md">
      <Alert color="yellow" variant="light" title={t("account.codesTitle")}>
        {t("account.codesHint")}
      </Alert>
      <SimpleGrid cols={2} spacing="xs" data-testid="recovery-codes">
        {codes.map((code) => (
          <Code key={code} dir="ltr" ta="center" fz="md" py={6}>
            {code}
          </Code>
        ))}
      </SimpleGrid>
      <Group justify="space-between">
        <Group gap="xs">
          <CopyButton value={text}>
            {({ copied, copy }) => (
              <Button variant="default" onClick={copy}>
                {copied ? t("backups.copied") : t("account.copyCodes")}
              </Button>
            )}
          </CopyButton>
          <Button variant="default" onClick={download}>
            {t("account.downloadCodes")}
          </Button>
        </Group>
        <Button onClick={onDone}>{t("account.savedCodes")}</Button>
      </Group>
    </Stack>
  );
}

function EnableFlow({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const start = useStartTwoFactorSetup();
  const enable = useEnableTwoFactor();
  const [password, setPassword] = useState("");
  const [setup, setSetup] = useState<TwoFactorSetup | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);

  if (codes) {
    return (
      <RecoveryCodesView
        codes={codes}
        onDone={() => {
          notifications.show({ color: "green", message: t("account.enabled") });
          onClose();
        }}
      />
    );
  }

  if (!setup) {
    return (
      <form
        onSubmit={(e) => {
          e.preventDefault();
          start.mutate(password, { onSuccess: setSetup });
        }}
      >
        <Stack gap="md">
          <Text size="sm">{t("account.passwordFirst")}</Text>
          <PasswordInput
            label={t("auth.password")}
            dir="ltr"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            error={fieldError(t, start.error, "password")}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" loading={start.isPending} disabled={!password}>
              {t("account.continue")}
            </Button>
          </Group>
        </Stack>
      </form>
    );
  }

  const confirm = (value: string) =>
    enable.mutate(value, {
      onSuccess: (data) => setCodes(data.recovery_codes),
      onError: () => setCode(""),
    });

  return (
    <Stack gap="md">
      <List type="ordered" size="sm" spacing={4}>
        <List.Item>{t("account.step1")}</List.Item>
        <List.Item>{t("account.step2")}</List.Item>
        <List.Item>{t("account.step3")}</List.Item>
      </List>
      <Group align="flex-start" gap="lg" wrap="wrap" justify="center">
        <img
          src={setup.qr_svg}
          alt={t("account.qrAlt")}
          width={200}
          height={200}
          style={{ borderRadius: 12, background: "#fff" }}
          data-testid="totp-qr"
        />
        <Stack gap={6} style={{ flex: "1 1 220px" }}>
          <Text size="sm" c="var(--color-neutral-300)">
            {t("account.manualKey")}
          </Text>
          <Group gap={6} wrap="nowrap">
            <TextInput
              readOnly
              value={setup.secret}
              dir="ltr"
              styles={{ input: { fontFamily: "var(--font-mono)", letterSpacing: 1 } }}
              style={{ flex: 1 }}
              aria-label={t("account.manualKey")}
            />
            <CopyButton value={setup.secret}>
              {({ copied, copy }) => (
                <Button variant="default" onClick={copy}>
                  {copied ? t("backups.copied") : t("backups.copy")}
                </Button>
              )}
            </CopyButton>
          </Group>
          <Text size="xs" c="dimmed">
            {t("account.manualHint")}
          </Text>
        </Stack>
      </Group>
      <Stack gap={6} align="center">
        <Text size="sm">{t("account.enterCode")}</Text>
        <PinInput
          length={6}
          type="number"
          oneTimeCode
          dir="ltr"
          aria-label={t("auth.code")}
          value={code}
          onChange={setCode}
          onComplete={confirm}
          error={Boolean(enable.error)}
        />
        {enable.error && (
          <Text size="sm" c="red">
            {errorMessage(t, enable.error)}
          </Text>
        )}
      </Stack>
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button
          loading={enable.isPending}
          disabled={code.length !== 6}
          onClick={() => confirm(code)}
        >
          {t("account.enable")}
        </Button>
      </Group>
    </Stack>
  );
}

/** Password + code form for turning 2FA off or replacing the recovery codes. */
function ConfirmWithCode(props: { action: "disable" | "regenerate"; onClose: () => void }) {
  const { t } = useTranslation();
  const disable = useDisableTwoFactor();
  const regenerate = useRegenerateRecoveryCodes();
  const mutation = props.action === "disable" ? disable : regenerate;
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);

  if (codes) return <RecoveryCodesView codes={codes} onDone={props.onClose} />;

  const submit = () => {
    if (props.action === "disable") {
      disable.mutate(
        { password, code },
        {
          onSuccess: () => {
            notifications.show({ color: "green", message: t("account.disabled") });
            props.onClose();
          },
        },
      );
    } else {
      regenerate.mutate({ password, code }, { onSuccess: (data) => setCodes(data.recovery_codes) });
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <Stack gap="md">
        <Text size="sm">
          {props.action === "disable" ? t("account.disableHint") : t("account.regenerateHint")}
        </Text>
        <PasswordInput
          label={t("auth.password")}
          dir="ltr"
          autoComplete="current-password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.currentTarget.value)}
          error={fieldError(t, mutation.error, "password")}
        />
        <TextInput
          label={t("account.codeOrRecovery")}
          dir="ltr"
          autoComplete="one-time-code"
          value={code}
          onChange={(e) => setCode(e.currentTarget.value)}
          error={fieldError(t, mutation.error, "code")}
        />
        {Boolean(mutation.error) &&
          !(mutation.error instanceof ApiError && mutation.error.fields) && (
            <Alert color="red" variant="light">
              {errorMessage(t, mutation.error)}
            </Alert>
          )}
        <Group justify="flex-end">
          <Button variant="default" onClick={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            color={props.action === "disable" ? "red" : undefined}
            loading={mutation.isPending}
            disabled={!password || !code}
          >
            {props.action === "disable" ? t("account.disable") : t("account.regenerate")}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function AccountPage() {
  const { t, i18n } = useTranslation();
  const me = useMe();
  const status = useTwoFactorStatus();
  const [dialog, setDialog] = useState<"enable" | "disable" | "regenerate" | null>(null);
  const enabled = status.data?.enabled ?? false;
  const left = status.data?.recovery_codes_left ?? 0;

  return (
    <Stack gap="md">
      <PageHeader
        title={t("account.title")}
        subtitle={me.data ? t("account.subtitle", { name: me.data.username }) : undefined}
      />
      <Paper withBorder p="lg" maw={720}>
        <Group justify="space-between" mb="sm" wrap="nowrap" align="flex-start">
          <Group gap="sm" wrap="nowrap">
            <span className="cl-icon-tile">
              <ShieldCheck size={20} />
            </span>
            <div>
              <Title order={4}>{t("account.twoFactor")}</Title>
              <Text size="sm" c="var(--color-neutral-400)">
                {t("account.twoFactorHint")}
              </Text>
            </div>
          </Group>
          {status.data && (
            <Badge
              color={enabled ? "green" : "gray"}
              style={{ flexShrink: 0, overflow: "visible" }}
              data-testid="two-factor-state"
            >
              {enabled ? t("account.on") : t("account.off")}
            </Badge>
          )}
        </Group>
        {status.isPending && <Loader size="sm" />}
        {status.isError && <Alert color="red">{errorMessage(t, status.error)}</Alert>}
        {status.data && !enabled && (
          <Group justify="flex-end" mt="md">
            <Button leftSection={<ShieldCheck size={16} />} onClick={() => setDialog("enable")}>
              {t("account.setUp")}
            </Button>
          </Group>
        )}
        {status.data && enabled && (
          <Stack gap="sm" mt="md">
            <Text size="sm">
              {t("account.codesLeft", { n: formatNumber(left, i18n.language) })}
            </Text>
            {left <= 2 && (
              <Alert color="yellow" variant="light">
                {t("account.codesLow")}
              </Alert>
            )}
            <Group justify="flex-end" gap="xs">
              <Button variant="default" onClick={() => setDialog("regenerate")}>
                {t("account.regenerate")}
              </Button>
              <Button color="red" onClick={() => setDialog("disable")}>
                {t("account.disable")}
              </Button>
            </Group>
          </Stack>
        )}
      </Paper>

      <Modal
        opened={dialog !== null}
        onClose={() => setDialog(null)}
        title={
          dialog === "enable"
            ? t("account.setUpTitle")
            : dialog === "disable"
              ? t("account.disableTitle")
              : t("account.regenerateTitle")
        }
        size="lg"
        closeOnClickOutside={false}
      >
        {dialog === "enable" && <EnableFlow onClose={() => setDialog(null)} />}
        {(dialog === "disable" || dialog === "regenerate") && (
          <ConfirmWithCode action={dialog} onClose={() => setDialog(null)} />
        )}
      </Modal>
    </Stack>
  );
}
