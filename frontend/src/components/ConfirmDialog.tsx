import { Button, Group, Modal, Text } from "@mantine/core";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface ConfirmDialogProps {
  opened: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  loading?: boolean;
  /** Extra content between the text and the buttons (e.g. an option checkbox). */
  children?: ReactNode;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog(props: ConfirmDialogProps) {
  const { t } = useTranslation();
  return (
    <Modal opened={props.opened} onClose={props.onCancel} title={props.title} centered>
      <Text mb="lg">{props.body}</Text>
      {props.children}
      <Group justify="flex-end">
        <Button variant="default" onClick={props.onCancel} disabled={props.loading}>
          {t("common.cancel")}
        </Button>
        <Button
          color="red"
          onClick={props.onConfirm}
          loading={props.loading}
          disabled={props.confirmDisabled}
        >
          {props.confirmLabel}
        </Button>
      </Group>
    </Modal>
  );
}
