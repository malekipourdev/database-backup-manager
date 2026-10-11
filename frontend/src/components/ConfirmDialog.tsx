import { Button, Group, Modal, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";

interface ConfirmDialogProps {
  opened: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog(props: ConfirmDialogProps) {
  const { t } = useTranslation();
  return (
    <Modal opened={props.opened} onClose={props.onCancel} title={props.title} centered>
      <Text mb="lg">{props.body}</Text>
      <Group justify="flex-end">
        <Button variant="default" onClick={props.onCancel} disabled={props.loading}>
          {t("common.cancel")}
        </Button>
        <Button color="red" onClick={props.onConfirm} loading={props.loading}>
          {props.confirmLabel}
        </Button>
      </Group>
    </Modal>
  );
}
