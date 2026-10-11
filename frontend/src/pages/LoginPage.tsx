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
import { LanguageSwitcher } from "../components/LanguageSwitcher";

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

  return (
    <Center mih="100vh" p="md">
      <Stack w="100%" maw={380} gap="md">
        <Group justify="flex-end">
          <LanguageSwitcher />
        </Group>
        <Paper withBorder shadow="sm" p="xl" radius="md">
          <form onSubmit={form.onSubmit((values) => signIn.mutate(values))} noValidate>
            <Stack gap="md">
              <div>
                <Title order={3}>{t("common.appName")}</Title>
                <Text size="sm" c="dimmed" mt={4}>
                  {t("auth.subtitle")}
                </Text>
              </div>
              {signIn.isError && (
                <Alert color="red" role="alert">
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
              <Button type="submit" loading={signIn.isPending} fullWidth>
                {t("auth.signIn")}
              </Button>
            </Stack>
          </form>
        </Paper>
      </Stack>
    </Center>
  );
}
