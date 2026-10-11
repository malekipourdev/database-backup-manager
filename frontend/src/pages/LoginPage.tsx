import {
  Alert,
  Anchor,
  Button,
  Center,
  Group,
  Paper,
  PasswordInput,
  PinInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ME_KEY, login, loginSecondFactor, useMe } from "../api/auth";
import { errorMessage, isApiError } from "../api/client";
import { Lock } from "../components/Icons";
import { Brand, LanguageSeg, accessInfo } from "../components/Layout";

interface LocationState {
  from?: string;
}

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const me = useMe();
  const from = (location.state as LocationState | null)?.from ?? "/instances";

  const form = useForm({
    initialValues: { username: "", password: "" },
    validate: {
      username: (v) => (v.trim() ? null : t("validation.required")),
      password: (v) => (v ? null : t("validation.required")),
    },
  });

  const [challenge, setChallenge] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);

  const finish = (username: string) => {
    queryClient.setQueryData(ME_KEY, { username });
    // Re-read the account (e.g. its 2FA state) in the background.
    void queryClient.invalidateQueries({ queryKey: ME_KEY });
    navigate(from, { replace: true });
  };

  const signIn = useMutation({
    mutationFn: (values: { username: string; password: string }) =>
      login(values.username, values.password),
    onSuccess: (data) => {
      if (data.two_factor_required && data.challenge) {
        setChallenge(data.challenge);
        setCode("");
        return;
      }
      finish(data.username);
    },
    onError: () => form.setFieldValue("password", ""),
  });

  const verify = useMutation({
    mutationFn: (value: string) => loginSecondFactor(challenge ?? "", value),
    onSuccess: (data) => finish(data.username),
    onError: (error) => {
      setCode("");
      // The 5-minute step expired: start over with the password.
      if (isApiError(error, "challenge_expired")) {
        setChallenge(null);
        form.setFieldValue("password", "");
      }
    },
  });

  const submitCode = (value: string) => {
    if (verify.isPending) return;
    verify.mutate(value);
  };

  if (me.data) return <Navigate to={from} replace />;

  const access = accessInfo();
  return (
    <div className="cl-app" data-glow>
      <Center mih="100vh" w="100%" p="md">
        <Stack w="100%" maw={400} gap="md">
          <Group justify="space-between" wrap="nowrap">
            <Group gap={10} wrap="nowrap">
              <Brand compact />
              <Text fw={500}>{t("common.appName")}</Text>
            </Group>
            <LanguageSeg />
          </Group>
          <Paper withBorder p={28}>
            {challenge ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (code.trim()) submitCode(code.trim());
                }}
                noValidate
              >
                <Stack gap="md">
                  <div>
                    <Title order={3} fz={22}>
                      {t("auth.twoFactorTitle")}
                    </Title>
                    <Text size="sm" mt={6} c="var(--color-neutral-300)">
                      {useRecovery ? t("auth.recoveryHint") : t("auth.twoFactorHint")}
                    </Text>
                  </div>
                  {verify.isError && (
                    <Alert color="red" variant="light" role="alert">
                      {errorMessage(t, verify.error)}
                    </Alert>
                  )}
                  {useRecovery ? (
                    <TextInput
                      label={t("auth.recoveryCode")}
                      dir="ltr"
                      autoComplete="off"
                      autoFocus
                      value={code}
                      onChange={(e) => setCode(e.currentTarget.value)}
                    />
                  ) : (
                    <Stack gap={6} align="center">
                      <Text size="sm" c="var(--color-neutral-300)" style={{ alignSelf: "stretch" }}>
                        {t("auth.code")}
                      </Text>
                      <PinInput
                        length={6}
                        type="number"
                        oneTimeCode
                        autoFocus
                        size="md"
                        dir="ltr"
                        aria-label={t("auth.code")}
                        value={code}
                        onChange={setCode}
                        onComplete={submitCode}
                      />
                    </Stack>
                  )}
                  <Button type="submit" loading={verify.isPending} fullWidth size="md" mt={4}>
                    {t("auth.verify")}
                  </Button>
                  <Group justify="space-between">
                    <Anchor
                      component="button"
                      type="button"
                      size="sm"
                      onClick={() => {
                        setUseRecovery((v) => !v);
                        setCode("");
                        verify.reset();
                      }}
                    >
                      {useRecovery ? t("auth.useAuthenticator") : t("auth.useRecovery")}
                    </Anchor>
                    <Anchor
                      component="button"
                      type="button"
                      size="sm"
                      c="var(--color-neutral-400)"
                      onClick={() => {
                        setChallenge(null);
                        setUseRecovery(false);
                        verify.reset();
                        form.setFieldValue("password", "");
                      }}
                    >
                      {t("common.back")}
                    </Anchor>
                  </Group>
                </Stack>
              </form>
            ) : (
              <form onSubmit={form.onSubmit((values) => signIn.mutate(values))} noValidate>
                <Stack gap="md">
                  <div>
                    <Title order={3} fz={22}>
                      {t("auth.title")}
                    </Title>
                    <Text size="sm" mt={6} c="var(--color-neutral-300)">
                      {t("auth.subtitle")}
                    </Text>
                  </div>
                  {signIn.isError && (
                    <Alert color="red" variant="light" role="alert">
                      {errorMessage(t, signIn.error)}
                    </Alert>
                  )}
                  <TextInput
                    label={t("auth.username")}
                    autoComplete="username"
                    dir="ltr"
                    required
                    {...form.getInputProps("username")}
                  />
                  <PasswordInput
                    label={t("auth.password")}
                    autoComplete="current-password"
                    dir="ltr"
                    required
                    {...form.getInputProps("password")}
                  />
                  <Button type="submit" loading={signIn.isPending} fullWidth size="md" mt={4}>
                    {t("auth.signIn")}
                  </Button>
                </Stack>
              </form>
            )}
          </Paper>
          <Group gap={6} justify="center" c="var(--color-neutral-500)" fz={12}>
            <Lock size={13} />
            <span>{access.local ? t("layout.loginLocal") : t("layout.loginNetwork")}</span>
            <code dir="ltr">{access.host}</code>
          </Group>
        </Stack>
      </Center>
    </div>
  );
}
