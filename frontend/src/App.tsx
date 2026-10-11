import {
  Center,
  DirectionProvider,
  Loader,
  MantineProvider,
  createTheme,
  useDirection,
} from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { ME_KEY, useMe } from "./api/auth";
import { isApiError } from "./api/client";
import { Layout } from "./components/Layout";
import i18n, { directionOf } from "./i18n";
import { BackupHistoryPage } from "./pages/BackupHistoryPage";
import { BackupSettingsPage } from "./pages/BackupSettingsPage";
import { InstanceDetailPage } from "./pages/InstanceDetailPage";
import { InstanceFormPage } from "./pages/InstanceFormPage";
import { InstancesPage } from "./pages/InstancesPage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { notifications } from "@mantine/notifications";

const theme = createTheme({
  fontFamily: "Vazirmatn, system-ui, -apple-system, 'Segoe UI', sans-serif",
  headings: { fontFamily: "Vazirmatn, system-ui, -apple-system, 'Segoe UI', sans-serif" },
  primaryColor: "indigo",
});

export function createQueryClient(): QueryClient {
  // Any request that finds the session gone sends the admin back to the login page.
  const onError = (error: unknown) => {
    if (!isApiError(error, "not_authenticated")) return;
    if (queryClient.getQueryData(ME_KEY) === null) return;
    queryClient.clear();
    queryClient.setQueryData(ME_KEY, null);
    notifications.show({ color: "orange", message: i18n.t("auth.sessionExpired") });
  };
  const queryClient: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: {
        retry: (count, error) => !isApiError(error) && count < 2,
        refetchOnWindowFocus: false,
      },
    },
  });
  return queryClient;
}

function DirectionSync() {
  const { i18n: i18nInstance } = useTranslation();
  const { setDirection } = useDirection();
  useEffect(() => {
    setDirection(directionOf(i18nInstance.language));
  }, [i18nInstance.language, setDirection]);
  return null;
}

function RequireAuth() {
  const { t } = useTranslation();
  const me = useMe();
  const location = useLocation();
  if (me.isPending) {
    return (
      <Center mih="100vh" aria-label={t("common.loading")}>
        <Loader />
      </Center>
    );
  }
  if (!me.data) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/instances" replace />} />
          <Route path="/instances" element={<InstancesPage />} />
          <Route path="/instances/new" element={<InstanceFormPage />} />
          <Route path="/instances/:id" element={<InstanceDetailPage />} />
          <Route path="/instances/:id/edit" element={<InstanceFormPage />} />
          <Route path="/backups" element={<BackupHistoryPage />} />
          <Route path="/settings/backups" element={<BackupSettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}

export function App() {
  const [queryClient] = useState(createQueryClient);
  return (
    <DirectionProvider initialDirection={directionOf(i18n.language)} detectDirection={false}>
      <MantineProvider theme={theme}>
        <DirectionSync />
        <Notifications position="top-center" />
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </QueryClientProvider>
      </MantineProvider>
    </DirectionProvider>
  );
}
