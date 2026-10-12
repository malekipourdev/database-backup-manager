import { Alert, Button, Drawer, Group, Loader, Stack, Text } from "@mantine/core";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { errorMessage } from "../api/client";
import { useDeployment } from "../api/projects";
import { formatDateTime, formatNumber } from "../i18n";
import { DeployStatusBadge } from "./DeployStatusBadge";
import { ArrowClockwise } from "./Icons";

export function DeploymentDrawer(props: {
  id: number | null;
  onClose: () => void;
  onRedeploy?: (commit: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const deployment = useDeployment(props.id);
  const box = useRef<HTMLPreElement>(null);
  const log = deployment.data?.log;
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [log]);
  const d = deployment.data;
  return (
    <Drawer
      opened={props.id !== null}
      onClose={props.onClose}
      position="right"
      size="xl"
      title={
        <Text fw={600}>
          {t("projects.deploymentTitle", {
            id: props.id === null ? "" : formatNumber(props.id, i18n.language),
          })}
        </Text>
      }
    >
      {deployment.isPending && <Loader size="sm" />}
      {deployment.isError && <Alert color="red">{errorMessage(t, deployment.error)}</Alert>}
      {d && (
        <Stack gap="sm">
          <Group justify="space-between" wrap="wrap">
            <Group gap="xs">
              <DeployStatusBadge d={d} />
              <Text size="sm" dir="ltr">
                {d.commit_sha ? d.commit_sha.slice(0, 8) : d.ref}
              </Text>
              {d.commit_message && (
                <Text size="sm" c="dimmed" truncate maw={320}>
                  {d.commit_message}
                </Text>
              )}
            </Group>
            {props.onRedeploy && d.status === "success" && d.commit_sha && (
              <Button
                size="xs"
                variant="default"
                leftSection={<ArrowClockwise size={14} />}
                onClick={() => props.onRedeploy!(d.commit_sha!)}
              >
                {t("projects.redeploy")}
              </Button>
            )}
          </Group>
          <Text size="xs" c="dimmed">
            {t("projects.requestedBy", {
              actor: d.actor,
              source: t(`containers.activity.sources.${d.trigger}`, { defaultValue: d.trigger }),
              time: formatDateTime(d.requested_at, i18n.language),
            })}
          </Text>
          {d.status === "failed" && d.error_code && (
            <Alert color="red" variant="light">
              {t(`projects.errors.${d.error_code}`, {
                defaultValue: t(`errors.${d.error_code}`, { defaultValue: d.error_code }),
              })}
              {d.error_detail && (
                <Text size="xs" mt={4} dir="ltr" ta="start" ff="var(--font-mono)">
                  {d.error_detail}
                </Text>
              )}
            </Alert>
          )}
          <pre
            ref={box}
            dir="ltr"
            data-testid="deploy-log"
            style={{
              margin: 0,
              background: "var(--color-neutral-950, #0b0b10)",
              border: "1px solid var(--color-neutral-800)",
              borderRadius: 10,
              padding: "10px 12px",
              height: "62vh",
              overflow: "auto",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              lineHeight: 1.55,
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
              textAlign: "left",
            }}
          >
            {d.log || t("projects.logEmpty")}
          </pre>
        </Stack>
      )}
    </Drawer>
  );
}
