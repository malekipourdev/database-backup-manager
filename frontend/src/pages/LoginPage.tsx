import {
  Alert,
  Button,
  Center,
  Group,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ME_KEY, login, useMe } from "../api/auth";
import { errorMessage } from "../api/client";
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

  const signIn = useMutation({
    mutationFn: (values: { username: string; password: string }) =>
      login(values.username, values.password),
    onSuccess: (data) => {
      queryClient.setQueryData(ME_KEY, data);
      navigate(from, { replace: true });
    },
    onError: () => form.setFieldValue("password", ""),
  });

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
